from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant


class TenantRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self.s.scalar(select(Tenant).where(Tenant.slug == slug))

    def get_or_create(self, slug: str, name: str | None = None) -> Tenant:
        tenant = self.get_by_slug(slug)
        if tenant is None:
            tenant = Tenant(slug=slug, name=name or slug)
            self.s.add(tenant)
            self.s.flush()
        return tenant
