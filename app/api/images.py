from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query

from app.api.deps import MAX_OFFSET, DB, CurrentTenant
from app.errors import NotFound
from app.models import IMAGE_STATUSES
from app.repositories.images import ImageRepository
from app.schemas.ai import Category
from app.schemas.api import ImageList, ImageOut

router = APIRouter(prefix="/images", tags=["images"])

ImageStatus = Literal[IMAGE_STATUSES]  # type: ignore[valid-type]


@router.get("", response_model=ImageList)
def list_images(
    db: DB,
    tenant: CurrentTenant,
    status: ImageStatus | None = None,
    needs_review: bool | None = None,
    category: Category | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> ImageList:
    repo = ImageRepository(db)
    items = repo.list(
        tenant.id, status=status, needs_review=needs_review, category=category, limit=limit, offset=offset
    )
    return ImageList(
        count=len(items),
        status_counts=repo.status_counts(tenant.id),
        items=[ImageOut.model_validate(i) for i in items],
    )


@router.get("/{image_id}", response_model=ImageOut)
def get_image(db: DB, tenant: CurrentTenant, image_id: Annotated[int, Path(ge=1)]) -> ImageOut:
    image = ImageRepository(db).get(tenant.id, image_id)
    if image is None:
        raise NotFound(f"image {image_id} not found")
    return ImageOut.model_validate(image)
