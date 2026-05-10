"""RQ job entry points + Redis queue helpers."""
from __future__ import annotations

import logging
from datetime import timedelta

from flask import current_app
from redis import Redis
from rq import Queue


logger = logging.getLogger(__name__)
QUEUE_NAME = "flat-finder"


def _get_queue() -> Queue:
    redis = Redis.from_url(current_app.config["REDIS_URL"])
    return Queue(QUEUE_NAME, connection=redis)


def enqueue_import(job_id: int) -> None:
    """Enqueue an import job for processing by a worker."""
    q = _get_queue()
    q.enqueue(
        "app.services.importer.jobs.import_job_task",
        job_id,
        job_timeout=600,
        result_ttl=3600,
        failure_ttl=86400,
    )


def enqueue_refresh(source_id: int) -> None:
    q = _get_queue()
    q.enqueue(
        "app.services.importer.jobs.refresh_source_task",
        source_id,
        job_timeout=600,
        result_ttl=3600,
        failure_ttl=86400,
    )


def import_job_task(job_id: int) -> None:
    """Worker entry point: runs inside an RQ worker process.

    The worker uses a Flask app context provided by `worker.py`.
    """
    from app.services.importer.pipeline import run_import_job

    run_import_job(job_id)


def refresh_source_task(source_id: int) -> None:
    from app.services.importer.pipeline import run_refresh_for_source

    run_refresh_for_source(source_id)


def schedule_job_cleanup(import_job_id: int, delay_seconds: int = 300) -> None:
    """Schedule deletion of a done ImportJob after a grace period."""
    try:
        q = _get_queue()
        q.enqueue_in(
            timedelta(seconds=delay_seconds),
            "app.services.importer.jobs.delete_import_job_task",
            import_job_id,
            job_timeout=60,
            result_ttl=0,
        )
    except Exception as e:
        logger.warning("Could not schedule job cleanup for %s: %s", import_job_id, e)


def delete_import_job_task(import_job_id: int) -> None:
    """Delete an ImportJob row (called by RQ scheduler after grace period)."""
    from app.extensions import db
    from app.models.job import ImportJob, ImportJobStatus

    job = db.session.get(ImportJob, import_job_id)
    if job and job.status == ImportJobStatus.DONE:
        db.session.delete(job)
        db.session.commit()


LLM_QUEUE_MAX = 3   # max pending LLM enhance jobs; extras are silently dropped


def enqueue_llm_enhance(apartment_id: int) -> None:
    """Enqueue a non-blocking LLM enhancement job for an apartment.

    Uses a deterministic job ID so the same apartment can never have two
    LLM jobs queued simultaneously.  Also caps total pending LLM jobs at
    LLM_QUEUE_MAX so a burst of imports doesn't create an unbounded backlog.
    """
    try:
        from app.models.settings import AppSetting
        if AppSetting.get("ai_enabled") == "0":
            logger.debug("AI extraction disabled — skipping LLM enhance for apartment %s", apartment_id)
            return
    except Exception:
        pass
    try:
        redis = Redis.from_url(current_app.config["REDIS_URL"])
        q = Queue(QUEUE_NAME, connection=redis)
        job_id = f"llm-enhance-{apartment_id}"

        # Skip if a job for this apartment is already queued or running
        from rq.job import Job as _Job
        try:
            existing = _Job.fetch(job_id, connection=redis)
            if existing.get_status() in ("queued", "started"):
                logger.debug("LLM enhance already pending for apartment %s", apartment_id)
                return
        except Exception:
            pass  # job doesn't exist → proceed

        # Cap total pending LLM jobs (job IDs use our deterministic prefix)
        pending = sum(1 for jid in q.job_ids if jid.startswith("llm-enhance-"))
        if pending >= LLM_QUEUE_MAX:
            logger.info(
                "LLM queue has %d pending jobs (max %d) — skipping enhance for apartment %s",
                pending, LLM_QUEUE_MAX, apartment_id,
            )
            return

        q.enqueue(
            "app.services.importer.jobs.llm_enhance_task",
            apartment_id,
            job_id=job_id,
            job_timeout=75,
            result_ttl=0,
            failure_ttl=3600,
        )
    except Exception as e:
        logger.warning("Could not enqueue LLM enhance for apartment %s: %s", apartment_id, e)


def llm_enhance_task(apartment_id: int) -> None:
    """Run LLM field extraction + summary generation for an already-imported apartment."""
    from app.extensions import db
    from app.models.apartment import Apartment
    from app.services.importer.pipeline import _apply_llm_fields, _build_llm_context
    from app.services.llm import extract_fields

    apt = db.session.get(Apartment, apartment_id)
    if not apt:
        return
    desc = apt.description or ""
    if not desc.strip():
        return
    context = _build_llm_context(apt)
    fields = extract_fields(desc, context=context)
    if fields:
        _apply_llm_fields(apt, fields)
        db.session.commit()
        logger.info("LLM enhance done for apartment %s", apartment_id)


def _pull_job_id(model_name: str) -> str:
    import re
    safe = re.sub(r'[^a-zA-Z0-9_-]', '-', model_name)
    return f"ollama-pull-{safe}"


def enqueue_ollama_pull(model_name: str) -> None:
    """Enqueue an ollama pull job. Uses a deterministic job ID so the same model
    can't be queued twice simultaneously."""
    try:
        q = _get_queue()
        job_id = _pull_job_id(model_name)
        from rq.job import Job as _Job
        redis = Redis.from_url(current_app.config["REDIS_URL"])
        try:
            existing = _Job.fetch(job_id, connection=redis)
            if existing.get_status() in ("queued", "started"):
                logger.info("Pull job already running for model %s", model_name)
                return
        except Exception:
            pass
        q.enqueue(
            "app.services.importer.jobs.ollama_pull_task",
            model_name,
            job_id=job_id,
            job_timeout=1800,
            result_ttl=3600,
            failure_ttl=86400,
        )
        logger.info("Enqueued ollama pull for model %s", model_name)
    except Exception as e:
        logger.warning("Could not enqueue ollama pull for %s: %s", model_name, e)


def get_pull_job_status(model_name: str) -> str | None:
    """Return 'queued', 'started', 'finished', 'failed', or None (not found)."""
    try:
        redis = Redis.from_url(current_app.config["REDIS_URL"])
        from rq.job import Job as _Job
        job = _Job.fetch(_pull_job_id(model_name), connection=redis)
        return str(job.get_status())
    except Exception:
        return None


def get_rq_job_status(job_id: str) -> str | None:
    """Return status of any RQ job by ID, or None if not found."""
    try:
        redis = Redis.from_url(current_app.config["REDIS_URL"])
        from rq.job import Job as _Job
        job = _Job.fetch(job_id, connection=redis)
        return str(job.get_status())
    except Exception:
        return None


def ollama_pull_task(model_name: str) -> None:
    """Worker task: runs 'ollama pull <model_name>' as a subprocess."""
    import subprocess
    logger.info("Starting ollama pull for model: %s", model_name)
    result = subprocess.run(
        ["ollama", "pull", model_name],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ollama pull {model_name} failed: {result.stderr[:500]}")
    logger.info("Successfully pulled Ollama model: %s", model_name)


# ── Auto-refresh scheduling ───────────────────────────────────────────────────

AUTO_REFRESH_JOB_ID = "auto-refresh-daily"


def _schedule_next_auto_refresh(delay_hours: int = 24) -> None:
    """Enqueue the auto-refresh task to run delay_hours from now."""
    from datetime import timedelta
    try:
        q = _get_queue()
        q.enqueue_in(
            timedelta(hours=delay_hours),
            "app.services.importer.jobs.auto_refresh_all_task",
            job_id=AUTO_REFRESH_JOB_ID,
            job_timeout=3600,
            result_ttl=3600,
            failure_ttl=86400,
        )
        logger.info("Next auto-refresh scheduled in %dh", delay_hours)
    except Exception as e:
        logger.warning("Could not schedule auto-refresh: %s", e)


def auto_refresh_all_task() -> None:
    """Daily worker task: enqueue a refresh for every active listing source,
    then re-schedule itself for the next day."""
    from app.models.listing import ListingSource
    sources = ListingSource.query.filter_by(is_active=True).all()
    count = 0
    for src in sources:
        try:
            enqueue_refresh(src.id)
            count += 1
        except Exception as e:
            logger.warning("Could not enqueue refresh for source %s: %s", src.id, e)
    logger.info("Auto-refresh: enqueued %d refresh job(s)", count)
    _schedule_next_auto_refresh(delay_hours=24)


def get_auto_refresh_status() -> dict:
    """Return info about the scheduled auto-refresh job (for admin display)."""
    try:
        redis = Redis.from_url(current_app.config["REDIS_URL"])
        from rq.job import Job as _Job
        job = _Job.fetch(AUTO_REFRESH_JOB_ID, connection=redis)
        return {
            "scheduled": True,
            "status": str(job.get_status()),
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        }
    except Exception:
        return {"scheduled": False}
