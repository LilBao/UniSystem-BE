from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.submission_repository import SubmissionRepository
from app.schemas.artifact_schema import ArtifactCreate, ArtifactResponse
from app.schemas.submission_schema import SubmissionCreate, SubmissionResponse


class SubmissionService:
    def __init__(self, repository: SubmissionRepository) -> None:
        self.repository = repository

    async def create_submission(
        self, data: SubmissionCreate, idempotency_key: str | None
    ) -> SubmissionResponse:
        if idempotency_key:
            existing = await self.repository.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                same_request = all(
                    getattr(existing, field) == value
                    for field, value in data.model_dump().items()
                )
                if not same_request:
                    raise AppError(
                        ErrorCode.CONFLICT,
                        "Idempotency-Key was already used for a different request",
                    )
                return SubmissionResponse.model_validate(existing, from_attributes=True)

        if not await self.repository.check_project_is_open(data.project_id):
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "Project không mở")
        if not await self.repository.check_rubric_is_published(data.rubric_version_id):
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION, "Rubric chưa publish")
        if not await self.repository.check_user_in_group(
            group_id=data.group_id,
            user_id=data.submitted_by_user_id,
        ):
            raise AppError(ErrorCode.FORBIDDEN, "User không thuộc group")

        values = data.model_dump()
        values["idempotency_key"] = idempotency_key
        try:
            entity = await self.repository.create(values)
        except IntegrityError as exc:
            raise AppError(ErrorCode.DUPLICATE_RESOURCE) from exc
        return SubmissionResponse.model_validate(entity, from_attributes=True)

    async def register_artifact(
        self, submission_id: UUID, data: ArtifactCreate
    ) -> ArtifactResponse:
        submission = await self.repository.get(submission_id)
        if submission is None:
            raise AppError(ErrorCode.SUBMISSION_NOT_FOUND)
        if submission.status != "uploaded":
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "Submission no longer accepts source artifacts",
            )
        values = data.model_dump()
        values["submission_id"] = submission_id
        try:
            entity = await self.repository.create_artifact(values)
        except IntegrityError as exc:
            raise AppError(ErrorCode.DUPLICATE_RESOURCE) from exc
        return ArtifactResponse(
            id=entity.id,
            submission_id=entity.submission_id,
            kind=entity.kind,
            version_no=entity.version_no,
            object_uri=entity.object_uri,
            media_type=entity.media_type,
            byte_size=entity.byte_size,
            sha256=entity.sha256,
            metadata=entity.metadata_json,
        )
