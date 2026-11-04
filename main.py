import os
import sys
import uuid
import shutil
import threading
import subprocess
import time

from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Remove Vocals AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path("/tmp/remove-vocals")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")

jobs = {}

ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".ogg"
}

MAX_FILE_SIZE = 20 * 1024 * 1024


@app.get("/")
def home():
    return {"message": "Remove Vocals AI Server is running!"}


@app.get("/health")
def health():
    return {"status": "online"}


def process_audio(job_id, input_path):
    job_dir = OUTPUT_DIR / job_id
    demucs_dir = job_dir / "demucs"
    final_dir = job_dir / "result"

    job_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    jobs[job_id]["status"] = "processing"
    jobs[job_id]["progress"] = 15
    jobs[job_id]["message"] = "AI is separating audio..."

    try:
        command = [
            sys.executable,
            "-m", "demucs",
            "--two-stems=vocals",
            "-n", "htdemucs",
            "-o", str(demucs_dir),
            str(input_path)
        ]

        start_time = time.time()

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        while process.poll() is None:
            elapsed = time.time() - start_time
            progress = min(85, 20 + int(elapsed / 15))
            jobs[job_id]["progress"] = progress
            time.sleep(3)

        if process.returncode != 0:
            raise RuntimeError("Demucs processing failed.")

        result_folder = demucs_dir / "htdemucs" / input_path.stem

        vocals = result_folder / "vocals.wav"
        instrumental = result_folder / "no_vocals.wav"

        if not vocals.exists() or not instrumental.exists():
            raise RuntimeError("Output audio files were not found.")

        shutil.copy2(vocals, final_dir / "vocals.wav")
        shutil.copy2(instrumental, final_dir / "instrumental.wav")

        jobs[job_id].update({
            "status": "completed",
            "progress": 100,
            "message": "Audio separation completed!",
            "vocals_url": f"/files/{job_id}/result/vocals.wav",
            "instrumental_url": f"/files/{job_id}/result/instrumental.wav"
        })

    except Exception as error:
        jobs[job_id].update({
            "status": "failed",
            "progress": 0,
            "message": str(error)
        })

    finally:
        if input_path.exists():
            input_path.unlink(missing_ok=True)

        if demucs_dir.exists():
            shutil.rmtree(demucs_dir, ignore_errors=True)


@app.post("/api/separate")
async def separate_audio(file: UploadFile = File(...)):
    extension = Path(file.filename or "").suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported audio format."
        )

    job_id = str(uuid.uuid4())
    input_path = UPLOAD_DIR / f"{job_id}{extension}"

    size = 0

    try:
        with input_path.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                size += len(chunk)

                if size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="File must be smaller than 20 MB."
                    )

                output.write(chunk)

    except Exception:
        input_path.unlink(missing_ok=True)
        raise

    finally:
        await file.close()

    jobs[job_id] = {
        "status": "queued",
        "progress": 5,
        "message": "Audio uploaded. Waiting for AI..."
    }

    thread = threading.Thread(
        target=process_audio,
        args=(job_id, input_path),
        daemon=True
    )
    thread.start()

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    return jobs[job_id]
