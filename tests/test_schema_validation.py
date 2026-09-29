"""Vision output must match the schema; invalid output is retried, then rejected, never stored."""

import json

import pytest
from PIL import Image, ImageDraw, ImageFilter
from pydantic import ValidationError

from app.config import Settings
from app.errors import BudgetExceeded, InvalidModelOutput
from app.schemas.ai import PostAnalysis, VisionTags, ollama_schema
from app.services.costs import CallContext
from app.services.structured import call_structured
from app.services.vision import review_reasons, sharpness
from tests.fakes import FakeClient, FakeCosts, OllamaError

GOOD = {
    "subject": "red fox",
    "category": "animal",
    "attributes": ["orange fur", "wild", "forest"],
    "caption": "A red fox standing in a forest",
    "confidence": 0.94,
}
CTX = CallContext(tenant_id=1, job_id=1, target_type="image", target_id=1)


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# --- the schema itself ------------------------------------------------------------
def test_valid_vision_output_is_accepted():
    tags = VisionTags.model_validate_json(json.dumps(GOOD))
    assert tags.subject == "red fox" and tags.category == "animal" and tags.confidence == 0.94


def test_scientific_name_in_parentheses_is_stripped_and_lowercased():
    tags = VisionTags.model_validate({**GOOD, "subject": "Red Fox (Vulpes vulpes)"})
    assert tags.subject == "red fox"


@pytest.mark.parametrize(
    "patch, field",
    [
        ({"confidence": 1.7}, "confidence"),
        ({"confidence": -0.1}, "confidence"),
        ({"category": "spaceship"}, "category"),
        ({"attributes": []}, "attributes"),
        ({"caption": "fox"}, "caption"),
        ({"subject": ""}, "subject"),
        ({"extra_field": "surprise"}, "extra_field"),
    ],
)
def test_invalid_vision_output_is_rejected(patch, field):
    with pytest.raises(ValidationError) as exc:
        VisionTags.model_validate({**GOOD, **patch})
    assert field in str(exc.value)


def test_missing_field_and_non_json_are_rejected():
    missing = {k: v for k, v in GOOD.items() if k != "confidence"}
    with pytest.raises(ValidationError):
        VisionTags.model_validate_json(json.dumps(missing))
    with pytest.raises(ValidationError):
        VisionTags.model_validate_json("Sure! Here is a red fox.")


def test_ollama_schema_lists_every_field_as_required():
    schema = ollama_schema(VisionTags)
    assert set(schema["required"]) == {"subject", "category", "attributes", "caption", "confidence"}
    assert "animal" in schema["properties"]["category"]["enum"]
    assert schema["additionalProperties"] is False
    assert set(ollama_schema(PostAnalysis)["required"]) == {"subject", "category", "concepts", "summary", "confidence"}


# --- the retry loop -----------------------------------------------------------------
def run(client, costs, retries=2):
    return call_structured(
        client, costs, CTX, operation="vision_tag", model="m", messages=[{"role": "user", "content": "x"}],
        schema=VisionTags, max_retries=retries,
    )


def test_invalid_then_valid_output_is_retried_and_accepted():
    client = FakeClient([json.dumps({**GOOD, "confidence": 3}), json.dumps(GOOD)])
    costs = FakeCosts()
    result = run(client, costs)
    assert result.value.subject == "red fox" and result.attempts == 2
    # both calls are costed; the first is marked as a failed (invalid) call
    assert [r["success"] for r in costs.records] == [False, True]
    assert "schema validation failed" in costs.records[0]["error"]
    # the validation error is fed back to the model on the retry
    assert "failed validation" in client.chat_calls[1][-1]["content"]


def test_output_that_stays_invalid_raises_and_is_never_returned():
    client = FakeClient(["not json", json.dumps({**GOOD, "category": "x"}), "{}"])
    costs = FakeCosts()
    with pytest.raises(InvalidModelOutput) as exc:
        run(client, costs, retries=2)
    assert len(exc.value.errors) == 3
    assert [r["success"] for r in costs.records] == [False, False, False]


def test_transport_error_is_costed_and_reraised_for_the_job_to_retry():
    costs = FakeCosts()
    with pytest.raises(OllamaError):
        run(FakeClient([OllamaError("connection refused")]), costs)
    assert costs.records[0]["success"] is False and "connection refused" in costs.records[0]["error"]


def test_budget_guard_blocks_the_call_before_it_happens():
    client = FakeClient([json.dumps(GOOD)])
    with pytest.raises(BudgetExceeded):
        run(client, FakeCosts(budget_calls=0))
    assert client.chat_calls == []  # nothing was sent to the model


# --- low confidence flag ------------------------------------------------------------
def test_low_confidence_is_flagged_not_accepted():
    tags = VisionTags.model_validate({**GOOD, "confidence": 0.3})
    reasons = review_reasons(tags, sharpness_score=500.0, settings=settings(min_confidence=0.6))
    assert reasons == ["model confidence 0.30 is below the 0.60 minimum"]


def test_confident_sharp_image_is_not_flagged():
    tags = VisionTags.model_validate(GOOD)
    assert review_reasons(tags, sharpness_score=500.0, settings=settings()) == []


def test_blurry_or_unknown_image_is_flagged_even_when_model_is_confident():
    tags = VisionTags.model_validate({**GOOD, "subject": "unknown", "confidence": 0.9})
    reasons = review_reasons(tags, sharpness_score=3.0, settings=settings(blur_threshold=15))
    assert any("blurry" in r for r in reasons) and any("could not identify" in r for r in reasons)


def test_sharpness_separates_sharp_and_blurred_images():
    img = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(img)
    for x in range(0, 256, 8):
        draw.line([(x, 0), (x, 255)], fill="black", width=2)
    blurred = img.filter(ImageFilter.GaussianBlur(12))
    assert sharpness(img) > 15 > sharpness(blurred)
