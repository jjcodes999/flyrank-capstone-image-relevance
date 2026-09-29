"""Run the six acceptance probes against the live API and print the results.

    docker compose exec api python -m scripts.probes        (or with BASE_URL=... from a venv)

Looks things up by post slug / image filename, so it does not depend on database ids.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from app.schemas.ai import VisionTags
from scripts import eval as eval_script

BASE = os.environ.get("BASE_URL", "http://localhost:8000")


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def header(title: str) -> None:
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _, images = call("GET", "/images?limit=200")
    by_file = {i["filename"]: i for i in images["items"]}
    _, posts = call("GET", "/posts?limit=200")
    by_slug = {p["slug"]: p for p in posts}

    # ---------------------------------------------------------------- probe 1
    header("PROBE 1: batch job tags every image with schema-valid output; low confidence is flagged")
    _, jobs = call("GET", "/jobs")
    for j in jobs:
        print(f"job {j['id']} kind={j['kind']} status={j['status']} processed={j['processed']}/{j['total']} "
              f"(done={j['succeeded']} skipped={j['skipped']} failed={j['failed']})")
    print(f"image status counts: {images['status_counts']}")
    valid = 0
    for img in images["items"]:
        m = img["meta"]
        if m:
            VisionTags.model_validate({k: m[k] for k in ("subject", "category", "attributes", "caption", "confidence")})
            valid += 1
    print(f"images whose stored tags re-validate against the VisionTags schema: {valid}/{len(images['items'])}")
    print("flagged needs_review (not trusted):")
    for img in images["items"]:
        m = img["meta"]
        if m and m["needs_review"]:
            print(f"  {img['filename']:18} subject={m['subject']!r:24} conf={m['confidence']:.2f} "
                  f"reasons={m['review_reasons']}")

    # ---------------------------------------------------------------- probe 2
    header("PROBE 2: red fox article -> fox ranks first; wolf and dog rank clearly lower")
    fox_post = by_slug["red-fox-behavior"]
    _, res = call("GET", f"/posts/{fox_post['id']}/images?limit=48")
    print(f"post {fox_post['id']} '{res['title']}' (analysed subject: {res['post_subject']}) -> status={res['status']}")
    print(f"suggestion: {res['suggestion']['filename'] if res['suggestion'] else None}")
    print(f"{'rank':>4} {'image':18} {'subject':24} {'sim':>5}  decision")
    for c in res["candidates"]:
        name = c["filename"]
        if c["rank"] <= 8 or name.startswith(("wolf", "dog", "coyote")):
            print(f"{c['rank']:>4} {name:18} {str(c['subject'])[:24]:24} {c['similarity']:>5.2f}  {c['decision']}")

    # ---------------------------------------------------------------- probe 3
    header("PROBE 3: force the wolf as the candidate for the fox post -> rejected, category mismatch")
    wolf = by_file["wolf_01.jpg"]
    status, verdict = call("POST", f"/posts/{fox_post['id']}/check", {"image_id": wolf["id"]})
    print(f"POST /posts/{fox_post['id']}/check {{\"image_id\": {wolf['id']}}}  (wolf_01.jpg) -> HTTP {status}")
    print(json.dumps({k: verdict[k] for k in ("filename", "subject", "similarity", "decision", "reasons", "explanation")}, indent=2))

    # ---------------------------------------------------------------- probe 4
    header("PROBE 4: post with no suitable image -> 'no confident match' + reasons")
    for slug in ("pet-parrot-care", "chocolate-cake", "learning-to-sail"):
        p = by_slug[slug]
        _, res = call("GET", f"/posts/{p['id']}/images")
        print(f"post {p['id']} '{res['title']}' (subject: {res['post_subject']}) -> status={res['status']}")
        for r in res["reasons"]:
            print(f"    - {r}")

    # ---------------------------------------------------------------- probe 5
    header("PROBE 5: eval script -> top-1 precision on the labeled set")
    sys.argv = ["eval"]
    eval_script.main()

    # ---------------------------------------------------------------- probe 6
    header("PROBE 6: cost log -> every vision/embedding call attributed with a cost entry")
    _, costs = call("GET", "/costs")
    print(json.dumps(costs, indent=2))
    missing = []
    for img in images["items"]:
        if not img["meta"]:
            continue
        _, recs = call("GET", f"/costs/records?target_type=image&target_id={img['id']}&limit=50")
        ops = {r["operation"] for r in recs if r["success"]}
        if not {"vision_tag", "embed"} <= ops:
            missing.append(img["filename"])
    for p in posts:
        if p["status"] != "ready":
            continue
        _, recs = call("GET", f"/costs/records?target_type=post&target_id={p['id']}&limit=50")
        ops = {r["operation"] for r in recs if r["success"]}
        if not {"post_analysis", "embed"} <= ops:
            missing.append(p["slug"])
    tagged = sum(1 for i in images["items"] if i["meta"])
    ready = sum(1 for p in posts if p["status"] == "ready")
    print(f"tagged images with both a vision_tag and an embed cost row: {tagged - len([m for m in missing if m.endswith('.jpg')])}/{tagged}")
    print(f"ready posts with both a post_analysis and an embed cost row: {ready - len([m for m in missing if not m.endswith('.jpg')])}/{ready}")
    _, sample = call("GET", "/costs/records?limit=3")
    print("latest cost records:")
    for r in sample:
        print(f"  #{r['id']} job={r['job_id']} {r['operation']:13} {r['target_type']}:{r['target_id']} model={r['model']} "
              f"in={r['input_tokens']} out={r['output_tokens']} ms={r['duration_ms']} ok={r['success']} "
              f"notional=${float(r['notional_cost_usd']):.6f} actual=${float(r['actual_cost_usd']):.2f}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
