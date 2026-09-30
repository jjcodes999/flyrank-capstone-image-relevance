"""Regression tests for the gaps an external audit found (one test per finding).

Background jobs, budget, embeddings and seed recovery run against the real test database
with a scripted fake model, like tests/test_jobs.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from PIL import Image as PILImage

from app.ai.ollama import EmbedResult
from app.config import Settings
from app.errors import BudgetExceeded
from app.models import CostRecord, Image, Job, JobItem, Tenant
from app.services.costs import USAGE_UNKNOWN, CallContext, CostTracker
from app.services.embeddings import vector_problem
from app.services.jobs import JobRunner, JobService
from scripts.eval import PostResult, score
from tests.fakes import FakeClient, OllamaError

TAGS = json.dumps({"subject": "red fox", "category": "animal", "attributes": ["orange fur"],
                   "caption": "A red fox in the grass.", "confidence": 0.93})


@pytest.fixture()
def one_image(sessions, tmp_path):
    PILImage.new("RGB", (64, 64), "orange").save(tmp_path / "a.jpg")
    with sessions() as s:
        t = Tenant(slug="demo", name="Demo")
        s.add(t)
        s.flush()
        s.add(Image(tenant_id=t.id, filename="a.jpg", sha256="0" * 64, width=64, height=64))
        s.commit()
        tenant_id = t.id
    return tenant_id, Settings(_env_file=None, images_dir=str(tmp_path), job_backoff_base_s=0.0, blur_threshold=0.0)


def new_job(sessions, tenant_id, **kw) -> int:
    with sessions() as s:
        job, _ = JobService(s).create(tenant_id, "images", **kw)
        return job.id


# --- jobs -------------------------------------------------------------------------------
def test_shutdown_during_the_last_items_retry_never_marks_the_job_succeeded(sessions, one_image):
    tenant_id, settings = one_image
    job_id = new_job(sessions, tenant_id)
    stopping = {"now": False}

    def fail_then_stop(*a, **kw):
        stopping["now"] = True
        raise OllamaError("timed out")

    runner = JobRunner(sessions, FakeClient(), settings, sleep=lambda _: None, should_stop=lambda: stopping["now"])
    runner.client.chat_json = fail_then_stop
    runner.run_once()
    with sessions() as s:
        job = s.get(Job, job_id)
        item = s.query(JobItem).one()
        assert (job.status, job.processed, item.status) == ("queued", 0, "queued")
    # the next worker finishes it
    JobRunner(sessions, FakeClient([TAGS]), settings, sleep=lambda _: None).run_once()
    with sessions() as s:
        assert s.get(Job, job_id).status == "succeeded"


def test_a_forced_retry_after_an_embedding_failure_does_not_redo_the_vision_call(sessions, one_image):
    tenant_id, settings = one_image
    JobRunner(sessions, FakeClient([TAGS]), settings, sleep=lambda _: None).run_once()  # tag once
    new_job(sessions, tenant_id, force=True)
    client = FakeClient([TAGS, TAGS], embed_errors=[OllamaError("embedding timed out")])
    JobRunner(sessions, client, settings, sleep=lambda _: None).run_once()
    assert len(client.chat_calls) == 1  # forced once, not once per attempt
    assert len(client.embed_calls) == 2  # the failed embedding, then the retry


def test_model_calls_refresh_the_job_heartbeat(sessions, one_image):
    tenant_id, settings = one_image
    job_id = new_job(sessions, tenant_id)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    with sessions() as s:
        s.get(Job, job_id).heartbeat_at = old
        s.commit()
    CostTracker(sessions, settings).begin(CallContext(tenant_id, job_id, "image", 1), operation="vision_tag", model="m")
    with sessions() as s:
        assert s.get(Job, job_id).heartbeat_at > old + timedelta(hours=1)


def test_seed_rerun_queues_images_that_a_finished_job_left_pending(sessions, one_image):
    tenant_id, settings = one_image
    job_id = new_job(sessions, tenant_id, idempotency_key="seed-x")
    JobRunner(sessions, FakeClient([TAGS]), settings, sleep=lambda _: None).run_once()
    with sessions() as s:  # a second image arrives after the first run (e.g. a retried download)
        s.add(Image(tenant_id=tenant_id, filename="late.jpg", sha256="1" * 64, width=1, height=1))
        s.commit()
        service = JobService(s)
        same, created = service.create(tenant_id, "images", idempotency_key="seed-x")
        assert not created and same.id == job_id
        follow_up, resumed = service.resume(tenant_id, same)
        assert resumed and follow_up.total == 1 and follow_up.id != job_id


# --- budget: a hard cap ------------------------------------------------------------------
def test_a_budget_smaller_than_one_calls_worst_case_refuses_the_call(sessions, one_image):
    tenant_id, base = one_image
    settings = base.model_copy(update={"ai_budget_usd": 0.000001})
    tracker = CostTracker(sessions, settings)
    with pytest.raises(BudgetExceeded):
        tracker.begin(CallContext(tenant_id), operation="vision_tag", model="m")
    with sessions() as s:
        assert s.query(CostRecord).count() == 0  # nothing spent, nothing recorded


def test_total_notional_spend_never_exceeds_the_budget(sessions, one_image):
    tenant_id, base = one_image
    settings = base.model_copy(update={"ai_budget_usd": 0.004})  # room for one vision reserve
    tracker = CostTracker(sessions, settings)
    calls = 0
    with pytest.raises(BudgetExceeded):
        for _ in range(1000):
            row = tracker.begin(CallContext(tenant_id), operation="vision_tag", model="m")
            tracker.finish(row, input_tokens=1200, output_tokens=2000, success=True)
            calls += 1
    with sessions() as s:
        total = sum((r.notional_cost_usd for r in s.query(CostRecord)), Decimal("0"))
    assert calls >= 1 and total <= Decimal("0.004")


def test_a_call_with_unknown_usage_keeps_its_reservation_as_cost(sessions, one_image):
    tenant_id, settings = one_image
    tracker = CostTracker(sessions, settings)
    row = tracker.begin(CallContext(tenant_id), operation="vision_tag", model="m")
    tracker.finish(row, input_tokens=None, duration_ms=1_800_000, success=False, error="ReadTimeout")
    with sessions() as s:
        rec = s.get(CostRecord, row)
        assert rec.notional_cost_usd == tracker.reservation("vision_tag") > 0
        assert USAGE_UNKNOWN in rec.error and rec.duration_ms == 1_800_000


# --- embeddings --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vectors, problem",
    [
        ([[0.0] * 384], "all zeros"),
        ([[float("nan")] + [1.0] * 383], "non-finite"),
        ([[1.0] * 10], "10 dims"),
    ],
)
def test_unusable_vectors_are_refused(vectors, problem):
    assert problem in vector_problem(vectors, 384)


def test_a_zero_vector_from_the_model_fails_the_item_instead_of_being_stored(sessions, one_image):
    tenant_id, settings = one_image
    job_id = new_job(sessions, tenant_id)
    client = FakeClient([TAGS], vectors={})
    client.embed = lambda model, texts: EmbedResult(
        vectors=[[0.0] * 384 for _ in texts], input_tokens=5, duration_ms=1, model=model
    )
    JobRunner(sessions, client, settings, sleep=lambda _: None).run_once()
    with sessions() as s:
        job = s.get(Job, job_id)
        img = s.query(Image).one()
        assert job.status == "failed" and img.status == "failed" and img.embedding is None
        assert "all zeros" in s.query(JobItem).one().last_error


# --- evaluation metric -------------------------------------------------------------------
def test_precision_when_answered_counts_wrong_answers_on_no_match_posts():
    def result(slug, correct, suggested):
        sug = {"filename": suggested} if suggested else None
        return PostResult(slug, correct, {"suggestion": sug, "candidates": []})

    m = score([result("fox", ["fox.jpg"], "fox.jpg"), result("parrot", [], "wolf.jpg")], None)
    assert (m["answered"], m["precision_when_answered"]) == (2, 0.5)
