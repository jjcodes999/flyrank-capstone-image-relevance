"""The mismatch guard: is this (post, image) pairing actually good enough?

Pure functions only (no database, no model calls) so every rule is unit-tested.
All checks always run, so a rejection lists every reason, not just the first one.

    1 ready       - image has current validated tags and an embedding, and is not failed
    2 post        - the post analysis is confident and names a visual subject
    3 confidence  - classification confidence >= MIN_CONFIDENCE and not flagged for review
    4 category    - post category == image category
    5 subject     - the image shows the post's subject (see subject_match)
    6 similarity  - cosine(post, image) >= SIMILARITY_THRESHOLD
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

GUARD_VERSION = "g2"
NO_SUBJECT = {"none", "unknown", "n/a", ""}


@dataclass(frozen=True)
class GuardConfig:
    similarity_threshold: float
    min_confidence: float
    subject_sim_threshold: float


@dataclass(frozen=True)
class PostFacts:
    subject: str | None
    category: str | None
    confidence: float | None = None  # post-analysis confidence; None = given by a human


@dataclass(frozen=True)
class ImageFacts:
    image_id: int
    ready: bool
    subject: str | None = None
    category: str | None = None
    caption: str = ""
    attributes: tuple[str, ...] = ()
    confidence: float = 0.0
    needs_review: bool = False
    review_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scores:
    similarity: float  # cosine(post text, image text)
    subject_similarity: float | None = None  # cosine(post subject, image subject)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    value: float | None = None
    threshold: float | None = None


@dataclass
class Verdict:
    accepted: bool
    checks: list[Check] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    explanation: str = ""

    @property
    def decision(self) -> str:
        return "accepted" if self.accepted else "rejected"

    def checks_as_dicts(self) -> list[dict]:
        return [asdict(c) for c in self.checks]

    def check(self, name: str) -> Check:
        """A named check; one that never ran (e.g. after 'ready' failed) counts as failed."""
        return next((c for c in self.checks if c.name == name), Check(name, False, "not evaluated"))


# --- subject matching -----------------------------------------------------------------
_IRREGULAR = {"wolves": "wolf", "geese": "goose", "mice": "mouse", "deer": "deer", "sheep": "sheep", "fish": "fish"}


def _singular(word: str) -> str:
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("xes", "ches", "shes", "sses")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize(text: str | None) -> list[str]:
    """Lowercase words, singular: 'Red Foxes' -> ['red', 'fox']."""
    return [_singular(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())]


def _contains_phrase(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def subject_match(
    post_subject: str,
    image: ImageFacts,
    subject_similarity: float | None,
    threshold: float,
) -> tuple[bool, str]:
    """Does the image show what the post is about? Returns (matched, how/why).

    Animals are matched at species level: the names must be the same, or the subject
    embeddings must be close (>= threshold). A shared last word is not enough there:
    "red fox" vs "arctic fox" or "sea lion" vs "lion" are different animals.
    Other categories may also match on the head noun ("margherita pizza" is a pizza) or
    on the post subject appearing in the image's subject/tags. The free-text caption is
    never used, so a caption like "a wolf, not a red fox" can't sneak a wolf through.
    """
    post_words = normalize(post_subject)
    img_words = normalize(image.subject)
    if not post_words or not img_words:
        return False, "missing subject"
    if post_words == img_words:
        return True, f"same subject ('{' '.join(post_words)}')"
    close = subject_similarity is not None and subject_similarity >= threshold
    sim = f"{subject_similarity:.2f}" if subject_similarity is not None else "n/a"
    if image.category == "animal":
        if close:
            return True, f"same species: subject embeddings are close ({sim} >= {threshold:.2f})"
        return False, f"'{image.subject}' is a different animal from '{post_subject}' (subject similarity {sim})"
    if post_words[-1] == img_words[-1]:
        return True, f"same kind of subject ('{post_words[-1]}')"
    tag_words = normalize(" ".join([image.subject or "", *image.attributes]))
    if _contains_phrase(tag_words, post_words):
        return True, f"'{post_subject}' appears in the image's tags"
    if close:
        return True, f"subject embeddings are close ({sim} >= {threshold:.2f})"
    return False, f"'{image.subject}' is not '{post_subject}' (subject similarity {sim})"


# --- the guard ------------------------------------------------------------------------
def evaluate(post: PostFacts, image: ImageFacts, scores: Scores, cfg: GuardConfig) -> Verdict:
    checks: list[Check] = []
    reasons: list[str] = []

    # 1 ready
    if not image.ready:
        checks.append(Check("ready", False, "image has no validated tags/embedding yet"))
        reasons.append("Image has not been analysed yet")
        return Verdict(False, checks, reasons, "Rejected: " + reasons[0])
    checks.append(Check("ready", True, "image has validated tags and an embedding"))

    # 2 post: an uncertain or subject-less post analysis can't define what to look for
    has_subject = bool(post.subject) and post.subject.strip().lower() not in NO_SUBJECT
    post_conf_ok = post.confidence is None or post.confidence >= cfg.min_confidence
    if not has_subject:
        checks.append(Check("post", False, "post analysis found no visual subject"))
        reasons.append("Post has no identifiable visual subject; it needs a human to pick the image")
    elif not post_conf_ok:
        checks.append(Check("post", False, "post analysis is uncertain", post.confidence, cfg.min_confidence))
        reasons.append(
            f"Post analysis is uncertain ({post.confidence:.2f} < {cfg.min_confidence:.2f}); "
            "its subject needs review"
        )
    else:
        detail = "subject given" if post.confidence is None else f"confidence {post.confidence:.2f}"
        checks.append(Check("post", True, detail, post.confidence, cfg.min_confidence))

    # 3 confidence (a flagged image is never recommended)
    conf_ok = image.confidence >= cfg.min_confidence and not image.needs_review
    if conf_ok:
        detail = f"confidence {image.confidence:.2f} >= {cfg.min_confidence:.2f}"
    else:
        why = "; ".join(image.review_reasons) or f"confidence {image.confidence:.2f} < {cfg.min_confidence:.2f}"
        detail = f"image is flagged for review: {why}"
        reasons.append(f"Low-confidence image ({image.confidence:.2f}): flagged for review ({why})")
    checks.append(Check("confidence", conf_ok, detail, image.confidence, cfg.min_confidence))

    # 4 category
    category_ok = not post.category or post.category == image.category
    if category_ok:
        checks.append(Check("category", True, f"both are '{image.category}'"))
    else:
        checks.append(Check("category", False, f"post is '{post.category}', image is '{image.category}'"))
        reasons.append(f"Category mismatch: post is about {post.category}, image shows {image.category}")

    # 5 subject (only meaningful inside the same category)
    if not has_subject:
        checks.append(Check("subject", False, "not compared: post has no subject"))
    elif not category_ok:
        checks.append(Check("subject", False, "not compared: categories differ", scores.subject_similarity))
    else:
        ok, how = subject_match(post.subject, image, scores.subject_similarity, cfg.subject_sim_threshold)
        checks.append(Check("subject", ok, how, scores.subject_similarity, cfg.subject_sim_threshold))
        if not ok:
            label = (image.category or "subject").capitalize()
            reasons.append(f"{label} category mismatch: expected {post.subject}, detected {image.subject}")

    # 6 similarity (NaN from a broken vector never passes)
    sim_ok = scores.similarity >= cfg.similarity_threshold
    checks.append(
        Check(
            "similarity",
            sim_ok,
            f"{scores.similarity:.2f} {'>=' if sim_ok else '<'} threshold {cfg.similarity_threshold:.2f}",
            round(scores.similarity, 4),
            cfg.similarity_threshold,
        )
    )
    if not sim_ok:
        reasons.append(f"Similarity {scores.similarity:.2f} is below the threshold {cfg.similarity_threshold:.2f}")

    accepted = not reasons
    if accepted:
        how = next(c.detail for c in checks if c.name == "subject")
        explanation = (
            f"Accepted: '{image.subject}' fits the post ({how}); similarity {scores.similarity:.2f} "
            f">= {cfg.similarity_threshold:.2f}; confidence {image.confidence:.2f}"
        )
    else:
        explanation = "Rejected: " + "; ".join(reasons)
    return Verdict(accepted, checks, reasons, explanation)


def no_match_reasons(post: PostFacts, verdicts: list[tuple[ImageFacts, Scores, Verdict]], cfg: GuardConfig) -> list[str]:
    """Why nothing cleared the bar, summarised across the ranked candidates."""
    if not verdicts:
        return ["No analysed images are available to match against"]
    reasons: list[str] = [f"None of the {len(verdicts)} closest images passed every guard check"]
    post_check = verdicts[0][2].check("post")
    if not post_check.passed:
        reasons.append(verdicts[0][2].reasons[0])
        return reasons
    best_image, best_scores, _ = max(verdicts, key=lambda v: v[1].similarity)
    if best_scores.similarity < cfg.similarity_threshold:
        reasons.append(
            f"Similarity below threshold: the best candidate ('{best_image.subject}') scores "
            f"{best_scores.similarity:.2f} < {cfg.similarity_threshold:.2f}"
        )
    if post.subject and post.subject.lower() not in NO_SUBJECT:
        subject_ok = [img for img, _, v in verdicts if v.check("subject").passed]
        if not subject_ok:
            seen = list(dict.fromkeys(img.subject for img, _, _ in verdicts if img.subject))[:4]
            reasons.append(
                f"Subjects don't match: no candidate shows '{post.subject}' (closest: {', '.join(seen)})"
            )
    flagged = [img for img, _, v in verdicts if not v.check("confidence").passed and v.check("subject").passed]
    if flagged:
        reasons.append(
            f"{len(flagged)} candidate(s) with the right subject are flagged low-confidence and need review"
        )
    if len(reasons) == 1:  # every candidate failed a mix of checks
        reasons.append("Every candidate failed at least one guard check (see candidates for details)")
    return reasons
