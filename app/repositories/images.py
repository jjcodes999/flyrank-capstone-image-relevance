from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Image, ImageMetadata, ImageTag


class ImageRepository:
    """All image queries. Every read is scoped to one tenant."""

    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, tenant_id: int, image_id: int) -> Image | None:
        return self.s.scalar(
            select(Image)
            .where(Image.tenant_id == tenant_id, Image.id == image_id)
            .options(selectinload(Image.meta), selectinload(Image.tags))
        )

    def get_by_filename(self, tenant_id: int, filename: str) -> Image | None:
        return self.s.scalar(select(Image).where(Image.tenant_id == tenant_id, Image.filename == filename))

    def list(
        self,
        tenant_id: int,
        *,
        status: str | None = None,
        needs_review: bool | None = None,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Image]:
        q = select(Image).where(Image.tenant_id == tenant_id).options(selectinload(Image.meta))
        if status:
            q = q.where(Image.status == status)
        if needs_review is not None or category:
            q = q.join(ImageMetadata, ImageMetadata.image_id == Image.id)
            if needs_review is not None:
                q = q.where(ImageMetadata.needs_review.is_(needs_review))
            if category:
                q = q.where(ImageMetadata.category == category)
        return list(self.s.scalars(q.order_by(Image.id).limit(limit).offset(offset)))

    def ids(self, tenant_id: int) -> list[int]:
        return list(self.s.scalars(select(Image.id).where(Image.tenant_id == tenant_id).order_by(Image.id)))

    def status_counts(self, tenant_id: int) -> dict[str, int]:
        rows = self.s.execute(
            select(Image.status, func.count()).where(Image.tenant_id == tenant_id).group_by(Image.status)
        )
        return {status: n for status, n in rows}

    def add(self, image: Image) -> Image:
        self.s.add(image)
        self.s.flush()
        return image

    def save_metadata(self, image: Image, meta: ImageMetadata, tags: list[tuple[str, str]]) -> None:
        """Replace the image's metadata and tags in one go (called inside a transaction)."""
        if image.meta is not None:
            self.s.delete(image.meta)
            self.s.flush()
        self.s.execute(delete(ImageTag).where(ImageTag.image_id == image.id))
        meta.image_id = image.id
        self.s.add(meta)
        for tag, kind in dict.fromkeys(tags):  # keeps order, drops duplicates
            self.s.add(ImageTag(image_id=image.id, tag=tag[:100], kind=kind))
        self.s.flush()
        image.meta = meta
