from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies import get_pipeline1_service
from app.schemas.p1_schema import Pipeline1Config, Pipeline1DetailResult
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.layer2.pipeline1.pipeline1_service import Pipeline1Service

router = APIRouter(prefix="/api/v1/submissions", tags=["Pipeline 1"])


@router.post("/{submission_id}/pipelines/p1", response_model=PipelineRunResponse)
async def run_pipeline1(
    submission_id: UUID,
    service: Annotated[Pipeline1Service, Depends(get_pipeline1_service)],
    config: Pipeline1Config | None = None,
) -> PipelineRunResponse:
    """Kích hoạt chạy Pipeline 1: Tóm tắt & Đánh giá theo Rubric (G-EVAL CoT / Baseline)."""
    return await service.run(submission_id, config=config)


@router.get(
    "/{submission_id}/pipelines/p1/results",
    response_model=Pipeline1DetailResult | None,
)
async def get_pipeline1_results(
    submission_id: UUID,
    service: Annotated[Pipeline1Service, Depends(get_pipeline1_service)],
) -> Pipeline1DetailResult | None:
    """Lấy chi tiết kết quả đánh giá Rubric (điểm từng tiêu chí, phương sai, giải trình, executive summary)."""
    return await service.get_results(submission_id)
