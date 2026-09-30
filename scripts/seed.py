"""Seed demo data: download images, register images and posts, queue the batch job.

Usage (inside the api container):  python -m scripts.seed [--wait]

Idempotent: re-running it does not duplicate images, and the batch job uses an
idempotency key derived from the manifest, so the same seed returns the same job.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

from PIL import Image as PILImage

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Image, Post
from app.repositories.images import ImageRepository
from app.repositories.jobs import JobRepository
from app.repositories.posts import PostRepository
from app.repositories.tenants import TenantRepository
from app.services.jobs import JobService
from scripts.download_images import download_corpus

MANIFEST = "data/manifest.csv"
POSTS = "data/posts.json"


def register_images(session, tenant_id: int, images_dir: Path) -> tuple[int, int]:
    repo = ImageRepository(session)
    added = updated = 0
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            path = images_dir / row["filename"]
            if not path.is_file():
                print(f"  missing file, not registered: {path}")
                continue
            data = path.read_bytes()
            with PILImage.open(path) as im:
                width, height = im.size
            fields = dict(
                sha256=hashlib.sha256(data).hexdigest(),
                width=width,
                height=height,
                source_url=row["source_url"],
                photographer=row["photographer"],
                license=row["license"],
            )
            image = repo.get_by_filename(tenant_id, row["filename"])
            if image is None:
                repo.add(Image(tenant_id=tenant_id, filename=row["filename"], **fields))
                added += 1
            else:
                for k, v in fields.items():
                    setattr(image, k, v)
                updated += 1
    return added, updated


def register_posts(session, tenant_id: int) -> tuple[int, int]:
    repo = PostRepository(session)
    added = updated = 0
    with open(POSTS, encoding="utf-8") as f:
        for row in json.load(f):
            post = repo.get_by_slug(tenant_id, row["slug"])
            if post is None:
                repo.add(Post(tenant_id=tenant_id, slug=row["slug"], title=row["title"], body=row["body"]))
                added += 1
            elif (post.title, post.body) != (row["title"], row["body"]):
                post.title, post.body = row["title"], row["body"]  # analysis is redone by the next job
                updated += 1
    return added, updated


def seed_key(*paths: str) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return "seed-" + h.hexdigest()[:16]


def wait_for_job(tenant_id: int, job_id: int, poll_s: float = 15.0) -> str:
    sessions = get_sessionmaker()
    last = None
    while True:
        with sessions() as s:
            job = JobRepository(s).get(tenant_id, job_id)
            assert job is not None
            line = f"job {job.id} {job.status}: {job.processed}/{job.total} processed ({job.succeeded} done, {job.skipped} skipped, {job.failed} failed)"
            if line != last:
                print(time.strftime("%H:%M:%S"), line, flush=True)
                last = line
            if job.status in ("succeeded", "failed"):
                if job.error:
                    print("  error:", job.error)
                return job.status
        time.sleep(poll_s)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default=None)
    parser.add_argument("--wait", action="store_true", help="block until the batch job finishes")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = get_settings()
    tenant_slug = args.tenant or settings.default_tenant
    images_dir = Path(settings.images_dir)

    if not args.skip_download:
        print("1/3 downloading images ...")
        if download_corpus(MANIFEST, str(images_dir)):
            print("some downloads failed; continuing with the images that exist")

    sessions = get_sessionmaker()
    with sessions() as s:
        tenant = TenantRepository(s).get_or_create(tenant_slug, "Demo tenant")
        print("2/3 registering images and posts ...")
        added, updated = register_images(s, tenant.id, images_dir)
        print(f"  images: {added} added, {updated} already registered")
        added, updated = register_posts(s, tenant.id)
        print(f"  posts: {added} added, {updated} updated")
        s.commit()
        tenant_id = tenant.id

        print("3/3 queueing batch job ...")
        jobs = JobService(s)
        job, created = jobs.create(tenant_id, "ingest", idempotency_key=seed_key(MANIFEST, POSTS))
        print(f"  job {job.id} {'created' if created else 'already exists (idempotent re-run)'}: status={job.status}")
        follow_up, resumed = jobs.resume(tenant_id, job)
        if resumed:
            print(f"  job {follow_up.id} created for {follow_up.total} item(s) still pending or failed")
            job = follow_up
        job_id = job.id

    if args.wait:
        status = wait_for_job(tenant_id, job_id)
        return 0 if status == "succeeded" else 1
    print(f"the worker is processing it; follow progress with GET /jobs/{job_id} or add --wait")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
