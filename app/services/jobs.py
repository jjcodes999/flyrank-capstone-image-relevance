"""Background batch jobs, stored in Postgres (jobs + job_items).

JobService is used by the API to create/read jobs. JobRunner is used by the worker
process to execute them: per-item retries with exponential backoff, progress after every
item, a failed status (plus an ALERT log line) when items exhaust their retries, and
idempotent re-runs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.ollama import AIClient
from app.config import Settings
from app.errors import BudgetExceeded, InvalidModelOutput, NotFound
from app.models import Job, JobItem
from app.repositories.images import ImageRepository
from app.repositories.jobs import JobRepository
from app.services.costs import CallContext, CostTracker
from app.services.pipeline import ImagePipeline, PermanentItemError

log = logging.getLogger(__name__)

JOB_KINDS = ("images",)


class JobService:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.jobs = JobRepository(session)

    def _targets(self, tenant_id: int, kind: str) -> list[tuple[str, int]]:
        targets: list[tuple[str, int]] = []
        if kind in ("images", "ingest"):
            targets += [("image", i) for i in ImageRepository(self.s).ids(tenant_id)]
        return targets

    def create(
        self, tenant_id: int, kind: str, *, idempotency_key: str | None = None, force: bool = False
    ) -> tuple[Job, bool]:
        """Create a job, or return the existing one for the same idempotency key.

        Returns (job, created). The unique (tenant_id, idempotency_key) constraint makes this
        safe even when two identical requests race.
        """
        if idempotency_key:
            existing = self.jobs.get_by_key(tenant_id, idempotency_key)
            if existing is not None:
                return existing, False
        job = Job(tenant_id=tenant_id, kind=kind, idempotency_key=idempotency_key, force=force)
        try:
            self.jobs.add(job, self._targets(tenant_id, kind))
            self.s.commit()
        except IntegrityError:
            self.s.rollback()
            existing = self.jobs.get_by_key(tenant_id, idempotency_key or "")
            if existing is None:
                raise
            return existing, False
        return job, True


ItemHandler = Callable[[Session, Job, JobItem, CallContext], str]


class JobRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        client: AIClient,
        settings: Settings,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.sessions = session_factory
        self.client = client
        self.settings = settings
        self.costs = CostTracker(session_factory, settings)
        self.sleep = sleep
        self.handlers: dict[str, ItemHandler] = {"image": self._handle_image}

    # --- item handlers -------------------------------------------------------------
    def _handle_image(self, s: Session, job: Job, item: JobItem, ctx: CallContext) -> str:
        return ImagePipeline(s, self.client, self.costs, self.settings).process(
            job.tenant_id, item.target_id, ctx, job.force
        )

    def _mark_target_failed(self, s: Session, job: Job, item: JobItem, error: str) -> None:
        if item.target_type == "image":
            ImagePipeline(s, self.client, self.costs, self.settings).mark_failed(job.tenant_id, item.target_id, error)

    # --- execution ------------------------------------------------------------------
    def run_once(self) -> bool:
        """Recover stale jobs, then claim and run one job. Returns False when idle."""
        with self.sessions() as s:
            requeued = JobRepository(s).requeue_stale(self.settings.job_stale_after_s)
            s.commit()
            if requeued:
                log.warning("requeued stale jobs %s (worker heartbeat lost)", requeued)
        with self.sessions() as s:
            job = JobRepository(s).claim_next()
            s.commit()
            if job is None:
                return False
            job_id = job.id
        self.run_job(job_id)
        return True

    def run_job(self, job_id: int) -> None:
        with self.sessions() as s:
            item_ids = [i.id for i in JobRepository(s).pending_items(job_id)]
        log.info("job %s: %d item(s) to process", job_id, len(item_ids))

        budget_error: str | None = None
        for item_id in item_ids:
            if budget_error:
                self._fail_item(job_id, item_id, f"not attempted: {budget_error}")
                continue
            try:
                self._run_item(job_id, item_id)
            except BudgetExceeded as exc:
                budget_error = exc.message
                log.error("job %s: budget guard stopped the job: %s", job_id, exc.message)

        self._finish(job_id, budget_error)

    def _run_item(self, job_id: int, item_id: int) -> None:
        max_attempts = self.settings.job_max_attempts
        while True:
            with self.sessions() as s:
                job = s.get(Job, job_id)
                item = s.get(JobItem, item_id)
                assert job is not None and item is not None
                item.status = "running"
                item.attempts += 1
                attempt = item.attempts
                s.commit()

                ctx = CallContext(job.tenant_id, job.id, item.target_type, item.target_id)
                try:
                    outcome = self.handlers[item.target_type](s, job, item, ctx)
                    item.status = outcome
                    item.last_error = None
                    JobRepository(s).refresh_progress(job)
                    s.commit()
                    log.info("job %s item %s (%s %s): %s", job_id, item_id, item.target_type, item.target_id, outcome)
                    return
                except BudgetExceeded as exc:
                    s.rollback()
                    self._fail_item(job_id, item_id, exc.message)
                    raise
                except (InvalidModelOutput, PermanentItemError, NotFound) as exc:
                    s.rollback()
                    self._fail_item(job_id, item_id, str(exc), mark_target=True)
                    return
                except Exception as exc:  # transient: Ollama down/timeout, DB hiccup
                    s.rollback()
                    error = f"attempt {attempt}/{max_attempts}: {type(exc).__name__}: {exc}"
                    if attempt >= max_attempts:
                        self._fail_item(job_id, item_id, error, mark_target=True)
                        return
                    delay = self.settings.job_backoff_base_s * 2 ** (attempt - 1)
                    log.warning("job %s item %s failed, retrying in %.0fs: %s", job_id, item_id, delay, error)
                    with self.sessions() as s2:
                        it = s2.get(JobItem, item_id)
                        assert it is not None
                        it.status = "queued"
                        it.last_error = error[:2000]
                        s2.commit()
            self.sleep(delay)

    def _fail_item(self, job_id: int, item_id: int, error: str, mark_target: bool = False) -> None:
        with self.sessions() as s:
            job = s.get(Job, job_id)
            item = s.get(JobItem, item_id)
            assert job is not None and item is not None
            item.status = "failed"
            item.last_error = error[:2000]
            if mark_target:
                self._mark_target_failed(s, job, item, error)
            JobRepository(s).refresh_progress(job)
            s.commit()
        log.error("job %s item %s failed permanently: %s", job_id, item_id, error)

    def _finish(self, job_id: int, budget_error: str | None) -> None:
        with self.sessions() as s:
            repo = JobRepository(s)
            job = s.get(Job, job_id)
            assert job is not None
            repo.refresh_progress(job)
            job.finished_at = datetime.now(timezone.utc)
            if job.failed:
                job.status = "failed"
                job.error = budget_error or f"{job.failed} of {job.total} item(s) failed after retries"
                # the failure alert: one greppable line with everything an operator needs
                log.error(
                    "ALERT job %s failed: %s (succeeded=%s skipped=%s failed=%s)",
                    job.id, job.error, job.succeeded, job.skipped, job.failed,
                )
            else:
                job.status = "succeeded"
                job.error = None
            s.commit()
            log.info("job %s finished: %s", job.id, job.status)
