from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from app.api.deps import DB, CurrentTenant
from app.errors import NotFound
from app.models import Job
from app.repositories.jobs import JobRepository
from app.schemas.api import JobCreate, JobItemOut, JobOut
from app.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def job_out(job: Job, repo: JobRepository, with_failures: bool = True) -> JobOut:
    data = {name: getattr(job, name) for name in JobOut.model_fields if hasattr(job, name)}
    data["progress"] = round(job.processed / job.total, 3) if job.total else 1.0
    data["failed_items"] = (
        [JobItemOut.model_validate(i) for i in repo.failed_items(job.id)] if with_failures else []
    )
    return JobOut(**data)


@router.post("", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    db: DB,
    tenant: CurrentTenant,
    response: Response,
    body: JobCreate | None = None,
    idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None,
) -> JobOut:
    """Queue a batch job. Same Idempotency-Key -> same job (200 instead of 202)."""
    body = body or JobCreate()
    job, created = JobService(db).create(tenant.id, body.kind, idempotency_key=idempotency_key, force=body.force)
    if not created:
        response.status_code = status.HTTP_200_OK
    return job_out(job, JobRepository(db))


@router.get("", response_model=list[JobOut])
def list_jobs(db: DB, tenant: CurrentTenant) -> list[JobOut]:
    repo = JobRepository(db)
    return [job_out(j, repo, with_failures=False) for j in repo.list(tenant.id)]


@router.get("/{job_id}", response_model=JobOut)
def get_job(db: DB, tenant: CurrentTenant, job_id: Annotated[int, Path(ge=1)]) -> JobOut:
    repo = JobRepository(db)
    job = repo.get(tenant.id, job_id)
    if job is None:
        raise NotFound(f"job {job_id} not found")
    return job_out(job, repo)
