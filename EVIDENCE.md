# EVIDENCE

Real command output from this machine (Windows 11, 16 GB RAM, CPU only, Docker Desktop,
Ollama 0.34.4), captured on 2026-09-29 against the running stack
(`docker compose up -d --build` + `python -m scripts.seed`). Nothing below is edited
except long outputs cut where marked `...`. Times in logs are UTC.

Jump to: [Acceptance probes](#acceptance-probes-section-13-layer-2) ·
[Section 6 checklist](#section-6-requirements-one-proof-per-box) ·
[Shared requirements](#section-13-shared-requirements) ·
[Test suite](#test-suite) · [Clean machine](#clean-machine-run)

---

## Acceptance probes (Section 13, layer 2)

All six probes are scripted in `scripts/probes.py` and run with one command. This is its
complete output:

```
$ docker compose exec api python -m scripts.probes
==============================================================================
PROBE 1: batch job tags every image with schema-valid output; low confidence is flagged
==============================================================================
job 2 kind=ingest status=succeeded processed=71/71 (done=26 skipped=45 failed=0)
job 1 kind=images status=succeeded processed=48/48 (done=48 skipped=0 failed=0)
image status counts: {'needs_review': 3, 'tagged': 45}
images whose stored tags re-validate against the VisionTags schema: 48/48
flagged needs_review (not trusted):
  dog_04.jpg         subject='dog'                    conf=0.30 reasons=['model confidence 0.30 is below the 0.60 minimum']
  ambiguous_01.jpg   subject='unknown'                conf=0.20 reasons=['model confidence 0.20 is below the 0.60 minimum', 'image looks blurry (sharpness 4.9 < 15.0)', "model could not identify the subject ('unknown')"]
  ambiguous_02.jpg   subject='red fox'                conf=0.30 reasons=['model confidence 0.30 is below the 0.60 minimum', 'image looks blurry (sharpness 2.2 < 15.0)']

==============================================================================
PROBE 2: red fox article -> fox ranks first; wolf and dog rank clearly lower
==============================================================================
post 1 'The behavior of red foxes' (analysed subject: red fox) -> status=match
suggestion: fox_05.jpg
rank image              subject                    sim  decision
   1 fox_05.jpg         red fox                   0.63  accepted
   2 fox_03.jpg         red fox                   0.61  accepted
   3 fox_02.jpg         red fox                   0.61  accepted
   4 fox_04.jpg         red fox                   0.55  accepted
   5 ambiguous_02.jpg   red fox                   0.55  rejected
   6 fox_01.jpg         red fox                   0.49  rejected
   7 deer_02.jpg        fallow deer               0.47  rejected
   8 deer_01.jpg        red deer                  0.47  rejected
   9 wolf_01.jpg        gray wolf                 0.37  rejected
  11 wolf_04.jpg        gray wolf                 0.36  rejected
  12 coyote_01.jpg      coyote                    0.36  rejected
  13 wolf_02.jpg        gray wolf                 0.36  rejected
  14 coyote_02.jpg      coyote                    0.35  rejected
  15 wolf_03.jpg        gray wolf                 0.35  rejected
  18 coyote_03.jpg      coyote                    0.32  rejected
  19 dog_04.jpg         dog                       0.30  rejected
  22 dog_03.jpg         siberian husky            0.22  rejected
  24 dog_02.jpg         border collie             0.19  rejected
  26 dog_01.jpg         golden retriever          0.16  rejected

==============================================================================
PROBE 3: force the wolf as the candidate for the fox post -> rejected, category mismatch
==============================================================================
POST /posts/1/check {"image_id": 6}  (wolf_01.jpg) -> HTTP 200
{
  "filename": "wolf_01.jpg",
  "subject": "gray wolf",
  "similarity": 0.3717,
  "decision": "rejected",
  "reasons": [
    "Animal category mismatch: expected red fox, detected gray wolf",
    "Similarity 0.37 is below the threshold 0.50"
  ],
  "explanation": "Rejected: Animal category mismatch: expected red fox, detected gray wolf; Similarity 0.37 is below the threshold 0.50"
}

==============================================================================
PROBE 4: post with no suitable image -> 'no confident match' + reasons
==============================================================================
post 21 'How to care for a pet parrot' (subject: parrot) -> status=no_confident_match
    - Similarity below threshold: the best candidate ('golden retriever') scores 0.27 < 0.50
    - Subjects don't match: no candidate shows 'parrot' (closest: golden retriever, desert, red fox, fallow deer)
post 22 'Baking the perfect chocolate cake' (subject: chocolate layer cake) -> status=no_confident_match
    - Similarity below threshold: the best candidate ('mountain') scores 0.28 < 0.50
    - Subjects don't match: no candidate shows 'chocolate layer cake' (closest: mountain, maki sushi, fried chicken burger, steam locomotive)
post 23 'Learning to sail a small boat' (subject: dinghy) -> status=no_confident_match
    - Similarity below threshold: the best candidate ('bicycle') scores 0.27 < 0.50
    - Subjects don't match: no candidate shows 'dinghy' (closest: bicycle, coyote, red fox, fallow deer)

==============================================================================
PROBE 5: eval script -> top-1 precision on the labeled set
==============================================================================
Eval set: 23 posts (20 with a correct image, 3 where no image fits)
Similarity threshold in use: 0.5

post                         expected               suggested            sim  result
red-fox-behavior             fox_*                  fox_05.jpg          0.63  OK
vulpes-vulpes-field-notes    fox_*                  fox_05.jpg          0.64  OK
gray-wolf-packs              wolf_*                 wolf_02.jpg         0.66  OK
canis-lupus-returns          wolf_*                 wolf_03.jpg         0.64  OK
urban-coyotes                coyote_*               coyote_03.jpg       0.67  OK
golden-retriever-care        dog_01.jpg             dog_01.jpg          0.54  OK
deer-antlers                 deer_*                 no_confident_match        MISS
                              #1 deer_01.jpg      sim=0.39 rejected: Category mismatch: post is about object, image shows animal; Similarity 0.39 is below the threshold 0.50
                              #2 deer_03.jpg      sim=0.36 rejected: Category mismatch: post is about object, image shows animal; Similarity 0.36 is below the threshold 0.50
                              #3 deer_02.jpg      sim=0.34 rejected: Category mismatch: post is about object, image shows animal; Similarity 0.34 is below the threshold 0.50
                              reasons: Similarity below threshold: the best candidate ('red deer') scores 0.39 < 0.50 | Subjects don't match: no candidate shows 'stag antlers' (closest: red deer, sika deer, fallow deer, red fox)
brown-bear-hibernation       bear_*                 bear_03.jpg         0.62  OK
volkswagen-beetle-history    car_01.jpg             car_01.jpg          0.54  OK
bicycle-commuting            bicycle_*              bicycle_02.jpg      0.56  OK
neapolitan-pizza             pizza_*                pizza_01.jpg        0.58  OK
sushi-at-home                sushi_*                sushi_02.jpg        0.77  OK
great-burgers                burger_*               burger_02.jpg       0.68  OK
better-salads                salad_*                salad_01.jpg        0.72  OK
steam-railways               train_*                train_02.jpg        0.79  OK
motorcycle-touring           motorcycle_*           motorcycle_02.jpg   0.58  OK
winter-mountain-hiking       mountain_*             no_confident_match        MISS
                              #1 mountain_02.jpg  sim=0.43 rejected: Category mismatch: post is about person, image shows nature; Similarity 0.43 is below the threshold 0.50
                              #2 mountain_01.jpg  sim=0.37 rejected: Category mismatch: post is about person, image shows nature; Similarity 0.37 is below the threshold 0.50
                              #3 fox_04.jpg       sim=0.29 rejected: Category mismatch: post is about person, image shows animal; Similarity 0.29 is below the threshold 0.50
                              reasons: Similarity below threshold: the best candidate ('mountain') scores 0.43 < 0.50 | Subjects don't match: no candidate shows 'hiker' (closest: mountain, red fox, waterfall, motorcycle)
tropical-beach-holiday       beach_*                beach_02.jpg        0.70  OK
sahara-sand-dunes            desert_*               desert_01.jpg       0.72  OK
waterfall-photography        waterfall_*            waterfall_02.jpg    0.58  OK
pet-parrot-care              no match               no_confident_match        OK
chocolate-cake               no match               no_confident_match        OK
learning-to-sail             no match               no_confident_match        OK

Top-1 precision: 18/20 = 0.90
Precision when it answers: 18/18 = 1.00
Correct 'no confident match': 3/3
Overall decision accuracy: 0.91

full results written to eval/results/latest.json

==============================================================================
PROBE 6: cost log -> every vision/embedding call attributed with a cost entry
==============================================================================
{
  "total_calls": 145,
  "notional_cost_usd": "0.04705588",
  "actual_cost_usd": "0E-8",
  "budget_usd": "1.0",
  "budget_remaining_usd": "0.95294412",
  "note": "Local Ollama: actual cost is $0. Notional cost prices the same tokens at the reference rates in .env and is what the budget guard enforces.",
  "by_operation": [
    {
      "operation": "embed",
      "model": "all-minilm",
      "calls": 71,
      "failed_calls": 0,
      "input_tokens": 2959,
      "output_tokens": 0,
      "duration_ms": 24226,
      "notional_cost_usd": "0.00005918",
      "actual_cost_usd": "0E-8"
    },
    {
      "operation": "post_analysis",
      "model": "qwen3-vl:4b",
      "calls": 26,
      "failed_calls": 3,
      "input_tokens": 5551,
      "output_tokens": 58097,
      "duration_ms": 10610603,
      "notional_cost_usd": "0.02379390",
      "actual_cost_usd": "0E-8"
    },
    {
      "operation": "vision_tag",
      "model": "qwen3-vl:4b",
      "calls": 48,
      "failed_calls": 0,
      "input_tokens": 60140,
      "output_tokens": 42972,
      "duration_ms": 12420460,
      "notional_cost_usd": "0.02320280",
      "actual_cost_usd": "0E-8"
    }
  ]
}
tagged images with both a vision_tag and an embed cost row: 48/48
ready posts with both a post_analysis and an embed cost row: 23/23
latest cost records:
  #145 job=2 embed         image:3 model=all-minilm in=38 out=0 ms=50 ok=True notional=$0.000001 actual=$0.00
  #144 job=2 embed         image:2 model=all-minilm in=39 out=0 ms=57 ok=True notional=$0.000001 actual=$0.00
  #143 job=2 embed         image:1 model=all-minilm in=32 out=0 ms=54 ok=True notional=$0.000001 actual=$0.00
```

Probe 5 before and after tuning, with the threshold sweep used to choose 0.50:

```
$ docker compose exec api python -m scripts.eval --sweep     # run with the old threshold 0.45
...
Top-1 precision: 18/20 = 0.90
Precision when it answers: 18/18 = 1.00
Correct 'no confident match': 3/3
Overall decision accuracy: 0.91

Threshold sweep (guard re-applied offline to the same candidates):
threshold   top1 answered refusals  overall
     0.20   0.90       18     3/3     0.91
     0.25   0.90       18     3/3     0.91
     0.30   0.90       18     3/3     0.91
     0.35   0.90       18     3/3     0.91
     0.40   0.90       18     3/3     0.91
     0.45   0.90       18     3/3     0.91
     0.50   0.90       18     3/3     0.91
     0.55   0.80       16     3/3     0.83
     0.60   0.60       12     3/3     0.65
     0.65   0.40        8     3/3     0.48
     0.70   0.20        4     3/3     0.30
     0.75   0.10        2     3/3     0.22
     0.80   0.00        0     3/3     0.13
```

Why 0.50: it is the highest threshold that keeps every correct match (the sweep is flat
from 0.20 to 0.50, then drops). The numbers behind it:

```
$ python - < eval/results/latest.json analysis
weakest correct suggestion (accepted, top-1 per post):
   0.541  golden-retriever-care -> dog_01.jpg
   0.543  volkswagen-beetle-history -> car_01.jpg
   0.562  bicycle-commuting -> bicycle_02.jpg
strongest WRONG candidates (image not labeled correct for that post):
   0.611  vulpes-vulpes-field-notes -> ambiguous_02.jpg (red fox)
   0.557  vulpes-vulpes-field-notes -> deer_02.jpg (fallow deer)
   0.554  red-fox-behavior -> ambiguous_02.jpg (red fox)
   0.483  vulpes-vulpes-field-notes -> deer_01.jpg (red deer)
   0.482  brown-bear-hibernation -> fox_02.jpg (red fox)
   0.479  vulpes-vulpes-field-notes -> wolf_01.jpg (gray wolf)
best candidate on the no-match posts:
   0.273  pet-parrot-care -> dog_01.jpg (golden retriever)
   0.276  chocolate-cake -> mountain_02.jpg (mountain)
   0.270  learning-to-sail -> bicycle_02.jpg (bicycle)
```

Similarity alone can't separate right from wrong: a fallow deer (0.557) outscores the
weakest correct match (0.541) on the Vulpes post. The subject and confidence checks stop
those, and the threshold is a safety floor. Nothing on the three no-match posts gets
above 0.28.

---

## Section 6 requirements (one proof per box)

### AI processing

- [x] **Vision output validated against a schema; invalid responses are never trusted.**
  Probe 1: `images whose stored tags re-validate against the VisionTags schema: 48/48`.
  A real invalid reply from this run (post 7, cut off at the context limit, empty
  content) was recorded as a failed call and **not stored**; the post was re-analysed on
  retry:

  ```
  $ curl -s "localhost:8000/costs/records?limit=500" | failed calls only
    #118 job=2 post_analysis post:12 attempt=1 out_tokens=0 ms=0 error=ReadTimeout: timed out
    #115 job=2 post_analysis post:11 attempt=1 out_tokens=0 ms=0 error=no reply recorded: call in progress, or the worker stopped mid-call
    #16 job=2 post_analysis post:7 attempt=1 out_tokens=3860 ms=652767 error=schema validation failed: (root): Invalid JSON: EOF while parsing a value at line 1 column 0
  ```

  Tests: `test_invalid_vision_output_is_rejected[...]` (7 cases),
  `test_output_that_stays_invalid_raises_and_is_never_returned`,
  `test_invalid_model_output_is_never_stored`, `test_truncated_reply_is_reported_as_cut_off`
  (all PASSED, see [Test suite](#test-suite)).

- [x] **Low-confidence classifications are flagged instead of accepted.** Probe 1 lists
  3 flagged images with reasons (`dog_04` confidence 0.30; the bokeh shot and the
  blurred fox on confidence + blur). The guard never recommends them: on the Vulpes
  post the blurred fox scores 0.61 but is rejected:

  ```
  $ curl -s localhost:8000/posts/2   # the "Vulpes vulpes" post never says "fox"
  title: Vulpes vulpes: field notes on a widespread canid
  body mentions "fox": False
  analysed subject: red fox | category: animal
  summary: Field notes describe red foxes with russet coats and white-tipped tails hunting voles in meadows.
  $ curl -s localhost:8000/posts/2/images   # top 5
  status: match | suggestion: fox_05.jpg
    #1 fox_05.jpg       red fox        sim=0.64 accepted  
    #2 fox_02.jpg       red fox        sim=0.63 accepted  
    #3 fox_03.jpg       red fox        sim=0.62 accepted  
    #4 ambiguous_02.jpg red fox        sim=0.61 rejected  Low-confidence image (0.30): flagged for review (model confidence 0.30 is below the 0.60 minimum; image looks blurry (sharpness 2.2 < 15.0))
    #5 fox_01.jpg       red fox        sim=0.58 accepted
  ```

- [x] **Images processed through a batch background job with retries.** Probe 1:
  `job 1 kind=images status=succeeded processed=48/48`. Retry on a real transport
  timeout, from the worker log:

  ```
  2026-09-29 14:32:24,182 WARNING app.services.jobs: job 2 item 108 failed, retrying in 2s: attempt 1/3: OllamaError: ReadTimeout: timed out
  ```

  Crash recovery and graceful shutdown during the real run (worker log):

  ```
  2026-09-29 09:54:24,715 INFO app.worker: worker started (vision=qwen3-vl:4b, embed=all-minilm)
  2026-09-29 09:54:24,810 WARNING app.services.jobs: requeued stale jobs [1] (worker heartbeat lost)
  2026-09-29 09:54:24,836 INFO app.services.jobs: job 1: 45 item(s) to process
  2026-09-29 10:01:08,641 INFO app.services.costs: cost op=embed model=all-minilm target=image:4 in=36 out=0 ms=639 ok=True
  2026-09-29 10:01:08,694 INFO app.services.jobs: job 1 item 4 (image 4): done
  2026-09-29 10:01:08,711 INFO app.services.jobs: job 1 requeued for shutdown; 4 item(s) already processed
  2026-09-29 10:01:08,713 INFO app.worker: worker stopped
  2026-09-29 14:01:35,366 INFO app.worker: worker started (vision=qwen3-vl:4b, embed=all-minilm)
  2026-09-29 14:11:25,559 WARNING app.services.jobs: requeued stale jobs [2] (worker heartbeat lost)
  2026-09-29 14:11:25,578 INFO app.services.jobs: job 2: 61 item(s) to process
  2026-09-29 14:51:52,733 INFO app.services.costs: cost op=embed model=all-minilm target=post:13 in=60 out=0 ms=657 ok=True
  2026-09-29 14:51:52,752 INFO app.services.jobs: job 2 item 109 (post 13): done
  2026-09-29 14:51:52,768 INFO app.services.jobs: job 2 requeued for shutdown; 13 item(s) already processed
  2026-09-29 14:51:52,773 INFO app.worker: worker stopped
  ```

  Tests: `test_transient_error_is_retried_then_succeeds`,
  `test_item_that_keeps_failing_marks_job_failed_with_alert`,
  `test_shutdown_during_a_retry_hands_the_job_back_to_the_queue`.

- [x] **Vision and embedding costs tracked per call.** Probe 6: 145 calls,
  `tagged images with both a vision_tag and an embed cost row: 48/48`,
  `ready posts with both a post_analysis and an embed cost row: 23/23`. Failed calls
  are costed too (see the failed-call listing above; row #115 is a call interrupted by
  a database outage, left attributed by the write-ahead cost row).

### Matching system

- [x] **Image and post embeddings are stored; posts return ranked image suggestions.**

  ```
  $ psql: stored embeddings
      table_name    | rows | dims 
  ------------------+------+------
   image_embeddings |   48 |  384
   post_embeddings  |   23 |  384
  (2 rows)
  ```

  Ranked suggestions: Probe 2. The ranking uses the HNSW index:

  ```
  $ psql: EXPLAIN of the ranking query uses the HNSW index
  SET
                                 QUERY PLAN                                
  -------------------------------------------------------------------------
   Limit
     InitPlan 1 (returns $0)
       ->  Index Scan using post_embeddings_post_id_key on post_embeddings
             Index Cond: (post_id = 1)
     ->  Index Scan using ix_image_embeddings_hnsw on image_embeddings
           Order By: (embedding <=> $0)
  (6 rows)
  ```

- [x] **Semantic matching works for equivalent concepts: "red fox" matches "Vulpes vulpes".**
  The post never uses the word "fox", yet the top match is a fox (see the Vulpes output
  under "Low-confidence" above). Probe 5 shows `vulpes-vulpes-field-notes -> fox_05.jpg OK`
  and `canis-lupus-returns -> wolf_03.jpg OK`.

### Safety layer

- [x] **The mismatch guard rejects incorrect recommendations: the wolf-on-a-fox-post
  scenario provably fails.** Probe 3: `"decision": "rejected"`,
  `Animal category mismatch: expected red fox, detected gray wolf`. Test:
  `test_wolf_on_fox_post_is_rejected_with_category_mismatch_reason` (guard accepts
  nothing even when the wolf's similarity is high) and
  `test_force_checking_the_wolf_on_the_fox_post_is_rejected` (through the API).
- [x] **Rejections include a human-readable explanation.** Probe 3 `explanation`, and the
  inspect endpoint lists every check:

  ```
  $ curl -s http://localhost:8000/suggestions/3 | pj 2600
  {
    "id": 3,
    "post_id": 1,
    "post_title": "The behavior of red foxes",
    "image_id": 6,
    "filename": "wolf_01.jpg",
    "rank": 9,
    "similarity": 0.3717,
    "decision": "rejected",
    "explanation": "Rejected: Animal category mismatch: expected red fox, detected gray wolf; Similarity 0.37 is below the threshold 0.50",
    "review_status": "rejected",
    "reasons": [
      "Animal category mismatch: expected red fox, detected gray wolf",
      "Similarity 0.37 is below the threshold 0.50"
    ],
    "checks": [
      {
        "name": "ready",
        "passed": true,
        "detail": "image has validated tags and an embedding",
        "value": null,
        "threshold": null
      },
      {
        "name": "confidence",
        "passed": true,
        "detail": "confidence 0.95 >= 0.60",
        "value": 0.95,
        "threshold": 0.6
      },
      {
        "name": "category",
        "passed": true,
        "detail": "both are 'animal'",
        "value": null,
        "threshold": null
      },
      {
        "name": "subject",
        "passed": false,
        "detail": "'gray wolf' is not 'red fox' (subject similarity 0.53)",
        "value": 0.5261638886186043,
        "threshold": 0.8
      },
      {
        "name": "similarity",
        "passed": false,
        "detail": "0.37 < threshold 0.50",
        "value": 0.3717,
        "threshold": 0.5
      }
    ],
    "guard_version": "g1",
    "post": {
      "id": 1,
      "slug": "red-fox-behavior",
      "title": "The behavior of red foxes",
      "body": "Red foxes are solitary hunters that patrol their territory at dawn and dusk. They pounce on mice hidden under grass or snow, using their sharp hearing to pinpoint prey. In spring, pairs raise their kits in dens dug into banks, and their bushy tails help them balance and keep warm through the winter.",
      "status": "ready",
      "subject": "red fox",
      "category": "animal",
      "concepts": [
        "solitary hunters",
        "dawn patrols",
        "mouse hunting",
        "bushy tail",
        "winter den"
      ],
      "summary": "Red foxes hunt mice at dawn and dusk, use their hearing to locate prey, and raise kits in dens during spring.",
      "analysis_confidence": 0.95,
      "error": null
    },
    "image": {
      "id": 6,
      "filename": "wolf_01.jpg",
      "status": "tagged",
      "error": null,
      "width": 1024,
      "height": 768,
      "source_url": "https://www.pexels.com/photo/gray-wolf-in-forest-clearing-during-daytime-31767241/",
      "photographer": "Daniel Lengies",
      "license": "Pexels License",
      "meta": {
        "subject": "gray wolf",
        "category": "animal",
        "attributes": [
          "standing",
          "grassy",
          "w
  ...
  ```

- [x] **When no image clears the bar, the system answers "no confident match" with
  reasons.** Probe 4: parrot, chocolate cake and sailing posts all return
  `status=no_confident_match` with "Similarity below threshold ..." and "Subjects don't
  match ..." reasons.

### Backend

- [x] **Database models for images, tags, embeddings, posts, suggestions,
  approvals/rejections, with the required indexes.** Three Alembic migrations; live
  schema:

  ```
  $ docker compose exec migrate alembic current   # (run via api container)
  0003 (head)

  $ psql: indexes and unique constraints
      tablename     |           indexname            |                                                   indexdef                                                   
  ------------------+--------------------------------+--------------------------------------------------------------------------------------------------------------
   cost_records     | cost_records_pkey              | CREATE UNIQUE INDEX cost_records_pkey ON public.cost_records USING btree (id)
   cost_records     | ix_cost_records_job            | CREATE INDEX ix_cost_records_job ON public.cost_records USING btree (job_id)
   cost_records     | ix_cost_records_operation      | CREATE INDEX ix_cost_records_operation ON public.cost_records USING btree (operation)
   cost_records     | ix_cost_records_tenant_created | CREATE INDEX ix_cost_records_tenant_created ON public.cost_records USING btree (tenant_id, created_at)
   image_embeddings | image_embeddings_image_id_key  | CREATE UNIQUE INDEX image_embeddings_image_id_key ON public.image_embeddings USING btree (image_id)
   image_embeddings | image_embeddings_pkey          | CREATE UNIQUE INDEX image_embeddings_pkey ON public.image_embeddings USING btree (id)
   image_embeddings | ix_image_embeddings_hnsw       | CREATE INDEX ix_image_embeddings_hnsw ON public.image_embeddings USING hnsw (embedding vector_cosine_ops)
   image_embeddings | ix_image_embeddings_tenant     | CREATE INDEX ix_image_embeddings_tenant ON public.image_embeddings USING btree (tenant_id)
   image_metadata   | image_metadata_image_id_key    | CREATE UNIQUE INDEX image_metadata_image_id_key ON public.image_metadata USING btree (image_id)
   image_metadata   | image_metadata_pkey            | CREATE UNIQUE INDEX image_metadata_pkey ON public.image_metadata USING btree (id)
   image_metadata   | ix_image_metadata_category     | CREATE INDEX ix_image_metadata_category ON public.image_metadata USING btree (category)
   image_tags       | image_tags_pkey                | CREATE UNIQUE INDEX image_tags_pkey ON public.image_tags USING btree (id)
   image_tags       | ix_image_tags_tag              | CREATE INDEX ix_image_tags_tag ON public.image_tags USING btree (tag)
   image_tags       | uq_image_tags_image_tag_kind   | CREATE UNIQUE INDEX uq_image_tags_image_tag_kind ON public.image_tags USING btree (image_id, tag, kind)
   images           | images_pkey                    | CREATE UNIQUE INDEX images_pkey ON public.images USING btree (id)
   images           | ix_images_sha256               | CREATE INDEX ix_images_sha256 ON public.images USING btree (sha256)
   images           | ix_images_tenant_status        | CREATE INDEX ix_images_tenant_status ON public.images USING btree (tenant_id, status)
   images           | uq_images_tenant_filename      | CREATE UNIQUE INDEX uq_images_tenant_filename ON public.images USING btree (tenant_id, filename)
   job_items        | ix_job_items_job_status        | CREATE INDEX ix_job_items_job_status ON public.job_items USING btree (job_id, status)
   job_items        | job_items_pkey                 | CREATE UNIQUE INDEX job_items_pkey ON public.job_items USING btree (id)
   job_items        | uq_job_items_job_target        | CREATE UNIQUE INDEX uq_job_items_job_target ON public.job_items USING btree (job_id, target_type, target_id)
   jobs             | ix_jobs_status_id              | CREATE INDEX ix_jobs_status_id ON public.jobs USING btree (status, id)
   jobs             | jobs_pkey                      | CREATE UNIQUE INDEX jobs_pkey ON public.jobs USING btree (id)
   jobs             | uq_jobs_tenant_idempotency_key | CREATE UNIQUE INDEX uq_jobs_tenant_idempotency_key ON public.jobs USING btree (tenant_id, idempotency_key)
   post_embeddings  | post_embeddings_pkey           | CREATE UNIQUE INDEX post_embeddings_pkey ON public.post_embeddings USING btree (id)
   post_embeddings  | post_embeddings_post_id_key    | CREATE UNIQUE INDEX post_embeddings_post_id_key ON public.post_embeddings USING btree (post_id)
   posts            | ix_posts_tenant_status         | CREATE INDEX ix_posts_tenant_status ON public.posts USING btree (tenant_id, status)
   posts            | posts_pkey                     | CREATE UNIQUE INDEX posts_pkey ON public.posts USING btree (id)
   posts            | uq_posts_tenant_slug           | CREATE UNIQUE INDEX uq_posts_tenant_slug ON public.posts USING btree (tenant_id, slug)
   reviews          | ix_reviews_suggestion          | CREATE INDEX ix_reviews_suggestion ON public.reviews USING btree (suggestion_id)
   reviews          | ix_reviews_tenant_created      | CREATE INDEX ix_reviews_tenant_created ON public.reviews USING btree (tenant_id, created_at)
   reviews          | reviews_pkey                   | CREATE UNIQUE INDEX reviews_pkey ON public.reviews USING btree (id)
   suggestions      | ix_suggestions_post_rank       | CREATE INDEX ix_suggestions_post_rank ON public.suggestions USING btree (post_id, rank)
   suggestions      | ix_suggestions_tenant_review   | CREATE INDEX ix_suggestions_tenant_review ON public.suggestions USING btree (tenant_id, review_status)
   suggestions      | suggestions_pkey               | CREATE UNIQUE INDEX suggestions_pkey ON public.suggestions USING btree (id)
   suggestions      | uq_suggestions_post_image      | CREATE UNIQUE INDEX uq_suggestions_post_image ON public.suggestions USING btree (post_id, image_id)
   tenants          | tenants_pkey                   | CREATE UNIQUE INDEX tenants_pkey ON public.tenants USING btree (id)
   tenants          | tenants_slug_key               | CREATE UNIQUE INDEX tenants_slug_key ON public.tenants USING btree (slug)
  (38 rows)

  $ psql: check constraints
       table      |           conname            |                                                                                            definition                                                                                             
  ----------------+------------------------------+---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
   images         | ck_images_status             | CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'tagged'::character varying, 'needs_review'::character varying, 'failed'::character varying])::text[])))
   image_metadata | ck_image_metadata_confidence | CHECK (((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))
   posts          | ck_posts_status              | CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'ready'::character varying, 'failed'::character varying])::text[])))
   jobs           | ck_jobs_status               | CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'succeeded'::character varying, 'failed'::character varying])::text[])))
   job_items      | ck_job_items_status          | CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'done'::character varying, 'skipped'::character varying, 'failed'::character varying])::text[])))
   job_items      | ck_job_items_target_type     | CHECK (((target_type)::text = ANY ((ARRAY['image'::character varying, 'post'::character varying])::text[])))
   suggestions    | ck_suggestions_decision      | CHECK (((decision)::text = ANY ((ARRAY['accepted'::character varying, 'rejected'::character varying])::text[])))
   suggestions    | ck_suggestions_review_status | CHECK (((review_status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[])))
   reviews        | ck_reviews_action            | CHECK (((action)::text = ANY ((ARRAY['approve'::character varying, 'reject'::character varying])::text[])))
  (9 rows)
  ```

- [x] **API endpoints validated; the review workflow (approve / reject / inspect why) exists.**

  ```
  ===== REVIEW WORKFLOW =====
  suggestion id of the fox post's accepted image: 1
  $ curl -s -X POST http://localhost:8000/suggestions/1/approve -H 'content-type: application/json' -d '{"reviewer": "editor", "note": "right animal, good light"}' | .venv/Scripts/python -c "import sys,json;r=json.load(sys.stdin);print(r['changed'], r['message'], r['suggestion']['review_status'], len(r['suggestion']['reviews']), 'review row(s)')"
  True suggestion approved approved 1 review row(s)


  $ curl -s -X POST http://localhost:8000/suggestions/1/approve -H 'content-type: application/json' -d '{"reviewer": "editor"}' | .venv/Scripts/python -c "import sys,json;r=json.load(sys.stdin);print(r['changed'], r['message'], r['suggestion']['review_status'], len(r['suggestion']['reviews']), 'review row(s)')"
  False already approved; nothing changed (idempotent) approved 1 review row(s)


  $ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/suggestions/1/reject -H 'content-type: application/json' -d '{}'
  {"error":{"code":"conflict","message":"suggestion 1 is already approved; refusing to reject it again with a different decision"}}
  HTTP 409


  $ curl -s -X POST http://localhost:8000/suggestions/3/reject -H 'content-type: application/json' -d '{"reviewer": "editor", "note": "wolf, not fox"}' | .venv/Scripts/python -c "import sys,json;r=json.load(sys.stdin);print(r['changed'], r['message'])"
  True suggestion rejected
  $ curl -s http://localhost:8000/suggestions/3   (full output under 'Rejections include a human-readable explanation')

  $ curl -s 'http://localhost:8000/suggestions?review_status=approved' | pj 800
  [
    {
      "id": 1,
      "post_id": 1,
      "post_title": "The behavior of red foxes",
      "image_id": 5,
      "filename": "fox_05.jpg",
      "rank": 1,
      "similarity": 0.6335,
      "decision": "accepted",
      "explanation": "Accepted: 'red fox' fits the post (same kind of subject ('fox')); similarity 0.63 >= 0.50; confidence 0.95",
      "review_status": "approved"
    }
  ]


  $ curl -s -o /dev/null -w 'GET /review -> HTTP %{http_code}, %{size_download} bytes of HTML\n' http://localhost:8000/review
  GET /review -> HTTP 200, 58830 bytes of HTML
  ```

### Quality & documentation

- [x] **A small labeled evaluation dataset measures top-1 precision; the number is in the
  README.** `eval/eval_set.json` (23 posts). Probe 5: `Top-1 precision: 18/20 = 0.90`,
  and the README states 0.90.
- [x] **README with architecture explanation and diagram; the required Section 11 files
  are present.**

  ```
  $ ls README.md capstone.yaml EVIDENCE.md BUILDLOG.md .env.example LICENSE docs/design.md
  .env.example
  BUILDLOG.md
  EVIDENCE.md
  LICENSE
  README.md
  capstone.yaml
  docs/design.md
  ```

---

## Section 13 shared requirements

| # | Requirement | Proof |
|---|---|---|
| 1 | Layered architecture | output below: no SQL and no model calls in `app/api/` |
| 2 | Validation at the boundary, bad input -> clean 4xx | curl transcript below + 19 parametrised cases in `test_bad_input_returns_clean_4xx`; a DB outage gives 503 (`test_database_outage_is_a_clean_503_not_a_500`) |
| 3 | Background job, retries + failure alert | worker logs above; `ALERT job 4 failed: ...` in the budget demo below; `test_item_that_keeps_failing_marks_job_failed_with_alert` |
| 4 | Real persistence: migrations, indexes, isolated tenants | schema above; tenant transcript below; `test_tenants_are_isolated` |
| 5 | Idempotency where it matters | job idempotency + re-run demo below; review approve twice = one review row (transcript below) |
| 6 | Secrets clean | git output below; `test_database_password_is_never_shown_in_repr_or_str` |
| 7 | Cost tracked per call, with a budget guard | Probe 6 + budget demo below |

### 1. Layers

```
$ grep -rn "select(\|session.execute\|text(" app/api/   # no SQL in the HTTP layer
(no matches)
$ grep -rln "ollama\|OllamaClient" app/api/ app/repositories/   # no model calls in HTTP or data layers
(no matches)
$ ls app/api app/services app/repositories
app/api:
__init__.py
costs.py
deps.py
images.py
jobs.py
posts.py
suggestions.py

app/repositories:
__init__.py
costs.py
embeddings.py
images.py
jobs.py
posts.py
suggestions.py
tenants.py

app/services:
__init__.py
costs.py
embeddings.py
guard.py
jobs.py
matching.py
pipeline.py
posts.py
review.py
structured.py
vision.py
```

### 2. Bad input -> clean 4xx (and tenant isolation)

```
===== HEALTH =====
$ curl -s http://localhost:8000/health
{"status":"ok","database":"ok","ollama":"ok","vision_model":"qwen3-vl:4b","embed_model":"all-minilm"}

===== BAD INPUT -> CLEAN 4XX =====
$ curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/posts/abc/images; curl -s http://localhost:8000/posts/abc/images
422
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["path","post_id"],"msg":"Input should be a valid integer, unable to parse string as an integer","type":"int_parsing"}]}}

$ curl -s -w '\nHTTP %{http_code}\n' http://localhost:8000/posts/99999/images
{"error":{"code":"not_found","message":"post 99999 not found"}}
HTTP 404


$ curl -s -w '\nHTTP %{http_code}\n' 'http://localhost:8000/posts/1/images?limit=0'
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["query","limit"],"msg":"Input should be greater than or equal to 1","type":"greater_than_equal"}]}}
HTTP 422


$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/posts/1/check -H 'content-type: application/json' -d '{"image_id": "wolf"}'
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["body","image_id"],"msg":"Input should be a valid integer, unable to parse string as an integer","type":"int_parsing"}]}}
HTTP 422


$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/posts/1/check -H 'content-type: application/json' -d '{not json'
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["body",1],"msg":"JSON decode error","type":"json_invalid"}]}}
HTTP 422


$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/posts/1/check -H 'content-type: application/json' -d '{"image_id": 99999}'
{"error":{"code":"not_found","message":"image 99999 not found"}}
HTTP 404


$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/posts -H 'content-type: application/json' -d '{"slug": "red-fox-behavior", "title": "Foxes again", "body": "A duplicate post about red foxes in the wild."}'
{"error":{"code":"conflict","message":"a post with slug 'red-fox-behavior' already exists"}}
HTTP 409


$ curl -s -w '\nHTTP %{http_code}\n' 'http://localhost:8000/images?status=bogus'
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["query","status"],"msg":"Input should be 'pending', 'tagged', 'needs_review' or 'failed'","type":"literal_error"}]}}
HTTP 422


$ curl -s -w '\nHTTP %{http_code}\n' -X POST http://localhost:8000/jobs -H 'content-type: application/json' -d '{"kind": "everything"}'
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["body","kind"],"msg":"Input should be 'ingest', 'images' or 'posts'","type":"literal_error"}]}}
HTTP 422


$ curl -s -w '\nHTTP %{http_code}\n' -H 'X-Tenant-ID: acme' http://localhost:8000/posts/1
{"error":{"code":"not_found","message":"unknown tenant 'acme'"}}
HTTP 404


$ curl -s -w '\nHTTP %{http_code}\n' -H 'X-Tenant-ID: BAD TENANT' http://localhost:8000/posts/1
{"error":{"code":"validation_error","message":"invalid request","details":[{"loc":["header","x-tenant-id"],"msg":"String should match pattern '^[a-z0-9][a-z0-9-]{0,63}$'","type":"string_pattern_mismatch"}]}}
HTTP 422

===== TENANT ISOLATION =====
$ curl -s -w '\nHTTP %{http_code}\n' -H 'X-Tenant-ID: demo' http://localhost:8000/posts/1 | head -c 200
{"id":1,"slug":"red-fox-behavior","title":"The behavior of red foxes","body":"Red foxes are solitary hunters that patrol their territory at dawn and dusk. They pounce on mice hidden under grass or sno

$ curl -s -w '\nHTTP %{http_code}\n' -H 'X-Tenant-ID: other' http://localhost:8000/posts/1
{"error":{"code":"not_found","message":"post 1 not found"}}
HTTP 404
```

### 5. Idempotent re-run

```
$ curl -s localhost:8000/costs | total_calls   # before
total_calls = 145

$ curl -s -X POST localhost:8000/jobs -H "Idempotency-Key: rerun-demo-1" -d {"kind":"ingest"}   (first time)
job 3 queued total 71   -> HTTP 202
$ same request again (a client retry)
job 3 queued total 71   -> HTTP 200

$ curl -s localhost:8000/jobs/3   # after the worker ran it
{'id': 3, 'status': 'succeeded', 'total': 71, 'processed': 71, 'succeeded': 0, 'skipped': 71, 'failed': 0}
$ curl -s localhost:8000/costs | total_calls   # after: unchanged, no AI calls were made
total_calls = 145
```

### 6. Secrets

```
$ git ls-files | grep -i -E "\.env|images/|\.venv|pycache"
.env.example
$ git check-ignore -v .env data/images .venv
.gitignore:2:.env	.env
.gitignore:17:data/images/	data/images
.gitignore:7:.venv/	.venv
$ git log -p --all | grep -c "POSTGRES_PASSWORD=" ; git log -p --all | grep "POSTGRES_PASSWORD=" | sort -u
1
+POSTGRES_PASSWORD=change-me-local-only
```

### 7. Budget guard, live

```
$ docker compose stop worker        # so the one-off worker below picks up the job
$ curl -s -X POST localhost:8000/jobs -d {"kind":"images","force":true}   # force = would re-tag all 48 images
job 4 queued total 48
$ curl -s localhost:8000/costs   # notional spend so far
total_calls = 145  notional_cost_usd = 0.04705588
$ docker compose run --rm -e AI_BUDGET_USD=0.01 worker python -c "<run one job with JobRunner.run_once()>"
2026-09-29 16:03:32,491 INFO app.services.jobs: job 4: 48 item(s) to process
2026-09-29 16:03:32,694 ERROR app.services.jobs: job 4 item 191 failed permanently: AI budget exhausted: notional spend $0.047056 >= budget $0.01
2026-09-29 16:03:32,694 ERROR app.services.jobs: job 4: budget guard stopped the job: AI budget exhausted: notional spend $0.047056 >= budget $0.01
2026-09-29 16:03:32,967 ERROR app.services.jobs: ALERT job 4 failed: AI budget exhausted: notional spend $0.047056 >= budget $0.01 (succeeded=0 skipped=0 failed=48)
2026-09-29 16:03:32,969 INFO app.services.jobs: job 4 finished: failed
$ curl -s localhost:8000/jobs/4
{'id': 4, 'status': 'failed', 'total': 48, 'succeeded': 0, 'failed': 48, 'error': 'AI budget exhausted: notional spend $0.047056 >= budget $0.01'}
  item image 1 -> AI budget exhausted: notional spend $0.047056 >= budget $0.01
  item image 2 -> not attempted: AI budget exhausted: notional spend $0.047056 >= budget $0.01
  item image 3 -> not attempted: AI budget exhausted: notional spend $0.047056 >= budget $0.01
$ curl -s localhost:8000/costs   # unchanged: the guard refused before any model call
total_calls = 145  notional_cost_usd = 0.04705588
```

---

## Test suite

```
$ docker compose exec api pytest -v
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python3.12
cachedir: .pytest_cache
rootdir: /app
plugins: anyio-4.15.1
collecting ... collected 83 items

tests/test_config.py::test_database_password_is_never_shown_in_repr_or_str PASSED [  1%]
tests/test_guard.py::test_fox_on_fox_post_is_accepted_with_explanation PASSED [  2%]
tests/test_guard.py::test_wolf_on_fox_post_is_rejected_with_category_mismatch_reason PASSED [  3%]
tests/test_guard.py::test_dog_on_fox_post_is_rejected PASSED             [  4%]
tests/test_guard.py::test_different_category_gives_one_clear_reason_not_two PASSED [  6%]
tests/test_guard.py::test_low_similarity_alone_rejects PASSED            [  7%]
tests/test_guard.py::test_flagged_low_confidence_image_is_never_recommended PASSED [  8%]
tests/test_guard.py::test_flagged_image_is_rejected_even_when_confidence_is_high PASSED [  9%]
tests/test_guard.py::test_unanalysed_image_is_rejected PASSED            [ 10%]
tests/test_guard.py::test_all_failures_are_listed PASSED                 [ 12%]
tests/test_guard.py::test_threshold_boundary_is_inclusive PASSED         [ 13%]
tests/test_guard.py::test_subject_match[red fox-img0-True] PASSED        [ 14%]
tests/test_guard.py::test_subject_match[foxes-img1-True] PASSED          [ 15%]
tests/test_guard.py::test_subject_match[dog-img2-True] PASSED            [ 16%]
tests/test_guard.py::test_subject_match[sushi-img3-True] PASSED          [ 18%]
tests/test_guard.py::test_subject_match[red fox-img4-False] PASSED       [ 19%]
tests/test_guard.py::test_subject_match[red fox-img5-False] PASSED       [ 20%]
tests/test_guard.py::test_subject_match[gray wolf-img6-False] PASSED     [ 21%]
tests/test_guard.py::test_subject_embedding_similarity_can_match_synonyms PASSED [ 22%]
tests/test_guard.py::test_normalize_singularises PASSED                  [ 24%]
tests/test_guard.py::test_no_match_reasons_cover_threshold_and_subject PASSED [ 25%]
tests/test_guard.py::test_no_match_with_empty_library PASSED             [ 26%]
tests/test_jobs.py::test_all_images_tagged_embedded_and_costed PASSED    [ 27%]
tests/test_jobs.py::test_transient_error_is_retried_then_succeeds PASSED [ 28%]
tests/test_jobs.py::test_item_that_keeps_failing_marks_job_failed_with_alert PASSED [ 30%]
tests/test_jobs.py::test_invalid_model_output_is_never_stored PASSED     [ 31%]
tests/test_jobs.py::test_rerun_is_idempotent_and_makes_no_ai_calls PASSED [ 32%]
tests/test_jobs.py::test_same_idempotency_key_runs_once PASSED           [ 33%]
tests/test_jobs.py::test_budget_guard_stops_the_job PASSED               [ 34%]
tests/test_jobs.py::test_posts_are_analysed_and_embedded PASSED          [ 36%]
tests/test_jobs.py::test_a_call_that_never_returns_still_leaves_a_cost_row PASSED [ 37%]
tests/test_jobs.py::test_shutdown_during_a_retry_hands_the_job_back_to_the_queue PASSED [ 38%]
tests/test_matching_api.py::test_fox_post_ranks_fox_first_and_explains PASSED [ 39%]
tests/test_matching_api.py::test_force_checking_the_wolf_on_the_fox_post_is_rejected PASSED [ 40%]
tests/test_matching_api.py::test_post_without_a_suitable_image_gets_no_confident_match PASSED [ 42%]
tests/test_matching_api.py::test_suggestions_are_stored_and_re_ranking_is_idempotent PASSED [ 43%]
tests/test_matching_api.py::test_approve_is_idempotent_and_conflicting_decision_is_refused PASSED [ 44%]
tests/test_matching_api.py::test_inspect_shows_why PASSED                [ 45%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/posts/abc/images-kwargs0-422] PASSED [ 46%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/posts/0/images-kwargs1-422] PASSED [ 48%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/posts/99999/images-kwargs2-404] PASSED [ 49%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/posts/1/images?limit=0-kwargs3-422] PASSED [ 50%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/posts/1/images?limit=abc-kwargs4-422] PASSED [ 51%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/posts/1/check-kwargs5-422] PASSED [ 53%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/posts/1/check-kwargs6-422] PASSED [ 54%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/posts/1/check-kwargs7-422] PASSED [ 55%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/posts/1/check-kwargs8-404] PASSED [ 56%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/posts-kwargs9-422] PASSED [ 57%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/suggestions/99999/approve-kwargs10-404] PASSED [ 59%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/suggestions/1/approve-kwargs11-422] PASSED [ 60%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/images?status=bogus-kwargs12-422] PASSED [ 61%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/images/99999-kwargs13-404] PASSED [ 62%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/jobs/99999-kwargs14-404] PASSED [ 63%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[post-/jobs-kwargs15-422] PASSED [ 65%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/costs/records?operation=teleport-kwargs16-422] PASSED [ 66%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/images-kwargs17-404] PASSED [ 67%]
tests/test_matching_api.py::test_bad_input_returns_clean_4xx[get-/images-kwargs18-422] PASSED [ 68%]
tests/test_matching_api.py::test_post_that_is_not_analysed_yet_is_409_not_500 PASSED [ 69%]
tests/test_matching_api.py::test_duplicate_post_slug_is_409 PASSED       [ 71%]
tests/test_matching_api.py::test_tenants_are_isolated PASSED             [ 72%]
tests/test_matching_api.py::test_create_post_queues_a_job PASSED         [ 73%]
tests/test_matching_api.py::test_job_idempotency_key_returns_the_same_job PASSED [ 74%]
tests/test_matching_api.py::test_database_outage_is_a_clean_503_not_a_500 PASSED [ 75%]
tests/test_schema_validation.py::test_valid_vision_output_is_accepted PASSED [ 77%]
tests/test_schema_validation.py::test_scientific_name_in_parentheses_is_stripped_and_lowercased PASSED [ 78%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch0-confidence] PASSED [ 79%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch1-confidence] PASSED [ 80%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch2-category] PASSED [ 81%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch3-attributes] PASSED [ 83%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch4-caption] PASSED [ 84%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch5-subject] PASSED [ 85%]
tests/test_schema_validation.py::test_invalid_vision_output_is_rejected[patch6-extra_field] PASSED [ 86%]
tests/test_schema_validation.py::test_missing_field_and_non_json_are_rejected PASSED [ 87%]
tests/test_schema_validation.py::test_ollama_schema_lists_every_field_as_required PASSED [ 89%]
tests/test_schema_validation.py::test_invalid_then_valid_output_is_retried_and_accepted PASSED [ 90%]
tests/test_schema_validation.py::test_output_that_stays_invalid_raises_and_is_never_returned PASSED [ 91%]
tests/test_schema_validation.py::test_transport_error_is_costed_and_reraised_for_the_job_to_retry PASSED [ 92%]
tests/test_schema_validation.py::test_budget_guard_blocks_the_call_before_it_happens PASSED [ 93%]
tests/test_schema_validation.py::test_low_confidence_is_flagged_not_accepted PASSED [ 95%]
tests/test_schema_validation.py::test_confident_sharp_image_is_not_flagged PASSED [ 96%]
tests/test_schema_validation.py::test_blurry_or_unknown_image_is_flagged_even_when_model_is_confident PASSED [ 97%]
tests/test_schema_validation.py::test_sharpness_separates_sharp_and_blurred_images PASSED [ 98%]
tests/test_schema_validation.py::test_truncated_reply_is_reported_as_cut_off PASSED [100%]

============================= 83 passed in 14.52s ==============================
```

---

## Clean machine run

A fresh `git clone` into an empty temp folder, `cp .env.example .env` (new password,
ports 5434/8001 so it wouldn't clash with the main stack), then the README commands:

```
$ docker compose up -d --build
...
 Container cleanclone-migrate-1 Exited
 Container cleanclone-api-1 Started
 Container cleanclone-worker-1 Started
$ docker compose exec api python -m scripts.seed
1/3 downloading images ...
done: 48 downloaded, 0 already present, 0 failed, 48 in manifest
2/3 registering images and posts ...
  images: 48 added, 0 already registered
  posts: 23 added, 0 updated
3/3 queueing batch job ...
  job 1 created: status=queued
the worker is processing it; follow with: curl localhost:8000/jobs/1
$ curl -s localhost:8001/health
{"status":"ok","database":"ok","ollama":"ok","vision_model":"qwen3-vl:4b","embed_model":"all-minilm"}
$ docker compose logs worker
...
worker-1  | 2026-09-29 09:14:26,431 INFO app.services.jobs: job 1: 71 item(s) to process
worker-1  | 2026-09-29 09:25:03,384 INFO app.services.costs: cost op=post_analysis model=qwen3-vl:4b target=post:1 in=235 out=2784 ms=636939 ok=True
worker-1  | 2026-09-29 09:25:04,436 INFO app.services.costs: cost op=embed model=all-minilm target=post:1 in=52 out=0 ms=1002 ok=True
worker-1  | 2026-09-29 09:25:04,519 INFO app.services.jobs: job 1 item 49 (post 1): done
$ docker compose down -v
 Volume cleanclone_pgdata Removed
 Network cleanclone_default Removed
```

The first item was processed end to end on the clean copy (post analysed, embedded,
`status: ready`). The clone was then removed, since the full batch had already been
proven on the main stack.
