from uuid import UUID

from pydantic import BaseModel


class PipelineRunResponse(BaseModel):
    id: UUID
    submission_id: UUID
    pipeline: str
    status: str
    input_fingerprint: str
    attempt_no: int
