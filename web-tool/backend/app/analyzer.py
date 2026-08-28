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
DEFAULT_MODEL_PATH = ROOT_DIR / "models" / "yolo11s_stomata" / "weights" / "best.pt"
_model_path_override = os.getenv("STOMORPHIX_MODEL_PATH", "").strip()
MODEL_PATH = Path(_model_path_override).resolve() if _model_path_override else DEFAULT_MODEL_PATH
UPLOAD_DIR = OUTPUT_DIR / "uploads"
ANNOTATED_DIR = OUTPUT_DIR / "annotated"
CSV_DIR = OUTPUT_DIR / "csv"

for directory in (UPLOAD_DIR, ANNOTATED_DIR, CSV_DIR):
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


def polygon_region_metrics(points: np.ndarray):
    """Measure a polygon as a filled region using equivalent-ellipse moments."""
    points = np.rint(points).astype(np.int32)
    x, y, width, height = cv2.boundingRect(points)
    if width <= 0 or height <= 0:
        return {
            "area": 0.0,
            "centroid": (0, 0),
            "major_axis": 0.0,
            "minor_axis": 0.0,
            "angle": 0.0,
            "points": points,
        }
    local_points = points - np.array([x, y], dtype=np.int32)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [local_points], 1)
    moments = cv2.moments(mask, binaryImage=True)
    area = float(moments["m00"])

    if area:
        local_cx = moments["m10"] / area
        local_cy = moments["m01"] / area
        covariance = np.array(
            [
                [moments["mu20"] / area, moments["mu11"] / area],
                [moments["mu11"] / area, moments["mu02"] / area],
            ],
            dtype=float,
        )
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        eigenvalues = np.maximum(eigenvalues, 0)
        major_index = int(np.argmax(eigenvalues))
        minor_index = 1 - major_index
        major_axis = 4.0 * np.sqrt(eigenvalues[major_index])
        minor_axis = 4.0 * np.sqrt(eigenvalues[minor_index])
        major_vector = eigenvectors[:, major_index]
        angle = float(np.degrees(np.arctan2(major_vector[1], major_vector[0])))
        centroid = (int(round(x + local_cx)), int(round(y + local_cy)))
    else:
        (_, _), (rect_width, rect_height), angle = cv2.minAreaRect(points)
        major_axis = max(rect_width, rect_height)
        minor_axis = min(rect_width, rect_height)
        centroid = (int(round(np.mean(points[:, 0]))), int(round(np.mean(points[:, 1]))))

    return {
        "area": area,
        "centroid": centroid,
        "major_axis": float(major_axis),
        "minor_axis": float(minor_axis),
        "angle": angle,
        "points": points,
    }


def polygon_pixel_area(points: np.ndarray) -> float:
    return polygon_region_metrics(points)["area"]


def analyze_image(
    image_path: Path,
    confidence: float,
    iou: float,
    microns_per_pixel: float,
    *,
    is_calibrated: bool = True,
    output_dir: Path | None = None,
    image_id: str | None = None,
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
    rows = []

    if result.masks is not None:
        for idx, mask_xy in enumerate(result.masks.xy, start=1):
            region = polygon_region_metrics(mask_xy)
            pts = region["points"]
            cx, cy = region["centroid"]
            area_px2 = region["area"]
            perimeter_px = cv2.arcLength(mask_xy.astype(np.float32), closed=True)
            length_px = region["major_axis"]
            width_px = region["minor_axis"]

            row = {
                "stoma_id": idx,
                "centroid_x": cx,
                "centroid_y": cy,
                "length_px": round(float(length_px), 2),
                "width_px": round(float(width_px), 2),
                "length_um": round(float(length_px * microns_per_pixel), 3),
                "width_um": round(float(width_px * microns_per_pixel), 3),
                "aspect_ratio": round(float(length_px / width_px), 3) if width_px else 0,
                "area_px2": round(float(area_px2), 2),
                "area_um2": round(float(area_px2 * microns_per_pixel**2), 3),
                "perimeter_px": round(float(perimeter_px), 2),
                "perimeter_um": round(float(perimeter_px * microns_per_pixel), 3),
                "contour": [[int(pt[0]), int(pt[1])] for pt in mask_xy],
            }
            rows.append(row)

            ellipse_axes = (
                max(1, int(round(length_px / 2))),
                max(1, int(round(width_px / 2))),
            )
            cv2.ellipse(image, (cx, cy), ellipse_axes, region["angle"], 0, 360, (0, 255, 0), 2)
            cv2.polylines(image, [pts], isClosed=True, color=(255, 0, 0), thickness=1)
            cv2.circle(image, (cx, cy), 4, (0, 0, 255), -1)
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
        csv_dir = CSV_DIR
        raw_url = f"/outputs/uploads/{image_path.name}"
        annotated_url_prefix = "/outputs/annotated"
        csv_url_prefix = "/outputs/csv"
    else:
        annotated_dir = output_dir / "annotated"
        csv_dir = output_dir / "csv"
        annotated_dir.mkdir(parents=True, exist_ok=True)
        csv_dir.mkdir(parents=True, exist_ok=True)
        batch_id = output_dir.name
        raw_url = f"/outputs/batches/{batch_id}/uploads/{image_path.name}"
        annotated_url_prefix = f"/outputs/batches/{batch_id}/annotated"
        csv_url_prefix = f"/outputs/batches/{batch_id}/csv"

    annotated_path = annotated_dir / f"{image_id}_annotated.jpg"
    csv_path = csv_dir / f"{image_id}_measurements.csv"
    cv2.imwrite(str(annotated_path), image)
    write_csv(csv_path, rows, is_calibrated=is_calibrated)

    count = len(rows)
    summary = {
        "stomata_count": count,
        "avg_area_px2": average(rows, "area_px2"),
        "avg_length_px": average(rows, "length_px"),
        "avg_width_px": average(rows, "width_px"),
        "avg_perimeter_px": average(rows, "perimeter_px"),
        "avg_area_um2": average(rows, "area_um2"),
        "avg_length_um": average(rows, "length_um"),
        "avg_width_um": average(rows, "width_um"),
        "avg_perimeter_um": average(rows, "perimeter_um"),
    }

    return {
        "image_id": image_id,
        "stomata_count": count,
        "confidence": confidence,
        "iou": iou,
        "microns_per_pixel": microns_per_pixel,
        "is_calibrated": is_calibrated,
        "summary": summary,
        "measurements": rows,
        "annotated_image_url": f"{annotated_url_prefix}/{annotated_path.name}",
        "raw_image_url": raw_url,
        "csv_url": f"{csv_url_prefix}/{csv_path.name}",
    }


def average(rows, key):
    if not rows:
        return 0
    return round(float(sum(row[key] for row in rows) / len(rows)), 3)


def write_csv(csv_path: Path, rows, is_calibrated: bool = True):
    fieldnames = [
        "stoma_id",
        "length_px",
        "width_px",
        "area_px2",
        "perimeter_px",
        "aspect_ratio",
    ]
    if is_calibrated:
        fieldnames.extend([
            "length_um",
            "width_um",
            "area_um2",
            "perimeter_um",
        ])
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
