"""Test doubles for the AI client and cost tracker (no Ollama, no database)."""

from __future__ import annotations

from typing import Any

from app.ai.ollama import ChatResult, EmbedResult, OllamaError
from app.errors import BudgetExceeded


class FakeClient:
    """Returns scripted chat replies in order; an Exception in the script is raised."""

    def __init__(self, replies: list[str | Exception] | None = None, vectors: dict[str, list[float]] | None = None):
        self.replies = list(replies or [])
        self.vectors = vectors or {}
        self.chat_calls: list[list[dict[str, Any]]] = []
        self.embed_calls: list[list[str]] = []

    def chat_json(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> ChatResult:
        self.chat_calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=reply, input_tokens=100, output_tokens=20, duration_ms=5, model=model)

    def embed(self, model: str, texts: list[str]) -> EmbedResult:
        self.embed_calls.append(texts)
        return EmbedResult(
            vectors=[self.vectors.get(t, [1.0] + [0.0] * 383) for t in texts],
            input_tokens=10,
            duration_ms=1,
            model=model,
        )


class FakeCosts:
    def __init__(self, budget_calls: int | None = None):
        self.records: list[dict[str, Any]] = []
        self.budget_calls = budget_calls

    def check_budget(self, ctx) -> None:  # noqa: ANN001
        if self.budget_calls is not None and len(self.records) >= self.budget_calls:
            raise BudgetExceeded("test budget exhausted")

    def record(self, ctx, **kw) -> None:  # noqa: ANN001
        self.records.append(kw)


__all__ = ["FakeClient", "FakeCosts", "OllamaError"]
