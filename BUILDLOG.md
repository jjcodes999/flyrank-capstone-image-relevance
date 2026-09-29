# BUILDLOG

How I used AI on this project, phase by phase. I built it with Claude Code (an AI coding
agent) doing most of the typing; I set the requirements, stack and constraints, and I
review and own every line. Entries are short and honest, including the AI's mistakes.

## Phase 1 - Design and dataset

- **AI generated:** the first draft of `docs/design.md`, the image picks in
  `data/manifest.csv` (it browsed Pexels search pages and read photo IDs, descriptions
  and photographer names from the page data), and `scripts/download_images.py`.
- **Where it was wrong:**
  - The download script reported "48 downloaded, 1 failed" for 48 images. The "failure"
    was a `print()` crashing on the photographer name "Vaičiulėnas" (Windows console is
    cp1252) *after* the file had been saved. Fixed by switching stdout to UTF-8; a rerun
    now reports `1 downloaded, 47 already present, 0 failed`.
  - The model download command ended with `echo exit=$?`, which reported success even
    though `ollama pull qwen3-vl:4b` had failed with a TLS timeout. It was caught by
    `ollama list`, and the pull was retried in a loop.
- **What I checked / decided:**
  - Stack and constraints are mine: Python/FastAPI, Postgres + pgvector, local Ollama
    (`qwen3-vl:4b` for vision, `all-minilm` for embeddings), $0, no paid APIs.
  - Before designing matching, the AI measured `all-minilm` directly: "Vulpes vulpes"
    vs "red fox" = 0.26, vs "gray wolf" = 0.26, vs "coyote" = 0.34. So plain embeddings
    **cannot** do the scientific-name match. The decision: add a post-analysis step
    that turns each post into a common-name subject before embedding.
  - Corpus checked on a contact sheet: 48 images, and all the ambiguous ones really
    are ambiguous (bokeh, blurred fox, dark motion-blurred dog).
  - Filenames like `fox_01.jpg` are only for humans. The pipeline sends pixels only,
    never the filename, so the model can't cheat.

## Phase 2 - Image understanding pipeline

- **AI generated:** config, ORM models and migration 0001, the Ollama client, the
  structured-output loop (`app/services/structured.py`), the DB-backed job runner and
  worker, per-call cost tracking with the budget guard, the images/jobs/costs endpoints,
  Docker Compose, the seed script, and the schema/retry tests.
- **Where it was wrong:**
  - The API crashed on startup with `TypeError: 'function' object is not subscriptable`:
    a repository method named `list` shadowed the builtin inside the class body, so
    `-> list[int]` broke. Fixed with `from __future__ import annotations`.
  - Compose read `OLLAMA_BASE_URL=http://localhost:11434` from `.env` and would have
    passed it into the containers, where localhost is the container itself. Split into
    `OLLAMA_BASE_URL` (host scripts) and `OLLAMA_DOCKER_URL` (containers).
  - It first assumed `think: false` would make `qwen3-vl:4b` fast. Measured: Ollama
    ignores it for this model and every call writes ~300-1,800 hidden thinking tokens
    (~2-4 min per call on my CPU).
  - One generated helper (`job_out`) contained a meaningless `... if False else None`
    line. I removed it in review.
- **What I checked / decided:**
  - I kept `qwen3-vl:4b` anyway (it is the model I chose, and the thinking made its
    confidence better calibrated: 0.3 on both deliberately ambiguous images) and
    designed around it: all AI work runs in the background worker, never in a request.
  - In a test call the model tagged the blurred fox as `category: vehicle` with confidence
    0.8, so model confidence alone can't be trusted. I added a local blur measure
    (Laplacian variance). On the corpus the two blurred images score 2.2 and 4.9 and
    everything else is 35 or more, so `BLUR_THRESHOLD=15`.
  - Cost rows are written in their own short transaction so a failed item's rollback
    can't erase the record of a call that really happened. Failed and invalid calls are
    costed too.
  - Real local cost is $0, so the budget guard enforces a *notional* cost (real token
    counts × configurable reference rates) and a max-calls-per-job cap.

## Phase 3 - Matching engine and mismatch guard

- **AI generated:** migration 0002 (pgvector + HNSW index), embedding and post-analysis
  services, the guard (`app/services/guard.py`) and its tests, the matching service,
  posts/force-check endpoints, the 23 blog posts and the eval labels.
- **Where it was wrong:**
  - The first worker ignored SIGTERM until the *whole* job finished, so a restart killed
    it mid-item. I added a graceful stop (finish the current item, requeue the job) and
    a heartbeat per item. The killed job 1 was left `running` and is recovered by the
    heartbeat timeout, the same path a crashed worker would take.
  - If the embedding call failed after a 3-minute vision call, the rollback would throw
    the tags away. Now the tags are committed first, and a retry resumes at the embedding.
  - An integration test showed the guard *accepting* the wolf for the fox post. The
    test's fake subject vectors sat exactly on the 0.80 subject threshold. Before
    trusting 0.80 I had the real scores measured: wrong-subject pairs max out at 0.68
    (bicycle/motorcycle), red fox vs gray wolf = 0.53, true synonyms 0.81-0.92. So 0.80
    stays, backed by data, and the test now uses realistic vectors.
  - Alembic's `fileConfig()` disabled the app's loggers when migrations ran inside
    pytest, so the job-failure `ALERT` line silently disappeared. Fixed with
    `disable_existing_loggers=False`.
- **What I checked / decided:**
  - The "Vulpes vulpes" post is analysed as subject `red fox` with a summary about
    "red foxes". Concept matching comes from the post-analysis step, not from the
    embedding model alone (see Phase 1).
  - Items run posts-first because text-only calls are cheaper, so matching can be tried
    while images are still being tagged.
  - `GET /posts/{id}/images` also stores its verdicts as suggestions (upsert, safe to
    repeat) so they can be reviewed. I accepted a GET with a side effect as the price of
    a simple review flow.

## Phase 4 - Production layer (review API, eval, docs)

- **AI generated:** migration 0003 (reviews), the review service and endpoints, the HTML
  review table, `scripts/eval.py` (with the threshold sweep), `scripts/probes.py`, the
  API/job integration tests, README, capstone.yaml and EVIDENCE.md.
- **Where it was wrong (found by the real batch run, not by tests):**
  - Post 7 ("deer antlers") came back **empty** after 652 s: 236 prompt + 3,860 hidden
    reasoning tokens = 4,096, exactly Ollama's default context window, so the model
    ran out of room before writing any JSON. The validator correctly refused it
    (`Invalid JSON: EOF while parsing`) and recorded a failed cost row, but the retry
    would have hit the same wall. Fix: `num_ctx=8192` (configurable), plus detecting
    `done_reason == "length"` so the error says "cut off at the context limit" instead
    of a confusing JSON error.
  - Killing the worker mid-call to apply that fix exposed a gap: the interrupted call
    left **no** cost row, because rows were written only after the reply. Now the row is
    written before the call and completed after it, so a crash leaves an attributed row
    marked "no reply recorded". There's a test that simulates exactly that.
- **What I checked / decided:**
  - Crash recovery and graceful shutdown were exercised on the real run, not only in
    tests: `requeued stale jobs [1] (worker heartbeat lost)` after a kill, and
    `job 1 requeued for shutdown; 4 item(s) already processed` after a normal stop.
