# STOMASPOT

STOMASPOT is a React and FastAPI web application for counting stomata in microscopy images with a YOLO11n segmentation model. It returns an annotated image, an editable detection count, a count report, and a complete chat-style summary. Batches of up to 30 images produce downloadable annotated-image and count-report archives.

AI-generated explanations are optional. When no AI API key is configured, the application still performs inference and returns a deterministic count summary, annotated image, and count report.

## Repository contents

```text
stomaspot/
|-- Data/
|   |-- images/
|   |   |-- train/        # 452 training images
|   |   `-- val/          # 48 validation images
|   `-- labels/
|       |-- train/        # 452 YOLO segmentation labels
|       `-- val/          # 48 YOLO segmentation labels
|-- models/
|   |-- yolo11n_stomata/
|   |-- yolov8n_stomata/
|   `-- yolov8s_stomata/
|-- web-tool/
|   |-- backend/
|   `-- frontend/
|-- .env.example
|-- Dockerfile
`-- README.md
```

Each model directory contains the complete retained training run: configuration, metric curves, confusion matrices, label previews, training and validation previews, result tables and plots, and `weights/best.pt` plus `weights/last.pt`. The web application uses YOLO11n by default.

The `Data` directory contains the model training and validation dataset. Every image in `Data/images/train` or `Data/images/val` has a same-stem YOLO segmentation annotation in the corresponding `Data/labels` directory. The repository contains 500 images and 500 label files in total. Dataset images are stored with Git LFS, while generated Ultralytics `.cache` files are excluded because they can be rebuilt locally.

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
git clone https://github.com/Guruchandar360/stomaspot.git
cd stomaspot
git lfs install
git lfs pull
```

Confirm that the default inference weight exists:

```powershell
Get-Item .\models\yolo11n_stomata\weights\best.pt
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
cd $HOME\Downloads\stomaspot\web-tool\frontend
npm ci
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

Use the plus button in the chat bar to select one image, several images, or a folder. The maximum batch size is 30 supported microscopy images. For a single image, use **Edit Detections** to delete an incorrect outline or draw a missing stoma; the displayed count and downloaded count report update with those corrections.

## Counting output

STOMASPOT reports only stomata counts. It does not calculate or present length, width, area, aspect ratio, perimeter, or physical calibration results.

Each YOLO11n segmentation mask represents one detected stoma. The count equals the number of retained masks at the selected confidence and IoU thresholds. The green outlines allow users to inspect what the model counted before using the result. The magnification selector records whether the uploaded image was acquired at `4x`, `5x`, `10x`, `20x`, `40x`, or `100x`; it does not scale or otherwise change the count.

## Model artifacts

| Directory | Architecture | Application role |
|---|---|---|
| `models/yolo11n_stomata` | YOLO11n segmentation | Default production inference model |
| `models/yolov8n_stomata` | YOLOv8n segmentation | Comparison training run |
| `models/yolov8s_stomata` | YOLOv8s segmentation | Comparison training run |

To run the backend with another compatible weight, set an absolute path in `.env`:

```dotenv
STOMASPOT_MODEL_PATH=C:\path\to\stomaspot\models\yolo11n_stomata\weights\best.pt
```

## Optional Docker run

Docker packages the React build, FastAPI server, and default YOLO11n weight into one image:

```powershell
docker build -t stomaspot .
docker run --rm -p 7860:7860 --env-file .env stomaspot
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

## Vercel frontend with Hugging Face inference

The React interface can be deployed independently to Vercel while FastAPI and YOLO11n continue running on Hugging Face. Configure the Vercel project with `web-tool/frontend` as its root directory and set these environment variables for Production:

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

Runtime uploads, annotations, count reports, and batch archives are written under `web-tool/backend/outputs`. This directory is excluded from Git. Generated artifacts expire according to the cleanup settings in `.env`.

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

Inference does not depend on an AI key. Check the annotated image, count report, and deterministic summary; then verify the selected API key separately if AI-written explanations are required.
