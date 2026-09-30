"""Embeddings for images and posts in one shared space (all-minilm, 384 dims).

Each item gets two vectors from one embedding call:
  - the full description (used for ranking)
  - the subject alone (used by the guard's subject check)
"""

from __future__ import annotations

import math
import time

from app.ai.ollama import AIClient, OllamaError
from app.config import Settings
from app.errors import InvalidModelOutput
from app.models import ImageMetadata, Post
from app.services.costs import CallContext, CostTracker


def vector_problem(vectors: list[list[float]], dim: int) -> str | None:
    """Why these vectors can't be stored (wrong size, NaN/inf, all zeros), or None if fine.

    A zero vector has no direction, so its cosine similarity is undefined (NaN)."""
    for v in vectors:
        if len(v) != dim:
            return f"embedding has {len(v)} dims, expected {dim}"
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
            return "embedding contains non-finite values"
        if not any(v):
            return "embedding is all zeros (no direction, so cosine similarity is undefined)"
    return None


def image_embedding_text(meta: ImageMetadata) -> str:
    return f"{meta.subject}. {meta.caption} Tags: {', '.join(meta.attributes)}."


def post_embedding_text(post: Post) -> str:
    # built from the post analysis, so scientific names are already common names
    return f"{post.subject}. {post.summary} Related: {', '.join(post.concepts or [])}."


class EmbeddingService:
    def __init__(self, client: AIClient, costs: CostTracker, settings: Settings) -> None:
        self._client = client
        self._costs = costs
        self._settings = settings

    def embed_pair(self, text: str, subject: str, ctx: CallContext) -> tuple[list[float], list[float]]:
        model = self._settings.embed_model
        cost_id = self._costs.begin(ctx, operation="embed", model=model)
        started = time.monotonic()
        try:
            res = self._client.embed(model, [text, subject])
        except OllamaError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            self._costs.finish(cost_id, input_tokens=None, duration_ms=elapsed, success=False, error=str(exc))
            raise
        error = vector_problem(res.vectors, self._settings.embed_dim)
        if error:
            self._costs.finish(
                cost_id, input_tokens=res.input_tokens, duration_ms=res.duration_ms, success=False, error=error
            )
            raise InvalidModelOutput([error])
        self._costs.finish(cost_id, input_tokens=res.input_tokens, duration_ms=res.duration_ms, success=True)
        return res.vectors[0], res.vectors[1]
