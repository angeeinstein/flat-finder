"""RQ worker entry point.

Run with:
    venv/bin/rq worker -u $REDIS_URL -c worker flat-finder
or:
    venv/bin/python worker.py
"""
from __future__ import annotations

import os
import sys

from redis import Redis
from rq import Connection, Queue, Worker

from app import create_app


QUEUE_NAME = "flat-finder"


def main() -> int:
    app = create_app()
    app.app_context().push()
    redis_url = app.config["REDIS_URL"]
    conn = Redis.from_url(redis_url)
    with Connection(conn):
        worker = Worker([Queue(QUEUE_NAME)])
        worker.work(with_scheduler=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
