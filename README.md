# AI Image Understanding & Content Matching Engine

FlyRank internship capstone (backend track). The service looks at an image library,
works out what is actually in each photo, and picks the right image for each blog post.
A post about red foxes gets a red-fox photo, never the wolf. When no image is good
enough, it says **"no confident match"** and explains why instead of guessing.

Everything runs locally for **$0**: a vision model and an embedding model on
[Ollama](https://ollama.com), Postgres + pgvector in Docker. No API keys, no card.

- **Top-1 precision on the labeled eval set: 0.90 (18/20).** 18/18 = 1.00 when it does
  answer, and 3/3 correct "no confident match" refusals (see [Evaluation](#evaluation))
- 48 Pexels images across animals, vehicles, food, nature + deliberately ambiguous shots
- 23 blog posts, 20 with a labeled correct image, 3 where no image fits

## What it does

1. **Understands images.** A background job sends every image to `qwen3-vl:4b` and gets
   `{subject, category, attributes, caption, confidence}` back. The reply is validated
   against a Pydantic schema; invalid replies are retried with the error fed back and,
   if still invalid, rejected (never stored). Low-confidence or blurry images are flagged
   `needs_review` instead of trusted.
2. **Understands posts.** The same model reads each post and names its subject in common
   words, so "Vulpes vulpes" becomes "red fox".
3. **Matches on meaning.** Image descriptions and post summaries are embedded with
   `all-minilm` into one vector space (pgvector, HNSW index) and ranked by cosine similarity.
4. **Refuses bad matches.** Every candidate goes through the **mismatch guard**:
   classification confidence, category, subject, and a similarity threshold tuned on the
   eval set. Each rejection says why, e.g.
   `Animal category mismatch: expected red fox, detected gray wolf`.
5. **Keeps humans in the loop.** Suggestions are stored and can be approved, rejected
   and inspected through the review API (plus a plain HTML table at `/review`).
6. **Tracks cost.** Every vision, analysis and embedding call writes a `cost_records`
   row (tokens, latency, success). A budget guard stops a job before it goes over.

## Architecture

```
                       +------------------------- worker (python -m app.worker) ------------------------+
 data/images/*.jpg --> | batch job (jobs + job_items in Postgres, retries, heartbeat, idempotent re-run) |
                       |   image -> qwen3-vl:4b -> Pydantic validation -> image_metadata + image_tags  |
                       |            (retry w/ error; low confidence / blur -> needs_review)             |
                       |         -> all-minilm(subject. caption. tags) --------------> image_embeddings |
 posts (seed / API) -> |   post  -> qwen3-vl:4b (text) -> {subject, category, summary} -> posts         |
                       |         -> all-minilm(subject. summary. concepts) ------------> post_embeddings |
                       |   every model call -> budget guard -> cost_records row                          |
                       +-------------------------------------------------------------------------------+
                                                   |
                                        PostgreSQL 16 + pgvector
                                                   |
 GET /posts/{id}/images --> cosine ranking (HNSW) --> mismatch guard --> ranked, explained suggestions
 POST /posts/{id}/check --> mismatch guard on one forced pair           or "no_confident_match" + reasons
 POST /suggestions/{id}/approve|reject, GET /suggestions/{id} --> review log (reviews table)
```

Code is layered; each layer only calls the one below it:

| Layer | Folder | What lives there |
|---|---|---|
| HTTP | `app/api/` | FastAPI routes, request validation, status codes |
| Logic | `app/services/` | vision + post analysis, embeddings, **guard** (`guard.py`, pure functions), matching, jobs, costs, review |
| Data | `app/repositories/` | every SQL query, all scoped by tenant |
| AI client | `app/ai/ollama.py` | thin HTTP client; returns text + token counts, never judges validity |
| Schema | `alembic/versions/` | three migrations with the unique constraints and indexes |

The design doc is in [docs/design.md](docs/design.md).

## Run it

Prerequisites: Docker (with Compose) and [Ollama](https://ollama.com/download) running on
the host. The app never needs a GPU; on CPU each model call takes roughly 2-8 minutes.

```bash
ollama pull qwen3-vl:4b
ollama pull all-minilm
cp .env.example .env            # then change POSTGRES_PASSWORD
docker compose up -d --build    # db, migrations, api on :8000, worker
```

Seed the demo data (downloads the 48 images from Pexels, registers images and posts,
queues one batch job, and waits for it):

```bash
docker compose exec api python -m scripts.seed --wait
```

The seed is safe to re-run: images are not duplicated and the same seed returns the same
job. On a 16 GB CPU-only laptop the full batch (48 images + 23 posts) took about 6.4
hours of model time: ≈4.3 min per image and ≈7 min per post including retries (numbers
from `GET /costs`). Leave it running; progress survives worker restarts.
Follow progress with `curl localhost:8000/jobs/1` or `docker compose logs -f worker`.

Then try it (interactive docs at http://localhost:8000/docs):

```bash
curl localhost:8000/posts/1/images                                   # red fox post: ranked + explained
curl -X POST localhost:8000/posts/1/check -H "content-type: application/json" -d '{"image_id": 6}'   # force the wolf
curl localhost:8000/posts/21/images                                  # parrot post: no confident match
curl "localhost:8000/images?needs_review=true"                       # low-confidence images
curl localhost:8000/costs                                            # cost summary + budget
docker compose exec api python -m scripts.eval                       # top-1 precision
docker compose exec api pytest -q                                    # test suite
```

All requests use the `demo` tenant unless you send an `X-Tenant-ID` header.

The Compose project is pinned to `name: flyrank-imagematch`, so other checkouts of a
folder with the same name can't replace these containers (that happened during
development; see BUILDLOG).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | database and Ollama reachability |
| GET | `/images`, `/images/{id}` | tags, confidence, review flags (filters: `status`, `needs_review`, `category`) |
| POST | `/jobs` | queue a batch job (`ingest`, `images`, `posts`; `force`); `Idempotency-Key` header supported |
| GET | `/jobs`, `/jobs/{id}` | progress, status, failed items with their last error |
| POST | `/posts` | create a post (queues its analysis job) |
| GET | `/posts`, `/posts/{id}` | posts with their analysed subject/category/summary |
| GET | `/posts/{id}/images` | ranked candidates, each with guard checks + explanation; `suggestion` or `no_confident_match` + `reasons` |
| POST | `/posts/{id}/check` | force-check one image against a post |
| GET | `/suggestions`, `/suggestions/{id}` | review queue / inspect why (checks, tags, review history) |
| POST | `/suggestions/{id}/approve`, `/reject` | idempotent review decisions (repeat = no-op, flip = 409) |
| GET | `/review` | HTML review table |
| GET | `/costs`, `/costs/records` | cost summary and budget / one row per AI call |

Bad input gets a JSON error with a 4xx status (422 invalid input, 404 unknown id or
tenant, 409 conflict or not ready yet), never a 500. If the database itself is down,
the API answers 503 with `Retry-After`. This is covered by
`tests/test_matching_api.py::test_bad_input_returns_clean_4xx` (19 cases).

## The mismatch guard

`app/services/guard.py`. All checks run so a rejection lists every reason:

| Check | Rejects when |
|---|---|
| ready | the image has no validated tags or embedding |
| confidence | model confidence < 0.60, or the image is flagged `needs_review` |
| category | post category != image category |
| subject | the image doesn't show the post's subject: different head noun ("fox" vs "wolf"), subject phrase not in the image description, and subject embeddings below 0.80 |
| similarity | cosine(post, image) < `SIMILARITY_THRESHOLD` (0.50, tuned on the eval set) |

The 0.80 subject threshold comes from measured `all-minilm` scores: wrong-subject pairs
top out at 0.68 (bicycle vs motorcycle), "red fox" vs "gray wolf" is 0.53, while true
synonyms score 0.81-0.92 (bike, motorbike, burger, steam train).

## Evaluation

`eval/eval_set.json` labels 23 posts: 20 with the images a human would accept, and 3
(parrot, chocolate cake, sailing) where nothing in the corpus fits.
`scripts/eval.py` queries the live API and reports:

| Metric | Result |
|---|---|
| **Top-1 precision** (20 posts with a correct image) | **18/20 = 0.90** |
| Precision when it answers | 18/18 = 1.00 |
| Correct "no confident match" (3 posts with no fitting image) | 3/3 |
| Overall decision accuracy (23 posts) | 21/23 = 0.91 |
| "Vulpes vulpes" post / "Canis lupus" post | fox / wolf, both correct |

The two misses are refusals, not wrong images: post analysis named the subject of
"How deer grow and shed their antlers" as `stag antlers` (category `object`) and of
"Winter hiking among snowy peaks" as `hiker` (category `person`). The ranking put the
right image first in both cases, but the guard refused on the category mismatch. It
said "no confident match" instead of guessing.

**Top-1 precision** = posts whose suggested image is a labeled correct one / posts that
have a correct image. A "no confident match" on such a post counts as a miss.

Threshold tuning: `python -m scripts.eval --sweep` re-applies the guard at thresholds
0.20-0.80 to the same candidates. Top-1 precision stays at 0.90 from 0.20 up to 0.50 and falls
after that (0.80 at 0.55, 0.60 at 0.60), so **0.50** is the highest threshold that keeps
every correct match. The weakest correct suggestion scores 0.541; nothing on the three
no-match posts scores above 0.28. Similarity alone can't separate right from wrong:
a fallow deer scores 0.557 on the "Vulpes vulpes" post, above that weakest correct
match. The subject and confidence checks are what stop it; the threshold is a safety floor.

## Tests

`docker compose exec api pytest -q` (or `pytest -q` from a venv with the stack running).
83 tests (full `pytest -v` output is in EVIDENCE.md):

- `tests/test_schema_validation.py`: schema accepts/rejects vision output, retry with
  the error fed back, invalid output never returned, budget guard, low-confidence flag,
  blur detection.
- `tests/test_guard.py`: wolf-on-fox rejected with the category-mismatch reason, dog
  rejected, flagged images never recommended, subject matching, "no confident match" reasons.
- `tests/test_matching_api.py` and `tests/test_jobs.py`: against a real Postgres +
  pgvector test database. Ranking order, force-check, no-match, review idempotency, 19
  bad-input cases, tenant isolation, job retries, failure status + ALERT, idempotent
  re-runs with zero AI calls, cost rows per call, budget stop.

## Cost tracking

Local Ollama costs nothing, so `actual_cost_usd` is always 0. To make the budget guard
meaningful, each call also gets a `notional_cost_usd`: its real token counts priced at
configurable reference rates (`NOTIONAL_USD_PER_1M_*` in `.env`). The guard refuses the
next call when the tenant's notional total reaches `AI_BUDGET_USD`, or when a job hits
`AI_MAX_CALLS_PER_JOB`. Failed and invalid calls are recorded too.

## Limitations

- **Slow on CPU.** `qwen3-vl:4b` is a "thinking" model and Ollama ignores `think: false`
  for it, so every call writes 300-4,000 hidden reasoning tokens first: ~4 min per image,
  ~7 min per post on my CPU. Fine for a 48-image batch job; not for real-time tagging.
- **Post analysis is the weak link.** Both eval misses come from the model naming an
  odd subject for a post ("stag antlers", "hiker"). The guard then refuses safely, but a
  correct image is missed. A better prompt would likely fix it; I did not re-tune on the
  eval set to chase those two.
- **Small eval set, tuned on itself.** 23 posts is enough to catch fox/wolf mistakes but
  the threshold was tuned on the same posts it is scored on, so the precision number is
  optimistic. A held-out set would be the next step.
- **The model's confidence is not calibrated.** In a test it labelled the blurred fox
  `category: vehicle` with confidence 0.8. That is why blur is also measured locally
  (Laplacian variance) and why the guard requires category and subject agreement,
  not just confidence.
- **Subject matching is English and head-noun based.** "sea lion" vs "lion" would match
  on the head noun; multilingual posts are not handled.
- **Long calls need long timeouts.** A single post analysis reached 4,014 reasoning
  tokens (14 minutes). `OLLAMA_NUM_CTX=8192` and `OLLAMA_TIMEOUT_S=1800` are sized for
  that; the stale-job threshold (2,400 s) must stay above the timeout.
- **Ollama runs on the host,** not in Compose, so a fresh machine needs Ollama installed
  and the two models pulled (about 3.4 GB).
- **Tenancy is by header only.** There is no authentication; this is an internal tool.

## Repository map

```
app/            FastAPI app, services, repositories, worker
alembic/        migrations 0001-0003
data/           manifest.csv (source URL, photographer, license) + posts.json; images are downloaded, not committed
docs/design.md  phase-1 design
eval/           eval_set.json (labels); results/ is gitignored
scripts/        download_images.py, seed.py, eval.py
tests/          pytest suite
EVIDENCE.md     pasted proof for every requirement and probe
BUILDLOG.md     how AI was used, where it was wrong, what was changed
```

Images: Pexels photos under the [Pexels License](https://www.pexels.com/license/);
photographers are credited in `data/manifest.csv`. Code: MIT, see [LICENSE](LICENSE).
