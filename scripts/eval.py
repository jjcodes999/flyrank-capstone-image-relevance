"""Measure matching quality on the labeled eval set, through the live API.

    python -m scripts.eval                 # metrics at the configured threshold
    python -m scripts.eval --sweep         # also try other similarity thresholds

Top-1 precision (the headline number) = of the posts that have a correct image, the
share whose suggested image is one of the labeled correct images. A post answered with
"no_confident_match" counts as a miss. Posts labeled with no correct image are scored
separately: the right answer there is "no_confident_match".

The sweep re-applies the guard offline: every guard check except similarity is taken from
the API response, and the similarity rule is re-evaluated at each candidate threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

EVAL_SET = Path("eval/eval_set.json")
RESULTS = Path("eval/results/latest.json")


def get(base: str, path: str, tenant: str) -> dict | list:
    req = urllib.request.Request(base + path, headers={"X-Tenant-ID": tenant})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


@dataclass
class PostResult:
    slug: str
    correct: list[str]
    response: dict

    def suggestion_at(self, threshold: float | None) -> str | None:
        """Filename the system suggests; with a threshold, re-apply the similarity rule."""
        if threshold is None:
            s = self.response["suggestion"]
            return s["filename"] if s else None
        for c in self.response["candidates"]:
            others_pass = all(ch["passed"] for ch in c["checks"] if ch["name"] != "similarity")
            if others_pass and c["similarity"] >= threshold:
                return c["filename"]
        return None


def score(results: list[PostResult], threshold: float | None) -> dict:
    labeled = [r for r in results if r.correct]
    nomatch = [r for r in results if not r.correct]
    hits = sum(1 for r in labeled if r.suggestion_at(threshold) in r.correct)
    # every emitted suggestion counts, including a wrong answer on a no-match post
    answered = sum(1 for r in results if r.suggestion_at(threshold) is not None)
    refusals = sum(1 for r in nomatch if r.suggestion_at(threshold) is None)
    return {
        "top1_hits": hits,
        "labeled_posts": len(labeled),
        "top1_precision": round(hits / len(labeled), 4) if labeled else None,
        "precision_when_answered": round(hits / answered, 4) if answered else None,
        "answered": answered,
        "correct_refusals": refusals,
        "nomatch_posts": len(nomatch),
        "overall_accuracy": round((hits + refusals) / len(results), 4) if results else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--limit", type=int, default=15, help="candidates judged per post")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    labels = json.loads(EVAL_SET.read_text(encoding="utf-8"))["posts"]
    try:
        posts = {p["slug"]: p for p in get(args.base_url, "/posts?limit=200", args.tenant)}
    except urllib.error.URLError as exc:
        print(f"cannot reach the API at {args.base_url}: {exc}")
        return 2

    results: list[PostResult] = []
    for label in labels:
        post = posts.get(label["slug"])
        if post is None or post["status"] != "ready":
            print(f"post '{label['slug']}' is missing or not analysed yet; run the seed job first")
            return 2
        resp = get(args.base_url, f"/posts/{post['id']}/images?limit={args.limit}", args.tenant)
        results.append(PostResult(label["slug"], label["correct_images"], resp))

    threshold = results[0].response["similarity_threshold"]
    print(f"Eval set: {len(results)} posts ({sum(1 for r in results if r.correct)} with a correct image, "
          f"{sum(1 for r in results if not r.correct)} where no image fits)")
    print(f"Similarity threshold in use: {threshold}\n")
    print(f"{'post':28} {'expected':22} {'suggested':18} {'sim':>5}  result")
    for r in results:
        resp = r.response
        sug = resp["suggestion"]
        got = sug["filename"] if sug else "no_confident_match"
        sim = f"{sug['similarity']:.2f}" if sug else ""
        expected = (r.correct[0].split("_")[0] + "_*") if len(r.correct) > 1 else (r.correct[0] if r.correct else "no match")
        ok = (sug is not None and got in r.correct) or (sug is None and not r.correct)
        print(f"{r.slug[:28]:28} {expected:22} {got:18} {sim:>5}  {'OK' if ok else 'MISS'}")
        if args.verbose or not ok:
            top = resp["candidates"][:3]
            for c in top:
                print(f"{'':30}#{c['rank']} {c['filename']:16} sim={c['similarity']:.2f} {c['decision']}: "
                      f"{'; '.join(c['reasons']) or 'ok'}")
            if not sug:
                print(f"{'':30}reasons: {' | '.join(resp['reasons'])}")

    m = score(results, None)
    print()
    print(f"Top-1 precision: {m['top1_hits']}/{m['labeled_posts']} = {m['top1_precision']:.2f}")
    if m["precision_when_answered"] is not None:
        print(f"Precision when it answers: {m['top1_hits']}/{m['answered']} = {m['precision_when_answered']:.2f}")
    print(f"Correct 'no confident match': {m['correct_refusals']}/{m['nomatch_posts']}")
    print(f"Overall decision accuracy: {m['overall_accuracy']:.2f}")

    sweep = []
    if args.sweep:
        print("\nThreshold sweep (guard re-applied offline to the same candidates):")
        print(f"{'threshold':>9} {'top1':>6} {'answered':>8} {'refusals':>8} {'overall':>8}")
        for i in range(0, 13):
            t = round(0.20 + 0.05 * i, 2)
            s = score(results, t)
            sweep.append({"threshold": t, **s})
            print(f"{t:>9.2f} {s['top1_precision']:>6.2f} {s['answered']:>8} "
                  f"{s['correct_refusals']:>5}/{s['nomatch_posts']} {s['overall_accuracy']:>8.2f}")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps({"threshold": threshold, "metrics": m, "sweep": sweep,
                    "posts": [{"slug": r.slug, "correct": r.correct, "response": r.response} for r in results]},
                   indent=2),
        encoding="utf-8",
    )
    print(f"\nfull results written to {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
