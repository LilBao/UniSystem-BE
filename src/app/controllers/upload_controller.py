from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.dependencies import get_file_upload_service
from app.schemas.upload_schema import CloudinaryUploadResponse, UploadArtifactKind
from app.services.file_upload_service import FileUploadService

router = APIRouter(prefix="/api/v1/submissions", tags=["Submission files"])


@router.post(
    "/{submission_id}/files",
    response_model=CloudinaryUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_submission_file(
    submission_id: UUID,
    kind: Annotated[UploadArtifactKind, Form()],
    file: Annotated[UploadFile, File()],
    service: Annotated[FileUploadService, Depends(get_file_upload_service)],
) -> CloudinaryUploadResponse:
    return await service.upload_submission_file(submission_id, kind, file)
