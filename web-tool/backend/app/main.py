import asyncio
import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import cv2
import numpy as np
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

from .analyzer import (
    OUTPUT_DIR,
    InferenceBusyError,
    analyze_image,
    polygon_region_metrics,
    save_upload,
)
from .batch_jobs import MAX_BATCH_IMAGES, BatchError, batch_manager
from .explainer import build_explanation
from .maintenance import MaintenanceWorker
from .security import AUTH_REQUIRED, get_principal, rate_limiter

class ContourPoint(BaseModel):
    x: int
    y: int

class MorphometryRequest(BaseModel):
    points: List[ContourPoint]
    microns_per_pixel: float


class BatchCreateRequest(BaseModel):
    expected_files: int
    confidence: float = 0.5
    iou: float = 0.7
    microns_per_pixel: float = 1.0
    is_calibrated: bool = False
    magnification: int = 400
    prompt: str | None = None

app = FastAPI(title="Stomata Morphometry API")
maintenance_worker = MaintenanceWorker(batch_manager.cleanup_expired)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


@app.on_event("startup")
def start_batch_worker():
    batch_manager.start()
    maintenance_worker.start()


@app.on_event("shutdown")
def stop_batch_worker():
    maintenance_worker.stop()
    batch_manager.stop()


@app.get("/api/health")
def health(request: Request, response: Response):
    cache_reset_version = "2026-08-28-stomorphix-v3"
    if request.cookies.get("stomata_cache_reset") != cache_reset_version:
        response.headers["Clear-Site-Data"] = '"cache"'
        response.set_cookie(
            "stomata_cache_reset",
            cache_reset_version,
            max_age=60 * 60 * 24 * 30,
            secure=True,
            httponly=True,
            samesite="none",
        )
    return {"status": "ok", "authentication_required": AUTH_REQUIRED}


@app.post("/api/analyze")
async def analyze(
    image: UploadFile = File(...),
    confidence: float = Form(0.5),
    iou: float = Form(0.7),
    microns_per_pixel: float = Form(1.0),
    is_calibrated: bool = Form(False),
    magnification: int = Form(400),
    prompt: str = Form(None),
    principal=Depends(get_principal),
):
    validate_analysis_settings(confidence, iou, microns_per_pixel)
    validate_magnification(magnification)
    rate_limiter.consume(principal["rate_key"])

    try:
        image_path = await asyncio.to_thread(save_upload, image)
        result = await asyncio.to_thread(
            analyze_image,
            image_path,
            confidence,
            iou,
            microns_per_pixel,
            is_calibrated=is_calibrated,
        )
        result["magnification"] = magnification
        result["explanation"] = await build_explanation(result, prompt=prompt)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InferenceBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="The image could not be analyzed.") from exc


def validate_analysis_settings(confidence, iou, microns_per_pixel):
    if confidence < 0.05 or confidence > 0.95:
        raise HTTPException(status_code=400, detail="Confidence must be between 0.05 and 0.95.")
    if iou < 0.1 or iou > 0.95:
        raise HTTPException(status_code=400, detail="IoU threshold must be between 0.1 and 0.95.")
    if microns_per_pixel <= 0 or microns_per_pixel > 10:
        raise HTTPException(status_code=400, detail="Microns per pixel must be between 0 and 10.")


def validate_magnification(magnification):
    if magnification not in {40, 100, 200, 400, 1000}:
        raise HTTPException(status_code=400, detail="Unsupported microscope magnification.")


def handle_batch_error(exc):
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, BatchError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@app.post("/api/batches")
async def create_batch(request: BatchCreateRequest, principal=Depends(get_principal)):
    validate_analysis_settings(request.confidence, request.iou, request.microns_per_pixel)
    validate_magnification(request.magnification)
    if request.expected_files < 2 or request.expected_files > MAX_BATCH_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"A batch must contain between 2 and {MAX_BATCH_IMAGES} images.",
        )
    rate_limiter.consume(principal["rate_key"], request.expected_files)
    try:
        job, token = await asyncio.to_thread(
            batch_manager.create,
            request.expected_files,
            request.confidence,
            request.iou,
            request.microns_per_pixel,
            request.is_calibrated,
            request.prompt,
            request.magnification,
        )
        return {"job": job, "access_token": token}
    except Exception as exc:
        handle_batch_error(exc)


@app.post("/api/batches/{job_id}/uploads")
async def upload_batch_images(
    job_id: str,
    images: List[UploadFile] = File(...),
    relative_paths: str = Form("[]"),
    token: str = Header(default="", alias="X-Batch-Token"),
):
    try:
        paths = json.loads(relative_paths)
        if not isinstance(paths, list):
            raise BatchError("Relative paths must be a list.")
        return await asyncio.to_thread(batch_manager.add_uploads, job_id, token, images, paths)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid relative path data.") from exc
    except Exception as exc:
        handle_batch_error(exc)


@app.post("/api/batches/{job_id}/start")
async def start_batch(job_id: str, token: str = Header(default="", alias="X-Batch-Token")):
    try:
        return await asyncio.to_thread(batch_manager.enqueue, job_id, token)
    except Exception as exc:
        handle_batch_error(exc)


@app.get("/api/batches/{job_id}")
async def get_batch(job_id: str, token: str = Header(default="", alias="X-Batch-Token")):
    try:
        return await asyncio.to_thread(batch_manager.get, job_id, token)
    except Exception as exc:
        handle_batch_error(exc)


@app.get("/api/batches/{job_id}/results/{result_index}")
async def get_batch_result(
    job_id: str,
    result_index: int,
    token: str = Header(default="", alias="X-Batch-Token"),
):
    try:
        return await asyncio.to_thread(batch_manager.get_result, job_id, token, result_index)
    except Exception as exc:
        handle_batch_error(exc)


@app.get("/api/batches/{job_id}/downloads/{kind}")
async def download_batch(
    job_id: str,
    kind: str,
    token: str = Query(default=""),
):
    try:
        path = await asyncio.to_thread(batch_manager.download_path, job_id, token, kind)
        return FileResponse(path, filename=path.name, media_type="application/zip")
    except Exception as exc:
        handle_batch_error(exc)


@app.post("/api/calculate_morphometry")
async def calculate_morphometry(req: MorphometryRequest, principal=Depends(get_principal)):
    pts = np.array([[p.x, p.y] for p in req.points], dtype=np.int32)
    if len(pts) < 3:
        raise HTTPException(status_code=400, detail="At least 3 points are required to form a polygon.")
    if req.microns_per_pixel <= 0 or req.microns_per_pixel > 10:
        raise HTTPException(status_code=400, detail="Microns per pixel must be between 0 and 10.")
    rate_limiter.consume(principal["rate_key"])
    
    region = polygon_region_metrics(pts)
    cx, cy = region["centroid"]
    area_px2 = region["area"]
    perimeter_px = cv2.arcLength(pts.astype(np.float32), closed=True)
    length_px = region["major_axis"]
    width_px = region["minor_axis"]

    microns = req.microns_per_pixel
    return {
        "centroid_x": cx,
        "centroid_y": cy,
        "length_px": round(float(length_px), 2),
        "width_px": round(float(width_px), 2),
        "length_um": round(float(length_px * microns), 3),
        "width_um": round(float(width_px * microns), 3),
        "aspect_ratio": round(float(length_px / width_px), 3) if width_px else 0,
        "area_px2": round(float(area_px2), 2),
        "area_um2": round(float(area_px2 * microns**2), 3),
        "perimeter_px": round(float(perimeter_px), 2),
        "perimeter_um": round(float(perimeter_px * microns), 3),
        "contour": [[int(p.x), int(p.y)] for p in req.points]
    }


# Serve React frontend built static files if the static directory exists
import os
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parents[1]
static_dir = BACKEND_DIR / "static"
if static_dir.exists() and static_dir.is_dir():
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    # Generate dynamic Firebase credentials file for frontend at runtime
    import json
    env_vars = {
        "VITE_FIREBASE_API_KEY": os.getenv("VITE_FIREBASE_API_KEY", ""),
        "VITE_FIREBASE_AUTH_DOMAIN": os.getenv("VITE_FIREBASE_AUTH_DOMAIN", ""),
        "VITE_FIREBASE_PROJECT_ID": os.getenv("VITE_FIREBASE_PROJECT_ID", ""),
        "VITE_FIREBASE_STORAGE_BUCKET": os.getenv("VITE_FIREBASE_STORAGE_BUCKET", ""),
        "VITE_FIREBASE_MESSAGING_SENDER_ID": os.getenv("VITE_FIREBASE_MESSAGING_SENDER_ID", ""),
        "VITE_FIREBASE_APP_ID": os.getenv("VITE_FIREBASE_APP_ID", "")
    }
    js_content = f"window.env = {json.dumps(env_vars)};\n"
    try:
        with open(static_dir / "env-config.js", "w") as env_file:
            env_file.write(js_content)
        print("[Info] Successfully generated dynamic env-config.js from runtime environment secrets.")
    except Exception as env_err:
        print(f"[Error] Failed to generate dynamic env-config.js: {env_err}")

    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")
    
    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        if catchall.startswith("api") or catchall.startswith("outputs"):
            raise HTTPException(status_code=404, detail="Not Found")
        
        file_path = static_dir / catchall
        if file_path.is_file():
            headers = no_cache_headers if file_path.name in {"index.html", "env-config.js"} else None
            return FileResponse(str(file_path), headers=headers)
            
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path), headers=no_cache_headers)
        return {"message": "Static assets not found"}
