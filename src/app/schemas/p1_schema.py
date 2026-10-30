from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ScoringMethod(StrEnum):
    ZERO_SHOT = "zero_shot"
    FEW_SHOT = "few_shot"
    G_EVAL = "geval"


class P1ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REQUIRES_REVIEW = "requires_review"
    FAILED = "failed"


class CriterionEvidenceItem(BaseModel):
    block_id: UUID | None = None
    claim_id: UUID | None = None
    text: str = Field(min_length=1)
    section_title: str | None = None
    page_no: int | None = None
    block_type: str = "text"
    relevance_score: float | None = None


class CriterionEvidencePack(BaseModel):
    criterion_id: UUID
    criterion_code: str
    criterion_title: str
    criterion_description: str
    grading_rules: dict[str, Any] = Field(default_factory=dict)
    min_score: float = 0.0
    max_score: float = 10.0
    weight: float = 1.0
    evidence_items: list[CriterionEvidenceItem] = Field(default_factory=list)
    synthesized_context: str = ""


class SingleScoreRun(BaseModel):
    run_index: int = Field(ge=1)
    raw_score: float
    normalized_score: float = Field(ge=0.0, le=1.0)
    cot_steps: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    cited_evidence: list[str] = Field(default_factory=list)


class CriterionScoringResult(BaseModel):
    criterion_id: UUID
    criterion_code: str
    criterion_title: str
    weight: float
    min_score: float
    max_score: float
    scoring_method: ScoringMethod
    runs: list[SingleScoreRun] = Field(default_factory=list)
    mean_raw_score: float
    mean_normalized_score: float = Field(ge=0.0, le=1.0)
    variance: float = Field(default=0.0, ge=0.0)
    std_dev: float = Field(default=0.0, ge=0.0)
    uncertainty_flag: bool = False
    consensus_rationale: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)


class Pipeline1DetailResult(BaseModel):
    submission_id: UUID
    rubric_version_id: UUID
    pipeline_run_id: UUID
    status: str
    scoring_method: ScoringMethod
    total_raw_score: float
    total_max_score: float
    total_normalized_score: float = Field(ge=0.0, le=1.0)
    mean_variance: float = Field(default=0.0, ge=0.0)
    requires_human_review: bool = False
    executive_summary: str
    criteria_results: list[CriterionScoringResult] = Field(default_factory=list)


class Pipeline1Config(BaseModel):
    scoring_method: ScoringMethod = ScoringMethod.G_EVAL
    num_runs: int = Field(default=3, ge=1, le=10)
    variance_threshold: float = Field(default=0.15, ge=0.0)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
