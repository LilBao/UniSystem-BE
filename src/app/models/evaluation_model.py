from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ClaimReference(Base):
    __tablename__ = "claim_references"
    __table_args__ = (PrimaryKeyConstraint("claim_id", "submission_reference_id"),)

    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"))
    submission_reference_id: Mapped[UUID] = mapped_column(
        ForeignKey("submission_references.id")
    )


class PipelineResult(CreatedAtMixin, Base):
    __tablename__ = "pipeline_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.id"))
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    reason_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )
    escalation_history: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class EvidencePack(CreatedAtMixin, Base):
    __tablename__ = "evidence_packs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"))
    claim_id: Mapped[UUID | None] = mapped_column(ForeignKey("claims.id"))
    rubric_criterion_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rubric_criteria.id")
    )
    pipeline_run_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_runs.id"))
    coverage: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[str] = mapped_column(Text)


class EvidenceItem(CreatedAtMixin, Base):
    __tablename__ = "evidence_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    evidence_pack_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_packs.id"))
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[UUID | None]
    source_uri: Mapped[str | None] = mapped_column(Text)
    text_snapshot: Mapped[str | None] = mapped_column(Text)
    location: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    provenance: Mapped[str] = mapped_column(Text)
    retrieval_score: Mapped[float | None]
    rerank_score: Mapped[float | None]
    supports_atoms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )
    contradicts_atoms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )
    access_status: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(Text)


class PipelineResultEvidence(Base):
    __tablename__ = "pipeline_result_evidence"
    __table_args__ = (PrimaryKeyConstraint("pipeline_result_id", "evidence_item_id"),)

    pipeline_result_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_results.id"))
    evidence_item_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_items.id"))
    usage: Mapped[str] = mapped_column(Text, server_default="support")


class RubricCriterionScore(CreatedAtMixin, Base):
    __tablename__ = "rubric_criterion_scores"
    __table_args__ = (
        UniqueConstraint("pipeline_result_id", "rubric_criterion_id", "run_index"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_result_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_results.id"))
    rubric_criterion_id: Mapped[UUID] = mapped_column(ForeignKey("rubric_criteria.id"))
    run_index: Mapped[int] = mapped_column(server_default="1")
    raw_score: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    normalized_score: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    rationale: Mapped[str] = mapped_column(Text)
    variance: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))


class CitationVerdict(CreatedAtMixin, Base):
    __tablename__ = "citation_verdicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_results.id"), unique=True
    )
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"))
    verdict: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    pair_accuracy_label: Mapped[bool | None]
    requires_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class CodeConsistencyVerdict(CreatedAtMixin, Base):
    __tablename__ = "code_consistency_verdicts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_results.id"), unique=True
    )
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claims.id"))
    graph_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_graph_snapshots.id")
    )
    verdict: Mapped[str] = mapped_column(Text)
    verification_stage: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    requires_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class AISignal(CreatedAtMixin, Base):
    __tablename__ = "ai_signals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pipeline_result_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_results.id"), unique=True
    )
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"))
    language: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text)
    raw_score: Mapped[float]
    level: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    uncertainty: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    threshold_profile: Mapped[str] = mapped_column(Text)
    detector_version: Mapped[str] = mapped_column(Text)
    stylometric_signals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    segment_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("ARRAY[]::uuid[]")
    )
    requires_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    academic_score_effect: Mapped[Decimal] = mapped_column(
        Numeric(8, 3), server_default="0"
    )
    disclaimer: Mapped[str] = mapped_column(
        Text,
        server_default="Review-only evidence signal; not a misconduct verdict.",
    )


class FinalEvaluation(CreatedAtMixin, Base):
    __tablename__ = "final_evaluations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"), unique=True)
    rubric_version_id: Mapped[UUID] = mapped_column(ForeignKey("rubric_versions.id"))
    policy_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    academic_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    citation_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    consistency_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    integrity_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    explanation: Mapped[str | None] = mapped_column(Text)
    evidence_coverage: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeedbackItem(CreatedAtMixin, Base):
    __tablename__ = "feedback_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    final_evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("final_evaluations.id"))
    audience: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    claim_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("ARRAY[]::uuid[]")
    )
    evidence_item_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("ARRAY[]::uuid[]")
    )
    ordinal: Mapped[int] = mapped_column(server_default="0")


class HumanOverride(CreatedAtMixin, Base):
    __tablename__ = "human_overrides"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    final_evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("final_evaluations.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID | None]
    before_value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    after_value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
