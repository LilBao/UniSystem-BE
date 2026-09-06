from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class UploadArtifactKind(StrEnum):
    REPORT_PDF = "report_pdf"
    SOURCE_ARCHIVE = "source_archive"


class CloudinaryUploadResponse(BaseModel):
    provider: str = "cloudinary"
    submission_id: UUID
    kind: UploadArtifactKind
    asset_id: str
    public_id: str
    resource_type: str
    delivery_type: str
    object_uri: str
    secure_url: str
    original_filename: str
    media_type: str
    byte_size: int
    sha256: str
