"""Post analysis: turn a blog post into a common-name subject + summary, then embed it.

Why: all-minilm alone scores "Vulpes vulpes" vs "red fox" at 0.26 (the same as vs
"gray wolf"). The language model knows the scientific name, so it normalises the post
first; the embedding then compares like with like.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from app.ai.ollama import AIClient
from app.config import Settings
from app.errors import NotFound
from app.models import Post
from app.repositories.embeddings import EmbeddingRepository
from app.repositories.posts import PostRepository
from app.schemas.ai import PostAnalysis
from app.services.costs import CallContext, CostTracker
from app.services.embeddings import EmbeddingService, post_embedding_text
from app.services.structured import StructuredResult, call_structured

POST_PROMPT_VERSION = "p1"

SYSTEM_PROMPT = (
    "You read blog posts and describe the photo that should illustrate them. Answer with JSON only.\n"
    "subject: the main thing the photo should show, as a short lowercase common English name, as "
    "specific as the post is (e.g. 'red fox', 'gray wolf', 'steam locomotive', 'sushi'). Translate "
    "scientific or foreign names into the common English name. Use 'none' if the post has no visual subject.\n"
    "category: one of animal, vehicle, food, nature, person, object, other.\n"
    "concepts: 3 to 6 related words or short phrases in plain English.\n"
    "summary: one plain English sentence about the post, using common names only.\n"
    "confidence: probability from 0 to 1 that the subject is right."
)


def content_sha(post: Post) -> str:
    return hashlib.sha256(f"{post.title}\n{post.body}".encode()).hexdigest()


class PostAnalyzer:
    def __init__(self, client: AIClient, costs: CostTracker, settings: Settings) -> None:
        self._client, self._costs, self._settings = client, costs, settings

    def analyze(self, title: str, body: str, ctx: CallContext) -> StructuredResult[PostAnalysis]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Title: {title}\n\n{body}"},
        ]
        return call_structured(
            self._client, self._costs, ctx,
            operation="post_analysis", model=self._settings.vision_model, messages=messages,
            schema=PostAnalysis, max_retries=self._settings.vision_max_retries,
        )


class PostPipeline:
    def __init__(self, session: Session, client: AIClient, costs: CostTracker, settings: Settings) -> None:
        self.s = session
        self.posts = PostRepository(session)
        self.embeddings = EmbeddingRepository(session)
        self.analyzer = PostAnalyzer(client, costs, settings)
        self.embedder = EmbeddingService(client, costs, settings)
        self.settings = settings

    def analysis_is_current(self, post: Post) -> bool:
        return (
            post.subject is not None
            and post.analysis_model == self.settings.vision_model
            and post.analysis_prompt_version == POST_PROMPT_VERSION
            and post.analysis_source_sha256 == content_sha(post)
        )

    def process(
        self, tenant_id: int, post_id: int, ctx: CallContext, force_since: datetime | None = None
    ) -> str:
        """Analyse + embed one post. With force_since, redo what wasn't already redone since then."""
        post = self.posts.get(tenant_id, post_id)
        if post is None:
            raise NotFound(f"post {post_id} not found")
        did_work = False

        forced = force_since is not None and post.updated_at < force_since
        if forced or not self.analysis_is_current(post):
            result = self.analyzer.analyze(post.title, post.body, ctx)
            a = result.value
            post.subject, post.category, post.concepts, post.summary = a.subject, a.category, a.concepts, a.summary
            post.analysis_confidence = a.confidence
            post.analysis_model = self.settings.vision_model
            post.analysis_prompt_version = POST_PROMPT_VERSION
            post.analysis_source_sha256 = content_sha(post)
            # keep a (slow) analysis even if the embedding call below fails
            self.s.commit()
            did_work = True

        text = post_embedding_text(post)
        current = self.embeddings.get_post(post.id)
        stale = current is None or current.text != text or current.model != self.settings.embed_model
        if stale or (force_since is not None and current.created_at < force_since):
            vec, subject_vec = self.embedder.embed_pair(text, post.subject or "", ctx)
            self.embeddings.upsert_post(post.id, self.settings.embed_model, text, vec, subject_vec)
            did_work = True

        post.status = "ready"
        post.error = None
        return "done" if did_work else "skipped"

    def mark_failed(self, tenant_id: int, post_id: int, error: str) -> None:
        post = self.posts.get(tenant_id, post_id)
        if post is not None:
            post.status = "failed"
            post.error = error[:2000]
