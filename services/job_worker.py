# Fake async worker behind one seam: enqueue_job(job_id).
# Swap this module for Celery (broker + workers/tasks.py) later — API code stays same.
# Stub simulates stages with sleeps so queued/running are observable; writes a
# placeholder result file and completes. Checks cancelled between stages.
import time
from datetime import datetime, timezone

from core.db import SessionLocal
from core.storage import delete_key, job_result_path, save_bytes
from models.job import Job

RESULT_EXT = {"tts": ".mp3", "generate": ".mp4", "speak": ".mp3"}
# per-stage sleeps (total ~2s) — long enough to observe queued/running in tests
STAGES = (0.7, 0.7, 0.6)


def enqueue_job(job_id: str) -> None:
    # called via FastAPI BackgroundTasks; Celery: replace body with task.delay(job_id)
    _run(job_id)


def _run(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status != "queued":
            return  # cancelled while queued (or never existed)
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        for pause in STAGES:
            time.sleep(pause)
            db.refresh(job)
            if job.status == "cancelled":
                return  # endpoint already stamped finished_at

        ext = RESULT_EXT.get(job.type, ".mp3")
        dest, rel = job_result_path(job_id, ext)
        try:
            save_bytes(dest, b"stub-result:" + job.type.encode())
        except OSError as exc:
            db.refresh(job)
            job.status = "failed"
            job.error = f"result store failed: {exc}"
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        db.refresh(job)
        if job.status == "cancelled":
            delete_key(rel)
            return
        job.result_key = rel
        job.status = "completed"
        job.finished_at = datetime.now(timezone.utc)
        if job.started_at:
            job.duration_sec = (job.finished_at - job.started_at).total_seconds()
        db.commit()
    except Exception as exc:  # never leave a job stuck in running on code bugs
        try:
            db.rollback()
            job = db.get(Job, job_id)
            if job and job.status == "running":
                job.status = "failed"
                job.error = str(exc)[:2000]
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def reap_stale_running() -> int:
    # startup: a restart strands in-flight BackgroundTasks; fail them honestly
    db = SessionLocal()
    try:
        stale = db.query(Job).filter(Job.status == "running").all()
        for job in stale:
            job.status = "failed"
            job.error = "server restarted mid-run"
            job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return len(stale)
    finally:
        db.close()
