# Design: AI Image Understanding & Content Matching Engine

One-page design, written before the build (Phase 1 gate). Numbers marked *tuned* were
set later using the eval set; the rules themselves are unchanged.

## 1. Problem

A blog has posts and an image library. Editors need the right image for each post: a
red-fox article must get a red-fox photo, never the wolf. Filenames and keywords are not
enough (a post may say "Vulpes vulpes" and never "fox"). The system must understand
what is *in* each image, match on meaning, and refuse when no image is good enough,
with an explanation a human can check.

Avoiding a wrong match matters more than always finding a match.

## 2. Architecture and layers

```
                     +-------------------- worker process (background) --------------------+
 images on disk ---> | vision model (qwen3-vl:4b) -> schema validation -> image_metadata    |
 (data/images)       |        | retries, cost_records row per call, budget guard           |
                     |        +-> embed(subject + caption) (all-minilm) -> image_embeddings |
 posts (API/seed) -> | post analysis (same model, text only) -> embed -> post_embeddings   |
                     +---------------------------------------------------------------------+
                                           |  Postgres + pgvector
 GET /posts/{id}/images  --> ranking (cosine, HNSW index) --> mismatch guard --> ranked,
                                                                                 explained
 POST /suggestions/{id}/approve|reject  --> review log                           suggestions
```

Code layers (each layer only calls the one below it):

| Layer | Package | Responsibility |
|---|---|---|
| HTTP | `app/api/` | FastAPI routes, request/response schemas, status codes. No SQL, no AI calls. |
| Logic | `app/services/` | Vision pipeline, embeddings, matching, **guard**, jobs, costs/budget, review. |
| Data | `app/repositories/` | All SQLAlchemy queries. Every query is scoped by `tenant_id`. |
| AI client | `app/ai/` | Thin Ollama HTTP client. Returns text + token counts; knows nothing about schemas. |

The guard (`app/services/guard.py`) is a pure function with no I/O, so it is unit-tested
on its own.

## 3. Image metadata schema (vision output contract)

```json
{
  "subject": "red fox",
  "category": "animal",
  "attributes": ["orange fur", "wild", "forest"],
  "caption": "A red fox standing in a forest",
  "confidence": 0.94
}
```

| Field | Rule |
|---|---|
| `subject` | 1-60 chars, most specific common name (species level for animals) |
| `category` | enum: `animal, vehicle, food, nature, person, object, other` |
| `attributes` | 1-10 short strings, each 1-40 chars |
| `caption` | 5-300 chars, one sentence |
| `confidence` | number in [0, 1] |

The same schema is sent to Ollama as the `format` JSON schema and enforced again with
Pydantic `model_validate_json`. A response that fails validation is retried with the
validation error fed back to the model; after the retry limit the image is marked
`failed` and no metadata is stored. Invalid output is never written.

**Low confidence.** An image gets `needs_review = true` (with reasons) when
`confidence < MIN_CONFIDENCE` (0.60), when a local sharpness measure (variance of
edges) is below `BLUR_THRESHOLD`, or when the subject is "unknown/unclear". Flagged
images keep their tags for humans to inspect, but the guard never recommends them.

Post analysis uses the same approach: `{subject, category, concepts[], summary, confidence}`,
where `subject` is the common English name (so "Vulpes vulpes" becomes "red fox").

## 4. Data model (Postgres 16 + pgvector, Alembic migrations)

| Table | Key columns | Constraints / indexes |
|---|---|---|
| `tenants` | id, slug | unique(slug) |
| `images` | tenant_id, filename, sha256, status, source_url, photographer, license | unique(tenant_id, filename); index(tenant_id, status) |
| `image_metadata` | image_id, subject, category, attributes, caption, confidence, needs_review, review_reasons, sharpness, model, prompt_version | unique(image_id); index(category) |
| `image_tags` | image_id, tag, kind (subject/attribute/category) | unique(image_id, tag, kind); index(tag) |
| `image_embeddings` | image_id, embedding vector(384), subject_embedding vector(384), text, model | unique(image_id); HNSW index (cosine) |
| `posts` | tenant_id, slug, title, body, status, subject, category, concepts, summary | unique(tenant_id, slug) |
| `post_embeddings` | post_id, embedding, subject_embedding, text, model | unique(post_id) |
| `suggestions` | post_id, image_id, rank, similarity, decision, reasons, checks, review_status | unique(post_id, image_id); index(post_id, rank); index(tenant_id, review_status) |
| `reviews` | suggestion_id, action, note, reviewer | index(suggestion_id) - the approve/reject log |
| `jobs` | tenant_id, kind, status, idempotency_key, total, processed, succeeded, failed, error | unique(tenant_id, idempotency_key); index(status, id) |
| `job_items` | job_id, target_type, target_id, status, attempts, last_error | unique(job_id, target_type, target_id); index(job_id, status) |
| `cost_records` | tenant_id, job_id, operation, model, input/output tokens, duration_ms, success, notional_cost_usd, actual_cost_usd | index(tenant_id, created_at); index(job_id); index(operation) |

## 5. Matching strategy

1. **Text for embedding.** Image: `subject. caption. attributes`. Post: the analysed
   common-name `subject` + `summary` + title. Both go through `all-minilm` (384 dims)
   into one shared space. A quick test showed why post analysis is needed:
   `all-minilm` alone scores "Vulpes vulpes" vs "red fox" at 0.26, the same as vs
   "gray wolf".
2. **Ranking.** Cosine similarity between post and image vectors (`<=>` on an HNSW
   index), highest first.
3. **Guard** on every ranked candidate. The suggestion is the highest-ranked candidate
   the guard accepts; if none, the answer is `no_confident_match` plus the reasons.

## 6. Guard rules

All rules are evaluated (not short-circuited) so the explanation lists every failure.

| # | Check | Rejects when | Example reason |
|---|---|---|---|
| 1 | ready | image has no valid metadata/embedding | "Image has not been analysed yet" |
| 2 | confidence | `confidence < MIN_CONFIDENCE` or image flagged `needs_review` | "Low classification confidence 0.35 < 0.60; image is flagged for review" |
| 3 | category | post category != image category | "Category mismatch: post is about food, image shows animal" |
| 4 | subject | subjects don't match (see below) | "Animal category mismatch: expected red fox, detected gray wolf" |
| 5 | similarity | cosine < `SIMILARITY_THRESHOLD` (*tuned*: 0.50) | "Similarity 0.37 is below the threshold 0.50" |

**Subject match** = same head noun ("red fox" / "fox"), or the post subject appears in
the image's subject/caption/attributes, or cosine of the two subject embeddings is
at least `SUBJECT_SIM_THRESHOLD`. "red fox" vs "gray wolf" fails all three.

## 7. Background jobs, cost, idempotency

- `POST /jobs` (with optional `Idempotency-Key`) inserts a job and one `job_item` per
  image/post. A separate **worker** process claims jobs with
  `SELECT ... FOR UPDATE SKIP LOCKED`, processes items one by one, and updates progress.
- Each item is retried up to `JOB_MAX_ATTEMPTS` with exponential backoff. An item that
  still fails is marked `failed`; the job ends `failed` with a summary and an `ALERT`
  log line. A worker that dies mid-job is recovered by a heartbeat timeout.
- Re-runs are idempotent: the same `Idempotency-Key` returns the same job, and items whose
  image already has metadata from the same model + prompt version + file hash are
  `skipped` without an AI call (unless `force=true`).
- Every vision / analysis / embedding call writes a `cost_records` row (tokens, latency,
  success). Actual cost is $0 (local Ollama); a notional cost at configurable reference
  rates feeds a **budget guard** that stops a job before it exceeds `AI_BUDGET_USD`.

## 8. API surface (all JSON, tenant from `X-Tenant-ID`, default `demo`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | DB + Ollama reachability |
| GET | `/images`, `/images/{id}` | list (filter `status`, `needs_review`, `category`) / detail with tags |
| POST/GET | `/posts`, `/posts/{id}` | create (queues analysis job) / read |
| GET | `/posts/{id}/images` | ranked, explained suggestions or `no_confident_match` |
| POST | `/posts/{id}/check` | force-check one image against a post (guard verdict) |
| POST/GET | `/jobs`, `/jobs/{id}` | start batch job / progress + failed items |
| GET | `/suggestions`, `/suggestions/{id}` | review queue / inspect why |
| POST | `/suggestions/{id}/approve`, `/reject` | review decisions (idempotent) |
| GET | `/costs`, `/costs/records` | cost summary + budget / per-call log |

Bad input returns 4xx (422 validation, 404 unknown id/tenant, 409 conflict) with a JSON
error body, never a 500.

## 9. Non-goals

- **No image upload or web UI.** Images come from the manifest + download script;
  review is done through API endpoints. (A frontend is explicitly out of scope.)
- Not comparing vision/embedding models; one of each.
- No auth beyond tenant scoping; this is a single-team internal tool.

## 10. Dataset

48 Pexels images (Pexels License) in `data/manifest.csv`: animals (red fox, gray wolf,
coyote, dog, deer, brown bear), vehicles, food, nature, and ambiguous images (abstract
bokeh, a heavily blurred fox, a motion-blurred dog in the dark) to exercise the
low-confidence flag. The images themselves are not committed;
`scripts/download_images.py` rebuilds them. The pipeline never sees filenames, only
pixels.
