import asyncio
import csv
import hashlib
import json
import os
import queue
import secrets
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .analyzer import ALLOWED_IMAGE_SUFFIXES, OUTPUT_DIR, analyze_image, save_upload
from .explainer import build_explanation


MAX_BATCH_IMAGES = int(os.getenv("MAX_BATCH_IMAGES", "30"))
BATCH_TTL_SECONDS = int(os.getenv("BATCH_TTL_SECONDS", str(24 * 60 * 60)))
MAX_PENDING_BATCHES = int(os.getenv("MAX_PENDING_BATCHES", "50"))
BATCH_ROOT = OUTPUT_DIR / "batches"
BATCH_ROOT.mkdir(parents=True, exist_ok=True)

TERMINAL_STATUSES = {"completed", "partial", "failed"}


class BatchError(ValueError):
    pass


class BatchManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.RLock()
        self.pending = queue.Queue(maxsize=MAX_PENDING_BATCHES)
        self.stop_event = threading.Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.cleanup_expired()
        self.worker = threading.Thread(target=self._worker_loop, name="stomata-batch-worker", daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=3)

    def create(
        self,
        expected_files,
        confidence,
        iou,
        microns_per_pixel,
        is_calibrated=False,
        prompt=None,
        magnification=400,
    ):
        if expected_files < 2 or expected_files > MAX_BATCH_IMAGES:
            raise BatchError(f"A batch must contain between 2 and {MAX_BATCH_IMAGES} images.")

        job_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        now = time.time()
        job = {
            "id": job_id,
            "token_hash": self._token_hash(token),
            "status": "receiving",
            "expected_files": expected_files,
            "uploaded": [],
            "processed": 0,
            "failed": 0,
            "results": [],
            "errors": [],
            "confidence": confidence,
            "iou": iou,
            "microns_per_pixel": microns_per_pixel,
            "is_calibrated": is_calibrated,
            "magnification": magnification,
            "prompt": prompt or "",
            "summary": None,
            "explanation": "",
            "created_at": now,
            "updated_at": now,
        }
        job_dir = self._job_dir(job_id)
        (job_dir / "uploads").mkdir(parents=True, exist_ok=False)
        (job_dir / "annotated").mkdir()
        (job_dir / "csv").mkdir()
        with self.lock:
            self.jobs[job_id] = job
            self._persist(job)
        return self._public(job), token

    def add_uploads(self, job_id, token, upload_files, relative_paths):
        job = self._authorized_job(job_id, token)
        with self.lock:
            if job["status"] != "receiving":
                raise BatchError("This batch is no longer accepting uploads.")
            if len(upload_files) != len(relative_paths):
                raise BatchError("Each uploaded image must have a matching relative path.")
            if len(job["uploaded"]) + len(upload_files) > job["expected_files"]:
                raise BatchError("The upload contains more images than declared for this batch.")

        saved = []
        upload_dir = self._job_dir(job_id) / "uploads"
        start_index = len(job["uploaded"])
        try:
            for offset, (upload, relative_path) in enumerate(zip(upload_files, relative_paths)):
                display_name = self._safe_relative_name(relative_path or upload.filename or "image.jpg")
                suffix = Path(display_name).suffix.lower()
                if suffix not in ALLOWED_IMAGE_SUFFIXES:
                    raise BatchError(f"Unsupported image format: {display_name}.")
                output_name = f"{start_index + offset + 1:03d}_{Path(display_name).name}"
                image_path = save_upload(upload, upload_dir, filename=output_name)
                saved.append({
                    "path": str(image_path),
                    "relative_name": display_name,
                    "output_id": f"{start_index + offset + 1:03d}_{Path(display_name).stem}",
                })
        except Exception:
            for item in saved:
                Path(item["path"]).unlink(missing_ok=True)
            raise

        with self.lock:
            job["uploaded"].extend(saved)
            job["updated_at"] = time.time()
            self._persist(job)
            return self._public(job)

    def enqueue(self, job_id, token):
        job = self._authorized_job(job_id, token)
        with self.lock:
            if job["status"] != "receiving":
                raise BatchError("This batch has already been started.")
            if len(job["uploaded"]) != job["expected_files"]:
                raise BatchError(
                    f"Expected {job['expected_files']} images but received {len(job['uploaded'])}."
                )
            job["status"] = "queued"
            job["updated_at"] = time.time()
            self._persist(job)
        try:
            self.pending.put_nowait(job_id)
        except queue.Full as exc:
            with self.lock:
                job["status"] = "receiving"
                self._persist(job)
            raise BatchError("The analysis queue is full. Please try again shortly.") from exc
        return self._public(job)

    def get(self, job_id, token):
        return self._public(self._authorized_job(job_id, token))

    def get_result(self, job_id, token, result_index):
        job = self._authorized_job(job_id, token)
        with self.lock:
            if result_index < 0 or result_index >= len(job["results"]):
                raise BatchError("Batch result not found.")
            return dict(job["results"][result_index])

    def download_path(self, job_id, token, kind):
        self._authorized_job(job_id, token)
        filenames = {
            "annotated": "annotated_images.zip",
            "csv": "morphometry_csvs.zip",
            "complete": "complete_batch.zip",
        }
        if kind not in filenames:
            raise BatchError("Unknown download type.")
        path = self._job_dir(job_id) / filenames[kind]
        if not path.is_file():
            raise BatchError("The requested archive is not ready yet.")
        return path

    def cleanup_expired(self):
        cutoff = time.time() - BATCH_TTL_SECONDS
        root = BATCH_ROOT.resolve()
        for path in BATCH_ROOT.iterdir():
            if not path.is_dir():
                continue
            try:
                resolved = path.resolve()
                if root not in resolved.parents or path.stat().st_mtime >= cutoff:
                    continue
                shutil.rmtree(resolved)
            except OSError:
                continue
        with self.lock:
            expired = [job_id for job_id, job in self.jobs.items() if job["updated_at"] < cutoff]
            for job_id in expired:
                self.jobs.pop(job_id, None)

    def _worker_loop(self):
        while not self.stop_event.is_set():
            try:
                job_id = self.pending.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process(job_id)
            finally:
                self.pending.task_done()
                self.cleanup_expired()

    def _process(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["status"] = "processing"
            job["updated_at"] = time.time()
            self._persist(job)

        job_dir = self._job_dir(job_id)
        for item in list(job["uploaded"]):
            if self.stop_event.is_set():
                return
            try:
                result = analyze_image(
                    Path(item["path"]),
                    job["confidence"],
                    job["iou"],
                    job["microns_per_pixel"],
                    is_calibrated=job["is_calibrated"],
                    output_dir=job_dir,
                    image_id=item["output_id"],
                )
                result["magnification"] = job["magnification"]
                result["original_name"] = item["relative_name"]
                with self.lock:
                    job["results"].append(result)
            except Exception as exc:
                with self.lock:
                    job["failed"] += 1
                    job["errors"].append({"filename": item["relative_name"], "error": str(exc)})
            finally:
                with self.lock:
                    job["processed"] += 1
                    job["updated_at"] = time.time()
                    self._persist(job)

        with self.lock:
            job["summary"] = self._build_summary(job["results"], job["failed"])
            final_status = (
                "failed" if not job["results"] else "partial" if job["failed"] else "completed"
            )
            job["status"] = "finalizing"
            job["updated_at"] = time.time()
            self._write_summary_csv(job)
            self._write_archives(job)

        if job["results"]:
            explanation_input = {
                "stomata_count": job["summary"]["total_stomata"],
                "confidence": job["confidence"],
                "iou": job["iou"],
                "microns_per_pixel": job["microns_per_pixel"],
                "is_calibrated": job["is_calibrated"],
                "magnification": job["magnification"],
                "summary": {
                    "avg_area_px2": job["summary"]["avg_area_px2"],
                    "avg_length_px": job["summary"]["avg_length_px"],
                    "avg_width_px": job["summary"]["avg_width_px"],
                    "avg_perimeter_px": job["summary"]["avg_perimeter_px"],
                    "avg_area_um2": job["summary"]["avg_area_um2"],
                    "avg_length_um": job["summary"]["avg_length_um"],
                    "avg_width_um": job["summary"]["avg_width_um"],
                    "avg_perimeter_um": job["summary"]["avg_perimeter_um"],
                },
            }
            try:
                detail = asyncio.run(build_explanation(explanation_input, prompt=job["prompt"]))
                fallback = self._fallback_explanation(job)
                job["explanation"] = (
                    f"{fallback} {detail}" if len(detail.split()) >= 8 else fallback
                )
            except Exception:
                job["explanation"] = self._fallback_explanation(job)
        else:
            job["explanation"] = "No images in this batch could be analyzed."

        with self.lock:
            job["status"] = final_status
            job["updated_at"] = time.time()
            self._persist(job)

    def _build_summary(self, results, failed):
        measurements = [row for result in results for row in result.get("measurements", [])]

        def average(key):
            if not measurements:
                return 0
            return round(sum(float(row.get(key, 0)) for row in measurements) / len(measurements), 3)

        total = sum(result["stomata_count"] for result in results)
        return {
            "completed_images": len(results),
            "failed_images": failed,
            "total_stomata": total,
            "avg_stomata_per_image": round(total / len(results), 2) if results else 0,
            "avg_area_px2": average("area_px2"),
            "avg_length_px": average("length_px"),
            "avg_width_px": average("width_px"),
            "avg_perimeter_px": average("perimeter_px"),
            "avg_area_um2": average("area_um2"),
            "avg_length_um": average("length_um"),
            "avg_width_um": average("width_um"),
            "avg_perimeter_um": average("perimeter_um"),
        }

    def _write_summary_csv(self, job):
        path = self._job_dir(job["id"]) / "summary.csv"
        fields = ["filename", "stomata_count", "avg_area_px2", "avg_length_px", "avg_width_px", "avg_perimeter_px"]
        if job["is_calibrated"]:
            fields.extend(["avg_area_um2", "avg_length_um", "avg_width_um", "avg_perimeter_um"])
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for result in job["results"]:
                writer.writerow({"filename": result["original_name"], **result["summary"]})

    def _write_archives(self, job):
        job_dir = self._job_dir(job["id"])
        annotated_zip = job_dir / "annotated_images.zip"
        csv_zip = job_dir / "morphometry_csvs.zip"
        complete_zip = job_dir / "complete_batch.zip"

        with zipfile.ZipFile(annotated_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for result in job["results"]:
                path = self._url_to_path(result["annotated_image_url"])
                archive.write(path, arcname=path.name)
        with zipfile.ZipFile(csv_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for result in job["results"]:
                path = self._url_to_path(result["csv_url"])
                archive.write(path, arcname=path.name)
            archive.write(job_dir / "summary.csv", arcname="summary.csv")
        with zipfile.ZipFile(complete_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for result in job["results"]:
                annotated = self._url_to_path(result["annotated_image_url"])
                report = self._url_to_path(result["csv_url"])
                archive.write(annotated, arcname=f"annotated_images/{annotated.name}")
                archive.write(report, arcname=f"csv_files/{report.name}")
            archive.write(job_dir / "summary.csv", arcname="summary.csv")

    def _public(self, job):
        with self.lock:
            results = [
                {
                    "index": index,
                    "original_name": result["original_name"],
                    "stomata_count": result["stomata_count"],
                    "summary": result["summary"],
                    "annotated_image_url": result["annotated_image_url"],
                    "raw_image_url": result["raw_image_url"],
                    "csv_url": result["csv_url"],
                }
                for index, result in enumerate(job["results"])
            ]
            return {
                "id": job["id"],
                "status": job["status"],
                "expected_files": job["expected_files"],
                "uploaded_files": len(job["uploaded"]),
                "processed_files": job["processed"],
                "failed_files": job["failed"],
                "current_file": (
                    job["uploaded"][job["processed"]]["relative_name"]
                    if job["status"] == "processing" and job["processed"] < len(job["uploaded"])
                    else None
                ),
                "results": results,
                "errors": list(job["errors"]),
                "summary": job["summary"],
                "explanation": job["explanation"],
                "confidence": job["confidence"],
                "iou": job["iou"],
                "microns_per_pixel": job["microns_per_pixel"],
                "is_calibrated": job["is_calibrated"],
                "magnification": job.get("magnification", 400),
                "created_at": job["created_at"],
                "updated_at": job["updated_at"],
            }

    def _authorized_job(self, job_id, token):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise BatchError("Batch job not found or expired.")
            if not token or not secrets.compare_digest(job["token_hash"], self._token_hash(token)):
                raise PermissionError("Invalid batch access token.")
            return job

    def _persist(self, job):
        public = self._public(job)
        path = self._job_dir(job["id"]) / "manifest.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(public, indent=2), encoding="utf-8")
        temp.replace(path)

    def _job_dir(self, job_id):
        if not job_id or any(char not in "0123456789abcdef" for char in job_id):
            raise BatchError("Invalid batch identifier.")
        path = (BATCH_ROOT / job_id).resolve()
        if BATCH_ROOT.resolve() not in path.parents:
            raise BatchError("Invalid batch identifier.")
        return path

    @staticmethod
    def _safe_relative_name(value):
        path = PurePosixPath(str(value).replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise BatchError("Invalid relative file path.")
        clean_parts = [part for part in path.parts if part not in {"", "."}]
        if not clean_parts:
            raise BatchError("Image filename is missing.")
        return "/".join(clean_parts)[-240:]

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _url_to_path(url):
        relative = url.removeprefix("/outputs/")
        return OUTPUT_DIR / Path(relative)

    @staticmethod
    def _fallback_explanation(job):
        summary = job["summary"]
        calibration = (
            f"using a calibration of {job['microns_per_pixel']} µm/pixel"
            if job["is_calibrated"]
            else "in pixel units because no pixel calibration was supplied"
        )
        return (
            f"I analyzed {summary['completed_images']} images and detected "
            f"{summary['total_stomata']} stomata in total, with an average of "
            f"{summary['avg_stomata_per_image']} stomata per image {calibration}."
        )


batch_manager = BatchManager()
