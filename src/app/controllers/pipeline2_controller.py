from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies import get_pipeline2_service
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.pipeline2_service import Pipeline2Service

router = APIRouter(prefix="/api/v1/submissions", tags=["Pipeline 2"])


@router.post("/{submission_id}/pipelines/p2", response_model=PipelineRunResponse)
async def run_pipeline2(
    submission_id: UUID,
    service: Annotated[Pipeline2Service, Depends(get_pipeline2_service)],
) -> PipelineRunResponse:
    return await service.run(submission_id)
