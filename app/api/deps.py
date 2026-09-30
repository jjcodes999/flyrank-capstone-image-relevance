from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import NotFound
from app.models import Tenant
from app.repositories.tenants import TenantRepository

DB = Annotated[Session, Depends(get_db)]

# pagination offsets beyond this are rejected with 422 (PostgreSQL can't take huge ints)
MAX_OFFSET = 100_000


def get_tenant(
    db: DB,
    x_tenant_id: Annotated[
        str, Header(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$", description="Tenant slug; defaults to the demo tenant")
    ] = get_settings().default_tenant,
) -> Tenant:
    tenant = TenantRepository(db).get_by_slug(x_tenant_id)
    if tenant is None:
        raise NotFound(f"unknown tenant '{x_tenant_id}'")
    return tenant


CurrentTenant = Annotated[Tenant, Depends(get_tenant)]
