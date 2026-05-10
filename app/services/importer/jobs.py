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
