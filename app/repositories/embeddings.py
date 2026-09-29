from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Image, ImageEmbedding, PostEmbedding


@dataclass(frozen=True)
class RankedRow:
    image: Image
    similarity: float
    subject_similarity: float


class EmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def upsert_image(
        self, tenant_id: int, image_id: int, model: str, text: str, vec: list[float], subject_vec: list[float]
    ) -> None:
        row = self.s.scalar(select(ImageEmbedding).where(ImageEmbedding.image_id == image_id))
        if row is None:
            row = ImageEmbedding(image_id=image_id, tenant_id=tenant_id)
            self.s.add(row)
        row.model, row.text, row.embedding, row.subject_embedding = model, text, vec, subject_vec
        self.s.flush()

    def upsert_post(self, post_id: int, model: str, text: str, vec: list[float], subject_vec: list[float]) -> None:
        row = self.s.scalar(select(PostEmbedding).where(PostEmbedding.post_id == post_id))
        if row is None:
            row = PostEmbedding(post_id=post_id)
            self.s.add(row)
        row.model, row.text, row.embedding, row.subject_embedding = model, text, vec, subject_vec
        self.s.flush()

    def get_image(self, image_id: int) -> ImageEmbedding | None:
        return self.s.scalar(select(ImageEmbedding).where(ImageEmbedding.image_id == image_id))

    def get_post(self, post_id: int) -> PostEmbedding | None:
        return self.s.scalar(select(PostEmbedding).where(PostEmbedding.post_id == post_id))

    def rank_images(
        self, tenant_id: int, post_vec: list[float], post_subject_vec: list[float], limit: int,
        image_id: int | None = None,
    ) -> list[RankedRow]:
        """Images closest to the post by cosine distance (served by the HNSW index)."""
        dist = ImageEmbedding.embedding.cosine_distance(post_vec)
        subject_dist = ImageEmbedding.subject_embedding.cosine_distance(post_subject_vec)
        q = (
            select(Image, (1 - dist).label("sim"), (1 - subject_dist).label("subject_sim"))
            .join(ImageEmbedding, ImageEmbedding.image_id == Image.id)
            .where(ImageEmbedding.tenant_id == tenant_id)
            .options(selectinload(Image.meta))
            .order_by(dist)
            .limit(limit)
        )
        if image_id is not None:
            q = q.where(Image.id == image_id)
        return [RankedRow(img, float(sim), float(ssim)) for img, sim, ssim in self.s.execute(q)]
