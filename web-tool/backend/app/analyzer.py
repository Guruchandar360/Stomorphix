import csv
import os
import re
import threading
import uuid
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = APP_DIR / "outputs"
YOLO_CONFIG_DIR = OUTPUT_DIR / "ultralytics"
YOLO_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(YOLO_CONFIG_DIR))

import cv2
import numpy as np
from ultralytics import YOLO


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_PATH = ROOT_DIR / "models" / "yolo11n_stomata" / "weights" / "best.pt"
_model_path_override = os.getenv("STOMASPOT_MODEL_PATH", "").strip()
MODEL_PATH = Path(_model_path_override).resolve() if _model_path_override else DEFAULT_MODEL_PATH
UPLOAD_DIR = OUTPUT_DIR / "uploads"
ANNOTATED_DIR = OUTPUT_DIR / "annotated"
COUNT_REPORT_DIR = OUTPUT_DIR / "counts"

for directory in (UPLOAD_DIR, ANNOTATED_DIR, COUNT_REPORT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

_model = None
_inference_lock = threading.Lock()
_inference_slots = threading.BoundedSemaphore(int(os.getenv("MAX_INFERENCE_QUEUE", "8")))

ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(25 * 1024 * 1024)))
MAX_DETECTIONS = int(os.getenv("MAX_DETECTIONS", "1000"))
INFERENCE_QUEUE_TIMEOUT_SECONDS = float(os.getenv("INFERENCE_QUEUE_TIMEOUT_SECONDS", "30"))


class InferenceBusyError(RuntimeError):
    pass


def get_model():
    global _model
    if _model is None:
        _model = YOLO(str(MODEL_PATH))
    return _model


def save_upload(upload_file, destination_dir: Path = UPLOAD_DIR, filename: str | None = None) -> Path:
    suffix = Path(upload_file.filename or "image.jpg").suffix.lower() or ".jpg"
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported image format: {suffix or 'unknown'}.")

    destination_dir.mkdir(parents=True, exist_ok=True)
    image_id = uuid.uuid4().hex if filename is None else sanitize_stem(filename)
    image_path = destination_dir / f"{image_id}{suffix}"
    total_bytes = 0
    with image_path.open("wb") as f:
        while chunk := upload_file.file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > MAX_IMAGE_BYTES:
                f.close()
                image_path.unlink(missing_ok=True)
                raise ValueError(
                    f"{upload_file.filename or 'Image'} exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit."
                )
            f.write(chunk)
    return image_path


def sanitize_stem(value: str) -> str:
    stem = Path(value).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned[:80] or uuid.uuid4().hex


def normalize_polygon(points: np.ndarray):
    """Normalize a detection polygon and find a label position."""
    points = np.rint(points).astype(np.int32)
    if len(points) < 3:
        raise ValueError("At least 3 points are required to form a detection polygon.")
    x, y, width, height = cv2.boundingRect(points)
    if width <= 0 or height <= 0:
        raise ValueError("The detection polygon must cover a visible region.")
    return points, (x + width // 2, y + height // 2)


def analyze_image(
    image_path: Path,
    confidence: float,
    iou: float,
    *,
    output_dir: Path | None = None,
    image_id: str | None = None,
    display_name: str | None = None,
):
    model = get_model()
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("Unable to read uploaded image.")

    if not _inference_slots.acquire(timeout=INFERENCE_QUEUE_TIMEOUT_SECONDS):
        raise InferenceBusyError("The analyzer is at capacity. Please retry shortly.")
    try:
        # Ultralytics models are not safe to invoke concurrently from multiple requests.
        with _inference_lock:
            results = model.predict(
                source=str(image_path),
                imgsz=1280,
                conf=confidence,
                iou=iou,
                max_det=MAX_DETECTIONS,
                save=False,
                verbose=False,
            )
    finally:
        _inference_slots.release()

    result = results[0]
    detections = []

    if result.masks is not None:
        for idx, mask_xy in enumerate(result.masks.xy, start=1):
            pts, (cx, cy) = normalize_polygon(mask_xy)
            detection = {
                "stoma_id": idx,
                "contour": [[int(pt[0]), int(pt[1])] for pt in mask_xy],
            }
            detections.append(detection)

            cv2.polylines(image, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
            cv2.putText(
                image,
                f"#{idx}",
                (cx + 8, cy - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

    image_id = sanitize_stem(image_id or image_path.stem)
    if output_dir is None:
        annotated_dir = ANNOTATED_DIR
        count_report_dir = COUNT_REPORT_DIR
        raw_url = f"/outputs/uploads/{image_path.name}"
        annotated_url_prefix = "/outputs/annotated"
        count_report_url_prefix = "/outputs/counts"
    else:
        annotated_dir = output_dir / "annotated"
        count_report_dir = output_dir / "counts"
        annotated_dir.mkdir(parents=True, exist_ok=True)
        count_report_dir.mkdir(parents=True, exist_ok=True)
        batch_id = output_dir.name
        raw_url = f"/outputs/batches/{batch_id}/uploads/{image_path.name}"
        annotated_url_prefix = f"/outputs/batches/{batch_id}/annotated"
        count_report_url_prefix = f"/outputs/batches/{batch_id}/counts"

    annotated_path = annotated_dir / f"{image_id}_annotated.jpg"
    count_report_path = count_report_dir / f"{image_id}_count.csv"
    cv2.imwrite(str(annotated_path), image)
    count = len(detections)
    write_count_csv(count_report_path, display_name or image_path.name, count)

    summary = {"stomata_count": count}

    return {
        "image_id": image_id,
        "original_name": display_name or image_path.name,
        "stomata_count": count,
        "confidence": confidence,
        "iou": iou,
        "summary": summary,
        "detections": detections,
        "annotated_image_url": f"{annotated_url_prefix}/{annotated_path.name}",
        "raw_image_url": raw_url,
        "count_report_url": f"{count_report_url_prefix}/{count_report_path.name}",
    }


def write_count_csv(csv_path: Path, filename: str, count: int):
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "stomata_count"])
        writer.writeheader()
        writer.writerow({"filename": filename, "stomata_count": count})
