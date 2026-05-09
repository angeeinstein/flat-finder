"""RQ job entry points + Redis queue helpers."""
from __future__ import annotations

import logging

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
