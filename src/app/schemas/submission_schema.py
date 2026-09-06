from uuid import UUID

from pydantic import BaseModel, Field


class SubmissionCreate(BaseModel):
    project_id: UUID
    group_id: UUID
    submitted_by_user_id: UUID
    rubric_version_id: UUID
    attempt_no: int = Field(default=1, gt=0)


class SubmissionResponse(SubmissionCreate):
    id: UUID
    status: str
