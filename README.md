# STOMORPHIX

STOMORPHIX is a React and FastAPI web application for counting stomata in microscopy images with a YOLO11s segmentation model. It returns an annotated image, per-stoma morphometry, CSV data, and a complete chat-style summary. A single image receives the detailed interactive result; batches of up to 30 images produce downloadable annotated-image and CSV archives.

AI-generated explanations are optional. When no AI API key is configured, the application still performs inference and returns a deterministic summary, annotated image, measurements, and CSV output.

## Repository contents

```text
Stomorphix/
|-- models/
|   |-- yolo11n_stomata/
|   |-- yolo11s_stomata/
|   |-- yolov8n_stomata/
|   `-- yolov8s_stomata/
|-- web-tool/
|   |-- backend/
|   `-- frontend/
|-- .env.example
|-- Dockerfile
`-- README.md
```

Each model directory contains the complete retained training run: configuration, metric curves, confusion matrices, label previews, training and validation previews, result tables and plots, and `weights/best.pt` plus `weights/last.pt`. The web application uses YOLO11s by default.

## Requirements for Windows

Install these tools before starting:

1. [Git for Windows](https://git-scm.com/download/win)
2. [Git LFS](https://git-lfs.com/)
3. [Python 3.10 or 3.11](https://www.python.org/downloads/windows/)
4. [Node.js 20 LTS](https://nodejs.org/)

During Python installation, enable **Add Python to PATH**.

Confirm the installations in PowerShell:

```powershell
git --version
git lfs version
py --version
node --version
npm --version
```

## 1. Download the repository

```powershell
cd $HOME\Downloads
git clone https://github.com/Guruchandar360/Stomorphix.git
cd Stomorphix
git lfs install
git lfs pull
```

Confirm that the default inference weight exists:

```powershell
Get-Item .\models\yolo11s_stomata\weights\best.pt
```

The file should be approximately 20 MB. If it is only a few bytes or contains text beginning with `version https://git-lfs`, run `git lfs pull` again.

## 2. Configure the application

Create the local backend environment file:

```powershell
Copy-Item .env.example .env
```

The app works without an AI key. For AI-written chat explanations, edit `.env` and set either `GEMINI_API_KEY` or `OPENAI_API_KEY`. Do not commit `.env`.

To enable Firebase login in the React development server, create its local environment file:

```powershell
Copy-Item .env.example .\web-tool\frontend\.env.local
```

Then fill in the `VITE_FIREBASE_*` values. Login is optional for local testing while `REQUIRE_AUTH=false`.

## 3. Start the FastAPI backend

Open PowerShell in the repository root:

```powershell
cd .\web-tool\backend
py -3.10 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this window open. Verify the backend at [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health).

## 4. Start the React frontend

Open a second PowerShell window:

```powershell
cd $HOME\Downloads\Stomorphix\web-tool\frontend
npm ci
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

Use the plus button in the chat bar to select one image, several images, or a folder. The maximum batch size is 30 supported microscopy images.

## Morphometry and calibration

For each segmentation mask, STOMORPHIX calculates:

- **Length:** major-axis length in pixels multiplied by the selected calibration in micrometres per pixel.
- **Width:** minor-axis length in pixels multiplied by the selected calibration.
- **Area:** segmented mask area in pixels squared multiplied by the square of the calibration.
- **Aspect ratio:** length divided by width; this is dimensionless.

Optical magnification alone is not a pixel-to-micrometre conversion. Preset magnifications can be reported as pixel-only measurements, or paired with a user-provided calibration obtained from the microscope/camera setup or a stage micrometer. Use custom calibration for research measurements.

## Model artifacts

| Directory | Architecture | Application role |
|---|---|---|
| `models/yolo11n_stomata` | YOLO11n segmentation | Comparison training run |
| `models/yolo11s_stomata` | YOLO11s segmentation | Default production inference model |
| `models/yolov8n_stomata` | YOLOv8n segmentation | Comparison training run |
| `models/yolov8s_stomata` | YOLOv8s segmentation | Comparison training run |

To run the backend with another compatible weight, set an absolute path in `.env`:

```dotenv
STOMORPHIX_MODEL_PATH=C:\path\to\Stomorphix\models\yolo11n_stomata\weights\best.pt
```

## Optional Docker run

Docker packages the React build, FastAPI server, and default YOLO11s weight into one image:

```powershell
docker build -t stomorphix .
docker run --rm -p 7860:7860 --env-file .env stomorphix
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

## Vercel frontend with Hugging Face inference

The React interface can be deployed independently to Vercel while FastAPI and YOLO11s continue running on Hugging Face. Configure the Vercel project with `web-tool/frontend` as its root directory and set these environment variables for Production:

```dotenv
VITE_API_BASE_URL=https://guruchandarkr-stomata-analyzer.hf.space
VITE_FIREBASE_API_KEY=your_firebase_web_api_key
VITE_FIREBASE_AUTH_DOMAIN=your_project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your_project_id
VITE_FIREBASE_STORAGE_BUCKET=your_storage_bucket
VITE_FIREBASE_MESSAGING_SENDER_ID=your_sender_id
VITE_FIREBASE_APP_ID=your_web_app_id
```

Add the production Vercel domain to both the FastAPI `CORS_ORIGINS` setting and Firebase Authentication's authorized domains. Browser uploads must go directly to Hugging Face rather than through a Vercel Function so that microscopy images are not restricted by Vercel's function payload limit.

## Generated files

Runtime uploads, annotations, CSV files, and batch archives are written under `web-tool/backend/outputs`. This directory is excluded from Git. Generated artifacts expire according to the cleanup settings in `.env`.

## Common Windows problems

**PowerShell blocks virtual-environment activation**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Model weight was not downloaded**

```powershell
git lfs install
git lfs pull
```

**Port 8000 or 5173 is already in use**

Close the older backend/frontend process, or start the service on another free port. If the backend port changes, update the frontend development proxy in `web-tool/frontend/vite.config.js`.

**AI explanation is unavailable**

Inference does not depend on an AI key. Check the annotated image, morphometry table, CSV, and deterministic summary; then verify the selected API key separately if AI-written explanations are required.
