import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.dependencies import get_layer1_service, get_submission_service
from app.schemas.artifact_schema import ArtifactCreate, ArtifactResponse
from app.schemas.pipeline_schema import PipelineRunResponse
from app.schemas.submission_schema import SubmissionCreate, SubmissionResponse
from app.services.layer1_service import Layer1Service
from app.services.submission_service import SubmissionService

router = APIRouter(prefix="/api/v1/submissions", tags=["Submissions"])
logger = logging.getLogger("uvicorn.error")


@router.post("", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    body: SubmissionCreate,
    service: Annotated[SubmissionService, Depends(get_submission_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmissionResponse:
    return await service.create_submission(body, idempotency_key)


@router.post(
    "/{submission_id}/artifacts",
    response_model=ArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_artifact(
    submission_id: UUID,
    body: ArtifactCreate,
    service: Annotated[SubmissionService, Depends(get_submission_service)],
) -> ArtifactResponse:
    return await service.register_artifact(submission_id, body)


@router.post("/{submission_id}/submit", response_model=PipelineRunResponse)
async def submit_submission(
    submission_id: UUID,
    service: Annotated[Layer1Service, Depends(get_layer1_service)],
) -> PipelineRunResponse:
    logger.info("Layer 1 request received: submission_id=%s", submission_id)
    return await service.submit(submission_id)
