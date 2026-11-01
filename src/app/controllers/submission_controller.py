import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from app.core.authorization import AuthenticatedUser
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.dependencies import (
    get_layer1_service,
    get_optional_current_user,
    get_submission_service,
)
from app.schemas.artifact_schema import ArtifactCreate, ArtifactResponse
from app.schemas.pipeline_schema import PipelineRunResponse
from app.schemas.submission_schema import SubmissionCreate, SubmissionResponse
from app.services.common.submission_service import SubmissionService
from app.services.layer1.layer1_service import Layer1Service

router = APIRouter(prefix="/api/v1/submissions", tags=["Submissions"])
logger = logging.getLogger("uvicorn.error")


@router.post("", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    body: SubmissionCreate,
    service: Annotated[SubmissionService, Depends(get_submission_service)],
    current_user: Annotated[
        AuthenticatedUser | None,
        Depends(get_optional_current_user),
    ] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SubmissionResponse:
    if (
        current_user is not None
        and not current_user.is_admin
        and body.submitted_by_user_id != current_user.id
    ):
        raise AppError(
            ErrorCode.FORBIDDEN,
            "submitted_by_user_id must match the authenticated user",
        )
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
    _current_user: Annotated[
        AuthenticatedUser | None,
        Depends(get_optional_current_user),
    ] = None,
) -> ArtifactResponse:
    return await service.register_artifact(submission_id, body)


@router.post("/{submission_id}/submit", response_model=PipelineRunResponse)
async def submit_submission(
    submission_id: UUID,
    service: Annotated[Layer1Service, Depends(get_layer1_service)],
    _current_user: Annotated[
        AuthenticatedUser | None,
        Depends(get_optional_current_user),
    ] = None,
) -> PipelineRunResponse:
    logger.info("Layer 1 request received: submission_id=%s", submission_id)
    return await service.submit(submission_id)
