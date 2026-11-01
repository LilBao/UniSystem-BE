from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies import (
    get_reference_resolution_service,
)
from app.services.layer2.pipeline2.reference_resolution_service import (
    ReferenceResolutionService,
)

router = APIRouter(
    prefix="/api/v1/submissions",
    tags=["References"],
)


@router.post("/{submission_id}/references/resolve")
async def resolve_references(
    submission_id: UUID,
    service: Annotated[
        ReferenceResolutionService,
        Depends(get_reference_resolution_service),
    ],
) -> dict[str, int]:
    return await service.resolve_submission(submission_id)
