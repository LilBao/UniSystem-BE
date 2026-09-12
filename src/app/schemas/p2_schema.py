from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CitationVerdict(StrEnum):
    SUPPORT = "SUPPORT"
    REFUTE = "REFUTE"
    NEI = "NEI"


class VerificationStage(StrEnum):
    LOCAL = "LOCAL"
    ABSTRACT = "ABSTRACT"


class CitationResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REQUIRES_REVIEW = "requires_review"
    ABSTAINED = "abstained"
    FAILED = "failed"


class CitationVerificationInput(BaseModel):
    claim_id: UUID
    text_content: str = Field(min_length=1)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    citation_marker: str = Field(min_length=1)
    submission_reference_id: UUID
    reference_document_id: UUID | None = None


class CitationEvidence(BaseModel):
    source_type: str = Field(min_length=1)
    source_id: UUID
    text: str = Field(min_length=1)
    location: dict[str, Any] = Field(default_factory=dict)
    access_status: str | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CitationVerificationResult(BaseModel):
    claim_id: UUID
    verdict: CitationVerdict | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: CitationResultStatus
    verification_stage: VerificationStage
    requires_review: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[CitationEvidence] = Field(default_factory=list)
    rationale: str | None = None


class CitationWorkItem(BaseModel):
    input: CitationVerificationInput
    evidence: list[CitationEvidence] = Field(default_factory=list)
