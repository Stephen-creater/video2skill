import json
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import JobContext, Pipeline, PipelineUnavailable

TARGET_BVID = "BV1ZW42197oE"
STAGES = ("download", "transcribe", "frames", "compile", "validate")
SKILL_PATH = Path(__file__).parents[2] / "skills" / f"{TARGET_BVID}.json"
WORK_ROOT = Path(__file__).parents[2] / "work"
LIVECODES_ROOT = Path(__file__).parents[2] / "vendor" / "livecodes"

app = FastAPI(title="Video2Skill")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*",
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)
app.mount("/livecodes", StaticFiles(directory=LIVECODES_ROOT, html=True, check_dir=False), name="livecodes")
pipeline = Pipeline()
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


class CompileRequest(BaseModel):
    bvid: str


def fixed_skill() -> dict:
    return json.loads(SKILL_PATH.read_text(encoding="utf-8"))


def new_job() -> tuple[str, dict]:
    job_id = uuid4().hex
    job = {
        "jobId": job_id,
        "status": "queued",
        "stages": {stage: {"state": "pending"} for stage in STAGES},
    }
    with jobs_lock:
        jobs[job_id] = job
    return job_id, job


def update_stage(job_id: str, stage: str, state: str, error: str | None = None) -> None:
    with jobs_lock:
        job = jobs[job_id]
        job["status"] = "running" if state == "running" else job["status"]
        job["stages"][stage] = {"state": state, **({"error": error} if error else {})}


def run_job(job_id: str) -> None:
    active_stage = "download"

    def observe(stage: str, state: str) -> None:
        nonlocal active_stage
        active_stage = stage
        update_stage(job_id, stage, state)

    try:
        pipeline.run(TARGET_BVID, JobContext(TARGET_BVID, job_id, WORK_ROOT / job_id), observe)
    except PipelineUnavailable as error:
        update_stage(job_id, error.stage, "failed", str(error))
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
    except Exception as error:
        update_stage(job_id, active_stage, "failed", str(error))
        with jobs_lock:
            jobs[job_id]["status"] = "failed"
    else:
        with jobs_lock:
            jobs[job_id]["status"] = "completed"


def start_job(job_id: str) -> None:
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


@app.get("/v1/skills/{bvid}")
def get_skill(bvid: str) -> dict:
    if bvid != TARGET_BVID:
        raise HTTPException(status_code=404, detail="skill is not cached")
    return fixed_skill()


@app.post("/v1/compile", status_code=202)
def compile_skill(request: CompileRequest) -> dict[str, str]:
    if request.bvid != TARGET_BVID:
        raise HTTPException(status_code=422, detail="only the target BVID is supported")
    job_id, _ = new_job()
    start_job(job_id)
    return {"jobId": job_id}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"jobId": job["jobId"], "status": job["status"], "stages": job["stages"].copy()}
