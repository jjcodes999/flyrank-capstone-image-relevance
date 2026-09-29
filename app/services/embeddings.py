"""Embeddings for images and posts in one shared space (all-minilm, 384 dims).

Each item gets two vectors from one embedding call:
  - the full description (used for ranking)
  - the subject alone (used by the guard's subject check)
"""

from __future__ import annotations

from app.ai.ollama import AIClient, OllamaError
from app.config import Settings
from app.errors import InvalidModelOutput
from app.models import ImageMetadata, Post
from app.services.costs import CallContext, CostTracker


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
        self._costs.check_budget(ctx)
        try:
            res = self._client.embed(model, [text, subject])
        except OllamaError as exc:
            self._costs.record(ctx, operation="embed", model=model, success=False, error=str(exc))
            raise
        bad = [len(v) for v in res.vectors if len(v) != self._settings.embed_dim]
        if bad:
            error = f"embedding has {bad[0]} dims, expected {self._settings.embed_dim}"
            self._costs.record(
                ctx, operation="embed", model=model, input_tokens=res.input_tokens,
                duration_ms=res.duration_ms, success=False, error=error,
            )
            raise InvalidModelOutput([error])
        self._costs.record(
            ctx, operation="embed", model=model, input_tokens=res.input_tokens,
            duration_ms=res.duration_ms, success=True,
        )
        return res.vectors[0], res.vectors[1]
