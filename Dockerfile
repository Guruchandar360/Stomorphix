# Stage 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY web-tool/frontend/package*.json ./
RUN npm ci
COPY web-tool/frontend/ ./
RUN npm run build

# Stage 2: Run Python FastAPI Backend
FROM python:3.10-slim
WORKDIR /app

# Ensure Python output is sent straight to terminal (no buffering)
ENV PYTHONUNBUFFERED=1

# Install system dependencies required for OpenCV headless and YOLO
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libxcb1 \
    libsm6 \
    libxext6 \
    libgl1 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install them
COPY web-tool/backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the model weights needed for inference
COPY models/yolo11s_stomata/weights/best.pt ./models/yolo11s_stomata/weights/best.pt

# Copy backend app and config files
COPY web-tool/backend/app ./web-tool/backend/app

# Copy built frontend assets into the FastAPI static directory
COPY --from=frontend-builder /frontend/dist ./web-tool/backend/static

# Ensure output directory for generated files exists
RUN mkdir -p /app/web-tool/backend/outputs

# Change ownership of /app to user 1000 (Hugging Face default user)
RUN chown -R 1000:1000 /app

# Run inference and file generation without root privileges.
USER 1000:1000

# Set working directory to the backend directory
WORKDIR /app/web-tool/backend

# Expose Hugging Face Space port
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=3)"

# Run FastAPI using uvicorn on port 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
