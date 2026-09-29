from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Post


class PostRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get(self, tenant_id: int, post_id: int) -> Post | None:
        return self.s.scalar(select(Post).where(Post.tenant_id == tenant_id, Post.id == post_id))

    def get_by_slug(self, tenant_id: int, slug: str) -> Post | None:
        return self.s.scalar(select(Post).where(Post.tenant_id == tenant_id, Post.slug == slug))

    def list(self, tenant_id: int, status: str | None = None, limit: int = 100, offset: int = 0) -> list[Post]:
        q = select(Post).where(Post.tenant_id == tenant_id)
        if status:
            q = q.where(Post.status == status)
        return list(self.s.scalars(q.order_by(Post.id).limit(limit).offset(offset)))

    def ids(self, tenant_id: int) -> list[int]:
        return list(self.s.scalars(select(Post.id).where(Post.tenant_id == tenant_id).order_by(Post.id)))

    def add(self, post: Post) -> Post:
        self.s.add(post)
        self.s.flush()
        return post
