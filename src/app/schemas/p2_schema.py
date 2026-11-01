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
    FULL_TEXT = "FULL_TEXT"
    TABLE_FIGURE = "TABLE_FIGURE"


class CitationResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REQUIRES_REVIEW = "requires_review"
    ABSTAINED = "abstained"
    FAILED = "failed"


class CitationVerificationInput(BaseModel):
    claim_id: UUID
    text_content: str = Field(min_length=1)
    is_atomic: bool = False
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
    retrieval_score: float | None = None
    rerank_score: float | None = None


class AtomicClaim(BaseModel):
    """One independently verifiable assertion derived from a Layer 1 claim."""

    atom_id: str = Field(min_length=1, max_length=64)
    text_content: str = Field(min_length=1)
    qualifiers: dict[str, Any] = Field(default_factory=dict)


class AtomAssessment(BaseModel):
    atom_id: str = Field(min_length=1, max_length=64)
    verdict: CitationVerdict
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    supporting_evidence_ids: list[UUID] = Field(default_factory=list)
    contradicting_evidence_ids: list[UUID] = Field(default_factory=list)


class CitationVerificationResult(BaseModel):
    claim_id: UUID
    verdict: CitationVerdict | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: CitationResultStatus
    verification_stage: VerificationStage
    requires_review: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[CitationEvidence] = Field(default_factory=list)
    atomic_claims: list[AtomicClaim] = Field(default_factory=list)
    atom_assessments: list[AtomAssessment] = Field(default_factory=list)
    stage_history: list[VerificationStage] = Field(default_factory=list)
    rationale: str | None = None


class CitationWorkItem(BaseModel):
    input: CitationVerificationInput
    evidence: list[CitationEvidence] = Field(default_factory=list)
