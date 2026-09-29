from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Job, JobItem


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, tenant_id: int, job_id: int) -> Job | None:
        return self.s.scalar(select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id))

    def get_any(self, job_id: int) -> Job | None:
        """Worker-side lookup (the worker serves every tenant)."""
        return self.s.get(Job, job_id)

    def get_by_key(self, tenant_id: int, key: str) -> Job | None:
        return self.s.scalar(select(Job).where(Job.tenant_id == tenant_id, Job.idempotency_key == key))

    def list(self, tenant_id: int, limit: int = 20) -> list[Job]:
        return list(
            self.s.scalars(select(Job).where(Job.tenant_id == tenant_id).order_by(Job.id.desc()).limit(limit))
        )

    def add(self, job: Job, targets: list[tuple[str, int]]) -> Job:
        job.total = len(targets)
        self.s.add(job)
        self.s.flush()
        for target_type, target_id in targets:
            self.s.add(JobItem(job_id=job.id, target_type=target_type, target_id=target_id))
        self.s.flush()
        return job

    def claim_next(self) -> Job | None:
        """Atomically move the oldest queued job to running.

        FOR UPDATE SKIP LOCKED means two workers can never claim the same job.
        """
        job = self.s.scalar(
            select(Job).where(Job.status == "queued").order_by(Job.id).limit(1).with_for_update(skip_locked=True)
        )
        if job is None:
            return None
        now = utcnow()
        job.status = "running"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        self.s.flush()
        return job

    def requeue_stale(self, stale_after_s: float) -> list[int]:
        """Jobs whose worker stopped heartbeating go back to the queue (their items resume)."""
        cutoff = utcnow() - timedelta(seconds=stale_after_s)
        ids = list(
            self.s.scalars(
                update(Job)
                .where(Job.status == "running", Job.heartbeat_at < cutoff)
                .values(status="queued")
                .returning(Job.id)
            )
        )
        if ids:
            self.s.execute(
                update(JobItem).where(JobItem.job_id.in_(ids), JobItem.status == "running").values(status="queued")
            )
        return ids

    def pending_items(self, job_id: int) -> list[JobItem]:
        # posts after images is just a stable order; items are independent
        return list(
            self.s.scalars(
                select(JobItem)
                .where(JobItem.job_id == job_id, JobItem.status.in_(("queued", "running")))
                .order_by(JobItem.target_type, JobItem.id)
            )
        )

    def failed_items(self, job_id: int) -> list[JobItem]:
        return list(
            self.s.scalars(
                select(JobItem).where(JobItem.job_id == job_id, JobItem.status == "failed").order_by(JobItem.id)
            )
        )

    def item_counts(self, job_id: int) -> dict[str, int]:
        rows = self.s.execute(
            select(JobItem.status, func.count()).where(JobItem.job_id == job_id).group_by(JobItem.status)
        )
        return {status: n for status, n in rows}

    def refresh_progress(self, job: Job) -> None:
        counts = self.item_counts(job.id)
        job.succeeded = counts.get("done", 0)
        job.skipped = counts.get("skipped", 0)
        job.failed = counts.get("failed", 0)
        job.processed = job.succeeded + job.skipped + job.failed
        job.heartbeat_at = utcnow()
        self.s.flush()
