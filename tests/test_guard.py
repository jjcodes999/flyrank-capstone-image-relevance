"""The mismatch guard: the wolf never goes on the fox post, and every rejection explains itself."""

import pytest

from app.services.guard import (
    GuardConfig,
    ImageFacts,
    PostFacts,
    Scores,
    evaluate,
    no_match_reasons,
    normalize,
    subject_match,
)

CFG = GuardConfig(similarity_threshold=0.45, min_confidence=0.6, subject_sim_threshold=0.8)
FOX_POST = PostFacts(subject="red fox", category="animal")


def image(**kw) -> ImageFacts:
    base = dict(
        image_id=1,
        ready=True,
        subject="red fox",
        category="animal",
        caption="A red fox lying in green grass.",
        attributes=("orange fur", "grass"),
        confidence=0.95,
    )
    return ImageFacts(**{**base, **kw})


FOX = image()
WOLF = image(image_id=2, subject="gray wolf", caption="A gray wolf standing in a forest clearing.",
             attributes=("gray fur", "forest"))
DOG = image(image_id=3, subject="golden retriever", caption="A golden retriever dog looking up.",
            attributes=("golden fur", "dog"))
CAR = image(image_id=4, subject="volkswagen beetle", category="vehicle", caption="A red car at a show.",
            attributes=("red", "vintage"))


def test_fox_on_fox_post_is_accepted_with_explanation():
    v = evaluate(FOX_POST, FOX, Scores(similarity=0.78, subject_similarity=1.0), CFG)
    assert v.accepted and v.decision == "accepted" and v.reasons == []
    assert v.explanation.startswith("Accepted:") and "0.78" in v.explanation


def test_wolf_on_fox_post_is_rejected_with_category_mismatch_reason():
    # even with a high text similarity the subject check refuses it
    v = evaluate(FOX_POST, WOLF, Scores(similarity=0.62, subject_similarity=0.55), CFG)
    assert not v.accepted
    assert "Animal category mismatch: expected red fox, detected gray wolf" in v.reasons
    assert v.check("subject").passed is False
    assert v.check("similarity").passed is True  # it is the subject rule that saves us


def test_dog_on_fox_post_is_rejected():
    v = evaluate(FOX_POST, DOG, Scores(similarity=0.40, subject_similarity=0.30), CFG)
    assert not v.accepted
    assert any("expected red fox, detected golden retriever" in r for r in v.reasons)
    assert any("Similarity 0.40 is below the threshold 0.45" in r for r in v.reasons)


def test_different_category_gives_one_clear_reason_not_two():
    v = evaluate(FOX_POST, CAR, Scores(similarity=0.10, subject_similarity=0.05), CFG)
    assert "Category mismatch: post is about animal, image shows vehicle" in v.reasons
    assert not any("category mismatch: expected" in r for r in v.reasons)
    assert v.check("subject").detail == "not compared: categories differ"


def test_low_similarity_alone_rejects():
    v = evaluate(FOX_POST, FOX, Scores(similarity=0.30, subject_similarity=1.0), CFG)
    assert not v.accepted and v.reasons == ["Similarity 0.30 is below the threshold 0.45"]


def test_flagged_low_confidence_image_is_never_recommended():
    blurry = image(confidence=0.3, needs_review=True, review_reasons=("image looks blurry (sharpness 2.2 < 15.0)",))
    v = evaluate(FOX_POST, blurry, Scores(similarity=0.9, subject_similarity=1.0), CFG)
    assert not v.accepted
    assert "flagged for review" in v.reasons[0] and "blurry" in v.reasons[0]


def test_flagged_image_is_rejected_even_when_confidence_is_high():
    v = evaluate(FOX_POST, image(confidence=0.9, needs_review=True, review_reasons=("image looks blurry",)),
                 Scores(similarity=0.9, subject_similarity=1.0), CFG)
    assert not v.accepted


def test_unanalysed_image_is_rejected():
    v = evaluate(FOX_POST, ImageFacts(image_id=9, ready=False), Scores(similarity=0.0), CFG)
    assert not v.accepted and v.reasons == ["Image has not been analysed yet"]


def test_all_failures_are_listed():
    bad = image(subject="gray wolf", caption="A wolf.", attributes=("fur",), confidence=0.2, needs_review=True)
    v = evaluate(FOX_POST, bad, Scores(similarity=0.2, subject_similarity=0.5), CFG)
    assert len(v.reasons) == 3  # confidence, subject, similarity
    assert [c.name for c in v.checks] == ["ready", "post", "confidence", "category", "subject", "similarity"]


def test_threshold_boundary_is_inclusive():
    assert evaluate(FOX_POST, FOX, Scores(similarity=0.45, subject_similarity=1.0), CFG).accepted


# --- subject matching ---------------------------------------------------------------
# subject similarities below are real all-minilm scores where we measured them
@pytest.mark.parametrize(
    "post_subject, img, ssim, expected",
    [
        ("red fox", image(subject="red fox"), 1.0, True),  # same species
        ("red foxes", image(subject="red fox"), 0.95, True),  # plural of the same name
        ("red fox", image(subject="fox"), 0.83, True),  # animals: close subject embeddings
        ("red fox", image(subject="gray wolf"), 0.53, False),
        ("red fox", image(subject="coyote"), 0.51, False),
        ("gray wolf", image(subject="siberian husky"), 0.50, False),
        ("neapolitan pizza", image(subject="margherita pizza", category="food"), 0.56, True),  # head noun
        ("sushi", image(subject="sushi roll", category="food"), 0.86, True),
        ("tropical beach", image(subject="beach", category="nature"), 0.80, True),
        ("bicycle", image(subject="motorcycle", category="vehicle"), 0.68, False),
    ],
)
def test_subject_match(post_subject, img, ssim, expected):
    matched, _ = subject_match(post_subject, img, subject_similarity=ssim, threshold=0.8)
    assert matched is expected


# --- counterexamples from the external audit: a shared word must not pass another animal
@pytest.mark.parametrize(
    "post_subject, img, ssim",
    [
        ("red fox", image(subject="arctic fox", caption="An arctic fox on snow."), 0.73),
        ("sea lion", image(subject="lion", caption="A lion on the savannah."), 0.30),
        ("red fox", image(subject="gray wolf", caption="A gray wolf, not a red fox, in a forest."), 0.30),
        ("dog", image(subject="golden retriever", caption="A golden retriever dog."), 0.59),
    ],
)
def test_other_animals_sharing_a_word_are_rejected(post_subject, img, ssim):
    post = PostFacts(subject=post_subject, category="animal")
    v = evaluate(post, img, Scores(similarity=0.75, subject_similarity=ssim), CFG)
    assert not v.accepted
    assert v.check("subject").passed is False
    assert f"expected {post_subject}, detected {img.subject}" in v.reasons[0]


def test_the_caption_text_is_never_used_to_match_a_subject():
    wolf = image(subject="gray wolf", category="nature", caption="Not a waterfall at all.")
    matched, _ = subject_match("waterfall", wolf, subject_similarity=0.2, threshold=0.8)
    assert matched is False


def test_uncertain_post_analysis_is_refused():
    post = PostFacts(subject="red fox", category="animal", confidence=0.01)
    v = evaluate(post, FOX, Scores(similarity=0.9, subject_similarity=1.0), CFG)
    assert not v.accepted and v.check("post").passed is False
    assert v.reasons[0] == "Post analysis is uncertain (0.01 < 0.60); its subject needs review"


@pytest.mark.parametrize("subject", ["none", "unknown", "", None])
def test_post_without_a_visual_subject_is_refused_not_waved_through(subject):
    v = evaluate(PostFacts(subject=subject, category="animal", confidence=0.9), FOX,
                 Scores(similarity=0.9, subject_similarity=1.0), CFG)
    assert not v.accepted
    assert v.reasons[0].startswith("Post has no identifiable visual subject")


def test_no_match_reasons_report_an_uncertain_post_first():
    post = PostFacts(subject="red fox", category="animal", confidence=0.2)
    verdicts = [(FOX, s, evaluate(post, FOX, s, CFG)) for s in [Scores(0.9, 1.0)]]
    reasons = no_match_reasons(post, verdicts, CFG)
    assert reasons[0] == "None of the 1 closest images passed every guard check"
    assert reasons[1].startswith("Post analysis is uncertain")


def test_subject_embedding_similarity_can_match_synonyms():
    burger = image(subject="cheeseburger", category="food", caption="A burger.")
    matched, how = subject_match("hamburger", burger, 0.86, 0.8)
    assert matched and "0.86" in how


def test_normalize_singularises():
    assert normalize("Red Foxes") == ["red", "fox"]
    assert normalize("Gray Wolves") == ["gray", "wolf"]
    assert normalize("sand dunes") == ["sand", "dune"]


# --- no confident match -------------------------------------------------------------
def test_no_match_reasons_cover_threshold_and_subject():
    post = PostFacts(subject="parrot", category="animal")
    verdicts = [
        (img, s, evaluate(post, img, s, CFG))
        for img, s in [(WOLF, Scores(0.31, 0.4)), (DOG, Scores(0.28, 0.35))]
    ]
    assert not any(v.accepted for _, _, v in verdicts)
    reasons = no_match_reasons(post, verdicts, CFG)
    assert reasons[0] == "None of the 2 closest images passed every guard check"
    assert reasons[1].startswith("Similarity below threshold") and "0.31" in reasons[1]
    assert reasons[2].startswith("Subjects don't match: no candidate shows 'parrot'")


def test_no_match_with_empty_library():
    assert no_match_reasons(FOX_POST, [], CFG) == ["No analysed images are available to match against"]
