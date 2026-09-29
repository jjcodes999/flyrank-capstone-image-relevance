"""Processing for one image job item: vision tags, then embeddings."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image as PILImage
from sqlalchemy.orm import Session

from app.ai.ollama import AIClient
from app.config import Settings
from app.errors import NotFound
from app.models import Image, ImageMetadata
from app.repositories.embeddings import EmbeddingRepository
from app.repositories.images import ImageRepository
from app.services.costs import CallContext, CostTracker
from app.services.embeddings import EmbeddingService, image_embedding_text
from app.services.vision import PROMPT_VERSION, VisionService, review_reasons, sharpness


class PermanentItemError(Exception):
    """Retrying will not help (missing file, invalid model output after retries)."""


class ImagePipeline:
    def __init__(self, session: Session, client: AIClient, costs: CostTracker, settings: Settings) -> None:
        self.s = session
        self.images = ImageRepository(session)
        self.embeddings = EmbeddingRepository(session)
        self.vision = VisionService(client, costs, settings)
        self.embedder = EmbeddingService(client, costs, settings)
        self.settings = settings

    def is_current(self, image: Image) -> bool:
        """True when stored tags came from this exact file, model and prompt version."""
        meta = image.meta
        return (
            meta is not None
            and meta.model == self.settings.vision_model
            and meta.prompt_version == PROMPT_VERSION
            and meta.source_sha256 == image.sha256
        )

    def process(self, tenant_id: int, image_id: int, ctx: CallContext, force: bool) -> str:
        image = self.images.get(tenant_id, image_id)
        if image is None:
            raise NotFound(f"image {image_id} not found")

        path = Path(self.settings.images_dir) / image.filename
        if not path.is_file():
            raise PermanentItemError(f"image file missing: {path}")
        data = path.read_bytes()
        image.sha256 = hashlib.sha256(data).hexdigest()

        did_work = False
        if force or not self.is_current(image):
            self._tag(image, data, ctx)
            # a vision call takes minutes on CPU: keep its result even if embedding fails,
            # so a retry resumes at the embedding step instead of re-tagging
            self.s.commit()
            did_work = True

        # needs_review images are embedded too, so they can still be inspected/force-checked
        assert image.meta is not None
        text = image_embedding_text(image.meta)
        current = self.embeddings.get_image(image.id)
        if force or current is None or current.text != text or current.model != self.settings.embed_model:
            vec, subject_vec = self.embedder.embed_pair(text, image.meta.subject, ctx)
            self.embeddings.upsert_image(tenant_id, image.id, self.settings.embed_model, text, vec, subject_vec)
            did_work = True
        return "done" if did_work else "skipped"

    def _tag(self, image: Image, data: bytes, ctx: CallContext) -> None:
        img = PILImage.open(io.BytesIO(data))
        img.load()
        sharp = sharpness(img)
        result = self.vision.tag(img, ctx)  # raises InvalidModelOutput / OllamaError / BudgetExceeded
        tags = result.value
        reasons = review_reasons(tags, sharp, self.settings)

        meta = ImageMetadata(
            subject=tags.subject,
            category=tags.category,
            attributes=tags.attributes,
            caption=tags.caption,
            confidence=tags.confidence,
            needs_review=bool(reasons),
            review_reasons=reasons,
            sharpness=round(sharp, 2),
            model=self.settings.vision_model,
            prompt_version=PROMPT_VERSION,
            source_sha256=image.sha256,
            raw_response=result.raw,
            validation_attempts=result.attempts,
        )
        tag_rows = [(tags.subject, "subject"), (tags.category, "category")]
        tag_rows += [(a, "attribute") for a in tags.attributes]
        self.images.save_metadata(image, meta, tag_rows)
        image.status = "needs_review" if reasons else "tagged"
        image.error = None

    def mark_failed(self, tenant_id: int, image_id: int, error: str) -> None:
        image = self.images.get(tenant_id, image_id)
        if image is not None:
            image.status = "failed"
            image.error = error[:2000]
