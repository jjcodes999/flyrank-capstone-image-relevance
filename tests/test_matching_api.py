"""Matching, guard and review through the real API and a real Postgres + pgvector.

Embeddings are hand-made 384-dim vectors, so similarities are known exactly:
fox image = post direction, wolf = cos 0.80, dog = cos 0.30.
"""

from __future__ import annotations

import math

import pytest

from app.models import (
    Image,
    ImageEmbedding,
    ImageMetadata,
    Post,
    PostEmbedding,
    Review,
    Tenant,
)
from app.services.embeddings import image_embedding_text

DIM = 384


def vec(**parts: float) -> list[float]:
    v = [0.0] * DIM
    for key, val in parts.items():
        v[int(key[1:])] = val
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


FOX_DIR = vec(d0=1)
WOLF_DIR = vec(d0=0.8, d1=0.6)  # cosine 0.80 with the fox direction
DOG_DIR = vec(d0=0.3, d2=math.sqrt(1 - 0.09))  # cosine 0.30
BLUR_DIR = vec(d0=0.95, d3=math.sqrt(1 - 0.9025))  # cosine 0.95
PARROT_DIR = vec(d5=1)  # unrelated to every image

# subject vectors live in their own directions; values mirror real all-minilm scores
# (e.g. "red fox" vs "gray wolf" = 0.53, well under SUBJECT_SIM_THRESHOLD 0.80)
SUBJECT = {
    "red fox": vec(d10=1),
    "gray wolf": vec(d10=0.53, d11=math.sqrt(1 - 0.53**2)),
    "golden retriever": vec(d10=0.3, d12=math.sqrt(1 - 0.09)),
    "parrot": vec(d15=1),
}


def add_image(s, tenant, name, subject, category, direction, conf=0.95, needs_review=False, reasons=()):
    img = Image(tenant_id=tenant.id, filename=name, sha256="x" * 64, width=10, height=10, status="tagged")
    s.add(img)
    s.flush()
    meta = ImageMetadata(
        image_id=img.id, subject=subject, category=category, attributes=["fur"],
        caption=f"A {subject} outdoors.", confidence=conf, needs_review=needs_review,
        review_reasons=list(reasons), sharpness=100.0, model="m", prompt_version="v1",
        source_sha256="x" * 64, raw_response="{}", validation_attempts=1,
    )
    s.add(meta)
    # the embedding text must match the tags, or the image counts as stale (not ready)
    s.add(ImageEmbedding(image_id=img.id, tenant_id=tenant.id, model="e", text=image_embedding_text(meta),
                         embedding=direction, subject_embedding=SUBJECT[subject]))
    return img


def add_post(s, tenant, slug, subject, category, direction, ready=True):
    post = Post(tenant_id=tenant.id, slug=slug, title=slug.replace("-", " "), body="body " * 10,
                status="ready" if ready else "pending", subject=subject if ready else None,
                category=category if ready else None, analysis_confidence=0.95 if ready else None)
    s.add(post)
    s.flush()
    if ready:
        s.add(PostEmbedding(post_id=post.id, model="e", text=subject, embedding=direction,
                            subject_embedding=SUBJECT[subject]))
    return post


@pytest.fixture()
def world(sessions):
    with sessions() as s:
        demo = Tenant(slug="demo", name="Demo")
        other = Tenant(slug="other", name="Other")
        s.add_all([demo, other])
        s.flush()
        ids = {
            "fox": add_image(s, demo, "fox.jpg", "red fox", "animal", FOX_DIR).id,
            "wolf": add_image(s, demo, "wolf.jpg", "gray wolf", "animal", WOLF_DIR).id,
            "dog": add_image(s, demo, "dog.jpg", "golden retriever", "animal", DOG_DIR).id,
            "blurry": add_image(s, demo, "blurry.jpg", "red fox", "animal", BLUR_DIR, conf=0.3,
                                needs_review=True, reasons=("image looks blurry (sharpness 2.2 < 15.0)",)).id,
            "fox_post": add_post(s, demo, "red-fox-behavior", "red fox", "animal", FOX_DIR).id,
            "parrot_post": add_post(s, demo, "pet-parrot-care", "parrot", "animal", PARROT_DIR).id,
            "pending_post": add_post(s, demo, "not-analysed", None, None, None, ready=False).id,
        }
        s.commit()
        return ids


# --- matching -------------------------------------------------------------------------
def test_fox_post_ranks_fox_first_and_explains(client, world):
    r = client.get(f"/posts/{world['fox_post']}/images")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "match"
    assert body["suggestion"]["filename"] == "fox.jpg"
    ranked = [c["filename"] for c in body["candidates"]]
    assert ranked == ["fox.jpg", "blurry.jpg", "wolf.jpg", "dog.jpg"]
    by_name = {c["filename"]: c for c in body["candidates"]}
    assert by_name["fox.jpg"]["similarity"] == pytest.approx(1.0, abs=1e-3)
    assert by_name["wolf.jpg"]["similarity"] == pytest.approx(0.8, abs=1e-3)
    assert "Animal category mismatch: expected red fox, detected gray wolf" in by_name["wolf.jpg"]["reasons"]
    assert by_name["blurry.jpg"]["decision"] == "rejected"
    assert "flagged for review" in by_name["blurry.jpg"]["reasons"][0]
    assert by_name["dog.jpg"]["decision"] == "rejected"


def test_force_checking_the_wolf_on_the_fox_post_is_rejected(client, world):
    r = client.post(f"/posts/{world['fox_post']}/check", json={"image_id": world["wolf"]})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "rejected"
    assert body["explanation"] == "Rejected: Animal category mismatch: expected red fox, detected gray wolf"


def test_post_without_a_suitable_image_gets_no_confident_match(client, world):
    body = client.get(f"/posts/{world['parrot_post']}/images").json()
    assert body["status"] == "no_confident_match" and body["suggestion"] is None
    assert any(r.startswith("Similarity below threshold") for r in body["reasons"])
    assert any(r.startswith("Subjects don't match: no candidate shows 'parrot'") for r in body["reasons"])


def test_suggestions_are_stored_and_re_ranking_is_idempotent(client, world):
    first = client.get(f"/posts/{world['fox_post']}/images").json()
    second = client.get(f"/posts/{world['fox_post']}/images").json()
    assert [c["suggestion_id"] for c in first["candidates"]] == [c["suggestion_id"] for c in second["candidates"]]
    assert len(client.get("/suggestions", params={"post_id": world["fox_post"]}).json()) == 4


# --- review workflow ------------------------------------------------------------------
def test_approve_is_idempotent_and_conflicting_decision_is_refused(client, world, sessions):
    sid = client.get(f"/posts/{world['fox_post']}/images").json()["suggestion"]["suggestion_id"]
    first = client.post(f"/suggestions/{sid}/approve", json={"reviewer": "sam", "note": "good"})
    again = client.post(f"/suggestions/{sid}/approve", json={"reviewer": "sam"})
    assert first.status_code == again.status_code == 200
    assert first.json()["changed"] is True and again.json()["changed"] is False
    with sessions() as s:
        assert s.query(Review).filter_by(suggestion_id=sid).count() == 1  # the retry happened once
    flip = client.post(f"/suggestions/{sid}/reject", json={})
    assert flip.status_code == 409 and flip.json()["error"]["code"] == "conflict"


def test_inspect_shows_why(client, world):
    client.get(f"/posts/{world['fox_post']}/images")
    wolf_sid = client.post(f"/posts/{world['fox_post']}/check", json={"image_id": world["wolf"]}).json()["suggestion_id"]
    client.post(f"/suggestions/{wolf_sid}/reject", json={"note": "wrong animal"})
    detail = client.get(f"/suggestions/{wolf_sid}").json()
    assert detail["decision"] == "rejected" and detail["review_status"] == "rejected"
    assert [c["name"] for c in detail["checks"]] == ["ready", "post", "confidence", "category", "subject", "similarity"]
    assert detail["image"]["meta"]["subject"] == "gray wolf"
    assert detail["reviews"][0]["note"] == "wrong animal"
    assert client.get("/review").status_code == 200


# --- validation at the boundary: clean 4xx, never 500 -----------------------------------
@pytest.mark.parametrize(
    "method, path, kwargs, code",
    [
        ("get", "/posts/abc/images", {}, 422),
        ("get", "/posts/0/images", {}, 422),
        ("get", "/posts/99999/images", {}, 404),
        ("get", "/posts/1/images?limit=0", {}, 422),
        ("get", "/posts/1/images?limit=abc", {}, 422),
        ("post", "/posts/1/check", {"json": {"image_id": "wolf"}}, 422),
        ("post", "/posts/1/check", {"json": {}}, 422),
        ("post", "/posts/1/check", {"content": b"{not json", "headers": {"content-type": "application/json"}}, 422),
        ("post", "/posts/1/check", {"json": {"image_id": 99999}}, 404),
        ("post", "/posts", {"json": {"slug": "Bad Slug!", "title": "x", "body": "short"}}, 422),
        ("post", "/suggestions/99999/approve", {"json": {}}, 404),
        ("post", "/suggestions/1/approve", {"json": {"reviewer": ""}}, 422),
        ("get", "/images?status=bogus", {}, 422),
        ("get", "/images/99999", {}, 404),
        ("get", "/jobs/99999", {}, 404),
        ("post", "/jobs", {"json": {"kind": "everything"}}, 422),
        ("get", "/costs/records?operation=teleport", {}, 422),
        ("get", "/images", {"headers": {"X-Tenant-ID": "nobody"}}, 404),
        ("get", "/images", {"headers": {"X-Tenant-ID": "BAD TENANT"}}, 422),
    ],
)
def test_bad_input_returns_clean_4xx(client, world, method, path, kwargs, code):
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == code, r.text
    assert "error" in r.json() and r.json()["error"]["code"]


def test_post_that_is_not_analysed_yet_is_409_not_500(client, world):
    r = client.get(f"/posts/{world['pending_post']}/images")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_ready"


def test_duplicate_post_slug_is_409(client, world):
    r = client.post("/posts", json={"slug": "red-fox-behavior", "title": "Foxes", "body": "A post about foxes " * 3})
    assert r.status_code == 409


def test_tenants_are_isolated(client, world):
    other = {"X-Tenant-ID": "other"}
    assert client.get(f"/posts/{world['fox_post']}/images", headers=other).status_code == 404
    assert client.get(f"/images/{world['fox']}", headers=other).status_code == 404
    assert client.get("/images", headers=other).json()["count"] == 0


def test_create_post_queues_a_job(client, world):
    r = client.post("/posts", json={"slug": "arctic-foxes", "title": "Arctic foxes", "body": "White foxes of the tundra " * 3})
    assert r.status_code == 201
    job = client.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["kind"] == "posts" and job["total"] == 1 and job["status"] == "queued"


def test_job_idempotency_key_returns_the_same_job(client, world):
    first = client.post("/jobs", json={"kind": "images"}, headers={"Idempotency-Key": "abc-1"})
    again = client.post("/jobs", json={"kind": "images"}, headers={"Idempotency-Key": "abc-1"})
    assert first.status_code == 202 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert len(client.get("/jobs").json()) == 1


def test_database_outage_is_a_clean_503_not_a_500(monkeypatch):
    """Seen for real when another compose project replaced our db container."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as app_db
    from app.main import create_app

    dead = sessionmaker(bind=create_engine("postgresql+psycopg://u:p@127.0.0.1:1/none", connect_args={"connect_timeout": 1}))

    def override_db():
        s = dead()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[app_db.get_db] = override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/images")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "database_unavailable"


# --- audit regressions: these used to return 500 or give the wrong answer ----------------
@pytest.mark.parametrize(
    "method, path, kwargs",
    [
        ("get", "/images?offset=" + "9" * 101, {}),
        ("get", "/posts?offset=100001", {}),
        ("get", "/suggestions?offset=" + "9" * 30, {}),
        ("get", "/costs/records?offset=" + "9" * 30, {}),
        ("post", "/posts", {"json": {"slug": "nul-title", "title": "Fox\u0000es", "body": "A post body that is long enough."}}),
        ("post", "/suggestions/1/reject", {"json": {"note": "bad\u0000note"}}),
    ],
)
def test_inputs_postgres_cannot_store_are_422_not_500(client, world, method, path, kwargs):
    r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 422, r.text


def test_a_pair_rejected_by_a_reviewer_is_not_suggested_again(client, world):
    first = client.get(f"/posts/{world['fox_post']}/images").json()
    assert first["suggestion"]["filename"] == "fox.jpg"
    client.post(f"/suggestions/{first['suggestion']['suggestion_id']}/reject", json={"note": "wrong fox"})
    again = client.get(f"/posts/{world['fox_post']}/images").json()
    assert again["status"] == "no_confident_match"
    assert any("rejected by a reviewer: fox.jpg" in r for r in again["reasons"])


def test_a_failed_image_is_never_recommended(client, world, sessions):
    with sessions() as s:
        s.get(Image, world["fox"]).status = "failed"
        s.commit()
    body = client.get(f"/posts/{world['fox_post']}/images").json()
    assert "fox.jpg" not in [c["filename"] for c in body["candidates"]]
    assert body["suggestion"] is None or body["suggestion"]["filename"] != "fox.jpg"


def test_an_embedding_that_no_longer_matches_the_tags_is_not_ready(client, world, sessions):
    with sessions() as s:  # tags were re-done but the vector is from the old tags
        s.get(ImageMetadata, world["fox"]).caption = "A different caption after re-tagging."
        s.commit()
    body = client.get(f"/posts/{world['fox_post']}/images").json()
    fox = next(c for c in body["candidates"] if c["filename"] == "fox.jpg")
    assert fox["decision"] == "rejected" and fox["reasons"] == ["Image has not been analysed yet"]


def test_a_zero_vector_in_the_database_does_not_break_matching(client, world, sessions):
    with sessions() as s:
        emb = s.query(ImageEmbedding).filter_by(image_id=world["dog"]).one()
        emb.embedding = [0.0] * DIM
        s.commit()
    r = client.get(f"/posts/{world['fox_post']}/images")
    assert r.status_code == 200
    assert "dog.jpg" not in [c["filename"] for c in r.json()["candidates"]]


def test_post_and_its_job_are_created_together(client, world, monkeypatch):
    from app.services import jobs as jobs_module

    real_create = jobs_module.JobService.create
    calls = {"n": 0}

    def flaky_create(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("queue unavailable")
        return real_create(self, *a, **kw)

    monkeypatch.setattr(jobs_module.JobService, "create", flaky_create)
    body = {"slug": "arctic-foxes", "title": "Arctic foxes", "body": "White foxes of the tundra " * 3}
    assert client.post("/posts", json=body).status_code == 500  # the queue really failed
    retry = client.post("/posts", json=body)  # no orphan post was left behind, so this works
    assert retry.status_code == 201


@pytest.mark.parametrize(
    "installed, ollama",
    [
        (None, "unreachable"),
        (["all-minilm:latest"], "missing models: qwen3-vl:4b"),
        (["qwen3-vl:4b", "all-minilm:latest"], "ok"),
    ],
)
def test_health_reports_degraded_when_ollama_or_a_model_is_missing(client, world, monkeypatch, installed, ollama):
    from app.ai import ollama as ollama_module

    monkeypatch.setattr(ollama_module.OllamaClient, "installed_models", lambda self: installed)
    body = client.get("/health").json()
    assert body["ollama"] == ollama
    assert body["status"] == ("ok" if ollama == "ok" else "degraded")
