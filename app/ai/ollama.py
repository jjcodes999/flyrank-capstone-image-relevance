"""Thin HTTP client for a local Ollama server.

It only moves bytes: it returns the raw text plus token counts and timing, and never
decides whether the output is valid. Validation lives in the services layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class OllamaError(Exception):
    """Transport-level failure (connection refused, timeout, 5xx). Safe to retry."""


@dataclass(frozen=True)
class ChatResult:
    content: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    model: str
    truncated: bool = False  # generation stopped at the context limit (done_reason == "length")


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    input_tokens: int
    duration_ms: int
    model: str


class AIClient(Protocol):
    def chat_json(
        self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]
    ) -> ChatResult: ...

    def embed(self, model: str, texts: list[str]) -> EmbedResult: ...


class OllamaClient:
    def __init__(self, base_url: str, timeout_s: float, num_ctx: int = 8192) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._num_ctx = num_ctx

    def _post(self, path: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        started = time.monotonic()
        try:
            resp = self._http.post(path, json=body)
        except httpx.HTTPError as exc:
            raise OllamaError(f"{type(exc).__name__}: {exc}") from exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 400:
            raise OllamaError(f"ollama {path} returned {resp.status_code}: {resp.text[:300]}")
        return resp.json(), elapsed_ms

    def chat_json(self, model: str, messages: list[dict[str, Any]], schema: dict[str, Any]) -> ChatResult:
        body = {
            "model": model,
            "messages": messages,
            "format": schema,  # Ollama structured output: constrains decoding to this JSON schema
            "stream": False,
            "think": False,  # note: qwen3-vl:4b is a thinking checkpoint and ignores this flag
            # the hidden reasoning counts against the context window; Ollama's default of
            # 4096 tokens was too small and cut replies off before any JSON was written
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        data, elapsed_ms = self._post("/api/chat", body)
        return ChatResult(
            content=data.get("message", {}).get("content", ""),
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            duration_ms=elapsed_ms,
            model=model,
            truncated=data.get("done_reason") == "length",
        )

    def embed(self, model: str, texts: list[str]) -> EmbedResult:
        data, elapsed_ms = self._post("/api/embed", {"model": model, "input": texts})
        vectors = data.get("embeddings") or []
        if len(vectors) != len(texts):
            raise OllamaError(f"expected {len(texts)} embeddings, got {len(vectors)}")
        return EmbedResult(
            vectors=vectors,
            input_tokens=int(data.get("prompt_eval_count") or 0),
            duration_ms=elapsed_ms,
            model=model,
        )

    def installed_models(self) -> list[str] | None:
        """Names of the models Ollama has pulled, or None if Ollama is unreachable."""
        try:
            resp = self._http.get("/api/tags", timeout=3)
            if resp.status_code != 200:
                return None
            return [m.get("name", "") for m in resp.json().get("models", [])]
        except (httpx.HTTPError, ValueError):
            return None
