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
