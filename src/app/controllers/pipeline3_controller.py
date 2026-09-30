from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_pipeline3_service
from app.schemas.p3_schema import VisualGraphResponse
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.layer2.pipeline3.pipeline3_service import Pipeline3Service

router = APIRouter(prefix="/api/v1/submissions", tags=["Pipeline 3"])


@router.post("/{submission_id}/pipelines/p3", response_model=PipelineRunResponse)
async def run_pipeline3(
    submission_id: UUID,
    service: Annotated[Pipeline3Service, Depends(get_pipeline3_service)],
) -> PipelineRunResponse:
    """Kích hoạt Pipeline 3: Code-Report Consistency Verification."""
    return await service.run(submission_id)


@router.get("/{submission_id}/pipelines/p3/graph", response_model=VisualGraphResponse)
async def get_pipeline3_graph(
    submission_id: UUID,
    service: Annotated[Pipeline3Service, Depends(get_pipeline3_service)],
    filter_mode: Annotated[
        Literal["all", "mismatches_only", "important_only"],
        Query(alias="filter"),
    ] = "all",
    min_importance: Annotated[
        float,
        Query(ge=0.0, le=1.0),
    ] = 0.0,
) -> VisualGraphResponse:
    """Trả về cấu trúc đồ thị trực quan (Visual Graph) phục vụ Frontend React Flow / Cytoscape."""
    return await service.get_visual_graph(
        submission_id=submission_id,
        filter_mode=filter_mode,
        min_importance=min_importance,
    )
