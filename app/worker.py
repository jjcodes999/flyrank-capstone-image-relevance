"""Background worker: `python -m app.worker`. Polls Postgres for queued jobs and runs them."""

from __future__ import annotations

import logging
import signal
import time

from app.ai.ollama import OllamaClient
from app.config import get_settings
from app.db import get_sessionmaker
from app.logging_setup import setup_logging
from app.services.jobs import JobRunner

log = logging.getLogger("app.worker")
_stop = False


def _handle_stop(signum, _frame) -> None:  # noqa: ANN001
    global _stop
    _stop = True
    log.info("signal %s received: finishing the current item, then requeueing the job", signum)


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    client = OllamaClient(settings.ollama_base_url, settings.ollama_timeout_s)
    runner = JobRunner(get_sessionmaker(), client, settings, should_stop=lambda: _stop)
    log.info("worker started (vision=%s, embed=%s)", settings.vision_model, settings.embed_model)
    while not _stop:
        try:
            worked = runner.run_once()
        except Exception:  # keep the worker alive; the job stays running and is recovered by heartbeat
            log.exception("worker loop error")
            worked = False
        if not worked:
            time.sleep(settings.job_poll_interval_s)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
