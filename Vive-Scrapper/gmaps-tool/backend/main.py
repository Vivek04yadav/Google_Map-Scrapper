"""
FastAPI backend for the Google Maps scraper tool.

Run with:
    uvicorn main:app --reload --port 8000

Endpoints:
    POST   /api/jobs              start a new scrape job
    GET    /api/jobs/{job_id}      poll job status + results so far
    POST   /api/jobs/{job_id}/stop request early stop of a running job
    GET    /api/jobs/{job_id}/csv  download results as CSV
"""

import csv
import io
import threading
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from scraper import scrape_google_maps

app = FastAPI(title="Google Maps Scraper API")

# Local tool — wide-open CORS so the static frontend (opened from file://
# or any localhost port) can talk to it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


class StartJobRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(30, ge=1, le=200)


def _run_job(job_id: str, query: str, limit: int):
    def on_result(row: dict):
        with JOBS_LOCK:
            JOBS[job_id]["results"].append(row)

    def on_status(message: str):
        with JOBS_LOCK:
            JOBS[job_id]["status_log"].append(message)
            JOBS[job_id]["last_status"] = message

    def should_stop():
        with JOBS_LOCK:
            return JOBS[job_id]["stop_requested"]

    try:
        scrape_google_maps(
            query=query,
            limit=limit,
            headless=True,
            on_result=on_result,
            on_status=on_status,
            should_stop=should_stop,
        )
        with JOBS_LOCK:
            JOBS[job_id]["state"] = "done"
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["state"] = "error"
            JOBS[job_id]["error"] = str(e)
            JOBS[job_id]["status_log"].append(f"Error: {e}")


@app.post("/api/jobs")
def start_job(req: StartJobRequest):
    job_id = str(uuid.uuid4())
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "query": req.query,
            "limit": req.limit,
            "state": "running",  # running | done | error
            "results": [],
            "status_log": [],
            "last_status": "Queued…",
            "stop_requested": False,
            "error": None,
            "created_at": datetime.utcnow().isoformat(),
        }

    thread = threading.Thread(target=_run_job, args=(job_id, req.query, req.limit), daemon=True)
    thread.start()

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, since: int = 0):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job["id"],
            "query": job["query"],
            "limit": job["limit"],
            "state": job["state"],
            "last_status": job["last_status"],
            "error": job["error"],
            "result_count": len(job["results"]),
            "results": job["results"][since:],
        }


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        job["stop_requested"] = True
    return {"ok": True}


@app.get("/api/jobs/{job_id}/csv")
def download_csv(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        results = list(job["results"])
        query = job["query"]

    fieldnames = ["name", "category", "rating", "reviews", "address", "phone", "website", "maps_url"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in results:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    buf.seek(0)

    safe_name = "".join(c if c.isalnum() else "_" for c in query)[:40] or "results"
    filename = f"gmaps_{safe_name}.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health():
    return {"ok": True}
