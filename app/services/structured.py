"""Call a model for JSON and refuse to accept anything that fails the schema.

Loop per attempt:
  1. budget guard + cost row (raises BudgetExceeded before spending anything)
  2. model call; a transport error is recorded as a failed cost row and re-raised so the
     job layer can retry later
  3. Pydantic validation; on failure the cost row is marked failed, the validation error
     is sent back to the model, and we try again (up to max_retries extra attempts)
After the last invalid attempt we raise InvalidModelOutput. Invalid output is never returned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.ollama import AIClient, OllamaError
from app.errors import InvalidModelOutput
from app.schemas.ai import ollama_schema
from app.services.costs import CallContext, CostTracker

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T
    raw: str
    attempts: int


def summarize_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def call_structured(
    client: AIClient,
    costs: CostTracker,
    ctx: CallContext,
    *,
    operation: str,
    model: str,
    messages: list[dict[str, Any]],
    schema: type[T],
    max_retries: int,
) -> StructuredResult[T]:
    errors: list[str] = []
    convo = list(messages)
    for attempt in range(1, max_retries + 2):
        cost_id = costs.begin(ctx, operation=operation, model=model, attempt=attempt)
        started = time.monotonic()
        try:
            res = client.chat_json(model, convo, ollama_schema(schema))
        except OllamaError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            costs.finish(cost_id, input_tokens=None, duration_ms=elapsed, success=False, error=str(exc))
            raise
        try:
            value = schema.model_validate_json(res.content)
        except ValidationError as exc:
            msg = summarize_validation_error(exc)
            if res.truncated:
                msg = f"reply cut off at the context limit after {res.output_tokens} tokens; {msg}"
            errors.append(msg)
            costs.finish(
                cost_id,
                input_tokens=res.input_tokens,
                output_tokens=res.output_tokens,
                duration_ms=res.duration_ms,
                success=False,
                error=f"schema validation failed: {msg}",
            )
            convo = convo + [
                {"role": "assistant", "content": res.content},
                {
                    "role": "user",
                    "content": f"That JSON failed validation ({msg}). "
                    "Reply again with corrected JSON only, following every rule.",
                },
            ]
            continue
        costs.finish(
            cost_id,
            input_tokens=res.input_tokens,
            output_tokens=res.output_tokens,
            duration_ms=res.duration_ms,
            success=True,
        )
        return StructuredResult(value=value, raw=res.content, attempts=attempt)
    raise InvalidModelOutput(errors)
