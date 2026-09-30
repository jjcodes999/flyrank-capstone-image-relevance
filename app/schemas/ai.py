"""Schemas the AI output must satisfy before anything is stored.

VisionTags is the image metadata contract from the design doc. The same model is used
twice: its JSON schema constrains Ollama's decoding, and model_validate_json() checks
the reply again, because constrained decoding does not enforce ranges or lengths.
"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Category = Literal["animal", "vehicle", "food", "nature", "person", "object", "other"]
CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]

# lengths are checked *after* trimming, so "     " can't pass as a 5-character caption
ShortTag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Caption = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=400)]

_PARENS = re.compile(r"\s*\([^)]*\)")


def _clean_subject(value: str) -> str:
    # "Red fox (Vulpes vulpes)" -> "red fox"; the model sometimes adds a scientific name
    return _PARENS.sub("", value).strip().strip(".").lower()


def _strict_number(v: object) -> object:
    # JSON true/false would otherwise be coerced to 1.0/0.0 (and "0.9" to 0.9): a
    # malformed confidence must fail validation, not become maximum confidence
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("confidence must be a JSON number")
    return v


def _dedupe_lower(values: list[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        v = v.lower()
        if v not in seen:
            seen.append(v)
    return seen


class VisionTags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=60)
    category: Category
    attributes: list[ShortTag] = Field(min_length=1, max_length=10)
    caption: Caption
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    _numeric_confidence = field_validator("confidence", mode="before")(_strict_number)

    @field_validator("subject")
    @classmethod
    def clean_subject(cls, v: str) -> str:
        v = _clean_subject(v)
        if not v:
            raise ValueError("subject is empty after cleaning")
        return v

    @field_validator("attributes")
    @classmethod
    def clean_attributes(cls, v: list[str]) -> list[str]:
        return _dedupe_lower(v)


class PostAnalysis(BaseModel):
    """What a post is about, in common words (the post-side twin of VisionTags)."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=60)
    category: Category
    concepts: list[ShortTag] = Field(min_length=1, max_length=10)
    summary: Summary
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    _numeric_confidence = field_validator("confidence", mode="before")(_strict_number)

    @field_validator("subject")
    @classmethod
    def clean_subject(cls, v: str) -> str:
        v = _clean_subject(v)
        if not v:
            raise ValueError("subject is empty after cleaning")
        return v

    @field_validator("concepts")
    @classmethod
    def clean_concepts(cls, v: list[str]) -> list[str]:
        return _dedupe_lower(v)


def ollama_schema(model: type[BaseModel]) -> dict:
    """A plain JSON schema for Ollama's `format` (types, enum, required; no $defs)."""
    props: dict[str, dict] = {}
    for name, field in model.model_fields.items():
        if name == "category":
            props[name] = {"type": "string", "enum": list(CATEGORIES)}
        elif field.annotation is float:
            props[name] = {"type": "number"}
        elif name in ("attributes", "concepts"):
            props[name] = {"type": "array", "items": {"type": "string"}}
        else:
            props[name] = {"type": "string"}
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }
