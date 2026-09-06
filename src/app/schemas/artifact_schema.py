from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.upload_schema import UploadArtifactKind

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ArtifactCreate(BaseModel):
    kind: UploadArtifactKind
    version_no: int = Field(default=1, gt=0)
    object_uri: str = Field(min_length=1, max_length=2048)
    media_type: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0)
    sha256: Sha256
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactResponse(ArtifactCreate):
    id: UUID
    submission_id: UUID | None
