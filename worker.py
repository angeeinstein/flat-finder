"""RQ worker entry point.

Run with:
    venv/bin/python worker.py
or (directly via rq CLI):
    venv/bin/rq worker -u $REDIS_URL flat-finder
"""
from __future__ import annotations

import sys

from redis import Redis
from rq import Queue, Worker

from app import create_app


QUEUE_NAME = "flat-finder"


def main() -> int:
    app = create_app()
    app.app_context().push()
    redis_url = app.config["REDIS_URL"]
    conn = Redis.from_url(redis_url)
    worker = Worker([Queue(QUEUE_NAME, connection=conn)], connection=conn)
    worker.work(with_scheduler=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
