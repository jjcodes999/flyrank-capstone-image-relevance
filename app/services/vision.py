"""Image understanding: one image in, validated VisionTags out (or an exception)."""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image as PILImage

from app.ai.ollama import AIClient
from app.config import Settings
from app.schemas.ai import VisionTags
from app.services.costs import CallContext, CostTracker
from app.services.structured import StructuredResult, call_structured

# Bump when the prompt or schema changes: images tagged with an older version are
# re-processed on the next job instead of being skipped.
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "You label photos for an image library. Answer with JSON only.\n"
    "subject: the main subject as a short lowercase common name, as specific as you can tell "
    "(e.g. 'red fox', 'gray wolf', 'golden retriever', 'margherita pizza', 'steam locomotive'). "
    "No scientific names. Use 'unknown' if you cannot tell.\n"
    "category: one of animal, vehicle, food, nature, person, object, other.\n"
    "attributes: 3 to 6 short visual tags, 1-3 words each.\n"
    "caption: one plain sentence, at most 20 words.\n"
    "confidence: probability from 0 to 1 that your subject is correct. Use a value below 0.5 "
    "when the image is blurry, dark, abstract, or the subject is hidden or could be several "
    "different things."
)

UNKNOWN_SUBJECTS = {"unknown", "unclear", "unidentifiable", "none", "n/a", "abstract"}


def sharpness(img: PILImage.Image) -> float:
    """Variance of the Laplacian on a 512px grayscale copy. Low = blurry.

    On this corpus the two deliberately blurred images score 2-5, everything else 35+.
    """
    gray = img.convert("L")
    gray.thumbnail((512, 512))
    a = np.asarray(gray, dtype=np.float32)
    lap = a[1:-1, :-2] + a[1:-1, 2:] + a[:-2, 1:-1] + a[2:, 1:-1] - 4 * a[1:-1, 1:-1]
    return float(lap.var())


def review_reasons(tags: VisionTags, sharpness_score: float, settings: Settings) -> list[str]:
    """Why a tagged image should be flagged for human review instead of trusted. Empty = OK."""
    reasons = []
    if tags.confidence < settings.min_confidence:
        reasons.append(
            f"model confidence {tags.confidence:.2f} is below the {settings.min_confidence:.2f} minimum"
        )
    if sharpness_score < settings.blur_threshold:
        reasons.append(f"image looks blurry (sharpness {sharpness_score:.1f} < {settings.blur_threshold:.1f})")
    if tags.subject in UNKNOWN_SUBJECTS:
        reasons.append(f"model could not identify the subject ('{tags.subject}')")
    return reasons


def encode_for_model(img: PILImage.Image, max_side: int) -> str:
    small = img.convert("RGB")
    small.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class VisionService:
    def __init__(self, client: AIClient, costs: CostTracker, settings: Settings) -> None:
        self._client = client
        self._costs = costs
        self._settings = settings

    def tag(self, img: PILImage.Image, ctx: CallContext) -> StructuredResult[VisionTags]:
        # only pixels are sent: never the filename, which would leak the answer
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Label this image.",
                "images": [encode_for_model(img, self._settings.vision_max_side)],
            },
        ]
        return call_structured(
            self._client,
            self._costs,
            ctx,
            operation="vision_tag",
            model=self._settings.vision_model,
            messages=messages,
            schema=VisionTags,
            max_retries=self._settings.vision_max_retries,
        )
