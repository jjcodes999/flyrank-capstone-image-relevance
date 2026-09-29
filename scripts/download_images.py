"""Download the image corpus listed in data/manifest.csv into data/images/.

Images are not committed to git; this script rebuilds the corpus on any machine.
Safe to re-run: files that already exist are skipped.

Usage: python -m scripts.download_images [--manifest data/manifest.csv] [--out data/images]
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter

CDN = "https://images.pexels.com/photos/{id}/pexels-photo-{id}.jpeg?auto=compress&cs=tinysrgb&w=1024"
USER_AGENT = "flyrank-capstone-image-relevance/1.0 (corpus download script)"
MAX_SIDE = 1024


def fetch(url: str, attempts: int = 3) -> bytes:
    last: Exception | None = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as exc:  # network errors are retried with backoff
            last = exc
            time.sleep(2**i)
    raise RuntimeError(f"download failed after {attempts} attempts: {url}: {last}")


def apply_transform(img: Image.Image, transform: str) -> Image.Image:
    """Transforms make deliberately ambiguous images, e.g. 'blur:24'."""
    if not transform:
        return img
    kind, _, arg = transform.partition(":")
    if kind == "blur":
        return img.filter(ImageFilter.GaussianBlur(radius=float(arg or 12)))
    raise ValueError(f"unknown transform {transform!r}")


def download_corpus(manifest: str = "data/manifest.csv", out_dir: str = "data/images") -> int:
    """Download every manifest row that is not on disk yet. Returns the number of failures."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(manifest, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    downloaded = skipped = failed = 0
    for row in rows:
        target = out / row["filename"]
        if target.exists() and target.stat().st_size > 0:
            skipped += 1
            continue
        try:
            raw = fetch(CDN.format(id=row["pexels_id"]))
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            img = apply_transform(img, row.get("transform", "").strip())
            img.save(target, "JPEG", quality=88)
            downloaded += 1
            print(f"ok    {row['filename']}  ({row['photographer']})")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {row['filename']}: {exc}", file=sys.stderr)

    print(f"done: {downloaded} downloaded, {skipped} already present, {failed} failed, {len(rows)} in manifest")
    return failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="data/manifest.csv")
    parser.add_argument("--out", default="data/images")
    args = parser.parse_args()
    # photographer names contain non-ASCII characters; Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return 1 if download_corpus(args.manifest, args.out) else 0


if __name__ == "__main__":
    raise SystemExit(main())
