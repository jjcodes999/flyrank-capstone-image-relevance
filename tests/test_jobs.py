"""The batch job: retries, failure status + alert, idempotent re-runs, cost rows, budget guard.

Runs the real JobRunner against the test database with a scripted fake model.
"""

from __future__ import annotations

import json
import logging

import pytest
from PIL import Image as PILImage

from app.config import Settings
from app.models import CostRecord, Image, Job, JobItem, Post, Tenant
from app.services.jobs import JobRunner, JobService
from tests.fakes import FakeClient, OllamaError

TAGS = json.dumps({"subject": "red fox", "category": "animal", "attributes": ["orange fur"],
                   "caption": "A red fox in the grass.", "confidence": 0.93})
POST_ANALYSIS = json.dumps({"subject": "red fox", "category": "animal", "concepts": ["fox"],
                            "summary": "A post about red foxes.", "confidence": 0.9})


@pytest.fixture()
def setup(sessions, tmp_path):
    for name in ("a.jpg", "b.jpg"):
        PILImage.new("RGB", (64, 64), "orange").save(tmp_path / name)
    with sessions() as s:
        t = Tenant(slug="demo", name="Demo")
        s.add(t)
        s.flush()
        for name in ("a.jpg", "b.jpg"):
            s.add(Image(tenant_id=t.id, filename=name, sha256="0" * 64, width=64, height=64))
        s.commit()
        tenant_id = t.id
    settings = Settings(_env_file=None, images_dir=str(tmp_path), job_backoff_base_s=0.0, blur_threshold=0.0)
    return tenant_id, settings


def run_job(sessions, settings, client, tenant_id, kind="images", key=None, force=False) -> Job:
    with sessions() as s:
        job, _ = JobService(s).create(tenant_id, kind, idempotency_key=key, force=force)
    JobRunner(sessions, client, settings, sleep=lambda _: None).run_once()
    with sessions() as s:
        return s.get(Job, job.id)


def test_all_images_tagged_embedded_and_costed(sessions, setup):
    tenant_id, settings = setup
    job = run_job(sessions, settings, FakeClient([TAGS, TAGS]), tenant_id)
    assert (job.status, job.succeeded, job.failed, job.processed, job.total) == ("succeeded", 2, 0, 2, 2)
    with sessions() as s:
        assert {i.status for i in s.query(Image)} == {"tagged"}
        ops = sorted(r.operation for r in s.query(CostRecord))
        assert ops == ["embed", "embed", "vision_tag", "vision_tag"]  # one row per AI call
        assert all(r.job_id == job.id and r.target_type == "image" for r in s.query(CostRecord))


def test_transient_error_is_retried_then_succeeds(sessions, setup):
    tenant_id, settings = setup
    client = FakeClient([OllamaError("connection refused"), TAGS, TAGS])
    job = run_job(sessions, settings, client, tenant_id)
    assert job.status == "succeeded"
    with sessions() as s:
        first = s.query(JobItem).order_by(JobItem.id).first()
        assert first.attempts == 2 and first.status == "done"
        failed_calls = s.query(CostRecord).filter_by(success=False).all()
        assert len(failed_calls) == 1 and "connection refused" in failed_calls[0].error


def test_item_that_keeps_failing_marks_job_failed_with_alert(sessions, setup, caplog):
    tenant_id, settings = setup
    client = FakeClient([OllamaError("timeout")] * 3 + [TAGS])  # image a: 3 transient failures
    with caplog.at_level(logging.ERROR):
        job = run_job(sessions, settings, client, tenant_id)
    assert job.status == "failed" and job.failed == 1 and job.succeeded == 1
    assert "1 of 2 item(s) failed after retries" in job.error
    assert any("ALERT job" in r.message for r in caplog.records)
    with sessions() as s:
        bad = s.query(Image).filter_by(filename="a.jpg").one()
        assert bad.status == "failed" and "timeout" in bad.error


def test_invalid_model_output_is_never_stored(sessions, setup):
    tenant_id, settings = setup
    invalid = json.dumps({"subject": "fox", "category": "spaceship", "attributes": [], "caption": "x",
                          "confidence": 7})
    client = FakeClient([invalid, invalid, invalid, TAGS])  # a: invalid 3x (1 try + 2 retries)
    job = run_job(sessions, settings, client, tenant_id)
    assert job.status == "failed"
    with sessions() as s:
        bad = s.query(Image).filter_by(filename="a.jpg").one()
        assert bad.status == "failed" and bad.meta is None  # nothing was written
        assert "schema validation" in bad.error
        assert s.query(CostRecord).filter_by(operation="vision_tag", success=False).count() == 3


def test_rerun_is_idempotent_and_makes_no_ai_calls(sessions, setup):
    tenant_id, settings = setup
    run_job(sessions, settings, FakeClient([TAGS, TAGS]), tenant_id)
    client = FakeClient([])  # any call would fail: the script is empty
    job = run_job(sessions, settings, client, tenant_id)
    assert job.status == "succeeded" and job.skipped == 2 and job.succeeded == 0
    assert client.chat_calls == [] and client.embed_calls == []
    # force=true re-processes
    forced = run_job(sessions, settings, FakeClient([TAGS, TAGS]), tenant_id, force=True)
    assert forced.succeeded == 2


def test_same_idempotency_key_runs_once(sessions, setup):
    tenant_id, settings = setup
    first = run_job(sessions, settings, FakeClient([TAGS, TAGS]), tenant_id, key="nightly-1")
    with sessions() as s:
        again, created = JobService(s).create(tenant_id, "images", idempotency_key="nightly-1")
    assert not created and again.id == first.id


def test_budget_guard_stops_the_job(sessions, setup):
    tenant_id, base = setup
    settings = base.model_copy(update={"ai_max_calls_per_job": 1})
    client = FakeClient([TAGS, TAGS])
    job = run_job(sessions, settings, client, tenant_id)
    assert job.status == "failed" and "cap of 1 AI calls" in job.error
    with sessions() as s:
        items = s.query(JobItem).order_by(JobItem.id).all()
        assert [i.status for i in items] == ["failed", "failed"]
        assert "not attempted" in items[1].last_error
    assert len(client.chat_calls) == 1  # the second image was never sent


def test_posts_are_analysed_and_embedded(sessions, setup):
    tenant_id, settings = setup
    with sessions() as s:
        s.add(Post(tenant_id=tenant_id, slug="vulpes", title="Vulpes vulpes", body="Field notes on V. vulpes."))
        s.commit()
    job = run_job(sessions, settings, FakeClient([POST_ANALYSIS]), tenant_id, kind="posts")
    assert job.status == "succeeded"
    with sessions() as s:
        post = s.query(Post).one()
        assert (post.status, post.subject, post.category) == ("ready", "red fox", "animal")
        assert post.embedding is not None


def test_a_call_that_never_returns_still_leaves_a_cost_row(sessions, setup):
    """Write-ahead cost rows: simulate a worker killed in the middle of a model call."""
    from app.services.costs import IN_PROGRESS, CallContext, CostTracker

    tenant_id, settings = setup
    tracker = CostTracker(sessions, settings)
    tracker.begin(CallContext(tenant_id, None, "image", 1), operation="vision_tag", model="qwen3-vl:4b")
    # ... the process dies here, finish() never runs ...
    with sessions() as s:
        row = s.query(CostRecord).one()
        assert (row.operation, row.target_type, row.target_id, row.success) == ("vision_tag", "image", 1, False)
        assert row.error == IN_PROGRESS
