from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_model import (
    EvidenceItem,
    EvidencePack,
    PipelineResult,
    PipelineResultEvidence,
    RubricCriterionScore,
)
from app.models.layer1_model import Claim, DocumentBlock, DocumentSection
from app.models.pipeline_model import PipelineRun
from app.models.rubric_model import RubricCriterion
from app.models.submission_model import Artifact, Submission
from app.schemas.p1_schema import (
    CriterionEvidencePack,
    CriterionScoringResult,
    Pipeline1DetailResult,
    ScoringMethod,
    SingleScoreRun,
)


class P1Repository:
    """Repository phụ trách truy xuất dữ liệu báo cáo/rubric và lưu trữ kết quả đánh giá Pipeline 1."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_criteria(self, rubric_version_id: UUID) -> list[RubricCriterion]:
        statement = (
            select(RubricCriterion)
            .where(RubricCriterion.rubric_version_id == rubric_version_id)
            .order_by(RubricCriterion.ordinal)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_document_blocks(self, submission_id: UUID) -> list[DocumentBlock]:
        statement = (
            select(DocumentBlock)
            .join(Artifact, Artifact.id == DocumentBlock.artifact_id)
            .where(
                Artifact.submission_id == submission_id,
                Artifact.kind.in_(["report_pdf", "parsed_markdown", "parsed_json"]),
            )
            .order_by(DocumentBlock.page_no, DocumentBlock.reading_order)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_document_sections(self, submission_id: UUID) -> list[DocumentSection]:
        statement = (
            select(DocumentSection)
            .join(Artifact, Artifact.id == DocumentSection.artifact_id)
            .where(Artifact.submission_id == submission_id)
            .order_by(DocumentSection.ordinal)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_claims(self, submission_id: UUID) -> list[Claim]:
        statement = (
            select(Claim)
            .where(Claim.submission_id == submission_id)
            .order_by(Claim.created_at)
        )
        return list((await self.session.scalars(statement)).all())

    async def save_criterion_evaluation(
        self,
        submission_id: UUID,
        pipeline_run_id: UUID,
        pack: CriterionEvidencePack,
        result: CriterionScoringResult,
    ) -> UUID:
        """Lưu EvidencePack, EvidenceItems, PipelineResult, và RubricCriterionScore cho một tiêu chí."""
        # 1. Tạo EvidencePack
        evidence_pack = EvidencePack(
            id=uuid4(),
            submission_id=submission_id,
            claim_id=None,
            rubric_criterion_id=result.criterion_id,
            pipeline_run_id=pipeline_run_id,
            coverage={
                "criterion_code": result.criterion_code,
                "evidence_count": len(pack.evidence_items),
                "synthesized_length": len(pack.synthesized_context),
                "scoring_method": result.scoring_method.value,
            },
            created_by="pipeline-p1",
        )
        self.session.add(evidence_pack)
        await self.session.flush()

        # 2. Tạo EvidenceItems
        evidence_item_models: list[EvidenceItem] = []
        for item in pack.evidence_items:
            item_id = uuid4()
            evidence_item_models.append(
                EvidenceItem(
                    id=item_id,
                    evidence_pack_id=evidence_pack.id,
                    source_type="submission_block" if item.block_id else "other",
                    source_id=item.block_id or item.claim_id,
                    source_uri=None,
                    text_snapshot=item.text,
                    location={
                        "page_no": item.page_no,
                        "section_title": item.section_title,
                        "block_type": item.block_type,
                    },
                    provenance="extracted" if item.claim_id else "parsed",
                    retrieval_score=item.relevance_score,
                    rerank_score=None,
                    supports_atoms=[],
                    contradicts_atoms=[],
                    access_status=None,
                    content_sha256=None,
                )
            )
        self.session.add_all(evidence_item_models)
        await self.session.flush()

        # 3. Tạo PipelineResult
        reason_codes = []
        if result.uncertainty_flag:
            reason_codes.append("HIGH_VARIANCE")
        if result.mean_normalized_score < 0.5:
            reason_codes.append("LOW_CRITERION_SCORE")

        confidence_val = Decimal(str(round(max(0.0, 1.0 - min(1.0, result.variance)), 4)))

        pipeline_result = PipelineResult(
            id=uuid4(),
            pipeline_run_id=pipeline_run_id,
            subject_type="criterion",
            subject_id=result.criterion_id,
            status="requires_review" if result.uncertainty_flag else "succeeded",
            verdict="PASS" if result.mean_normalized_score >= 0.5 else "FAIL",
            confidence=confidence_val,
            reason_codes=reason_codes,
            escalation_history=[],
            result={
                "criterion_code": result.criterion_code,
                "criterion_title": result.criterion_title,
                "weight": result.weight,
                "min_score": result.min_score,
                "max_score": result.max_score,
                "scoring_method": result.scoring_method.value,
                "mean_raw_score": result.mean_raw_score,
                "mean_normalized_score": result.mean_normalized_score,
                "variance": result.variance,
                "std_dev": result.std_dev,
                "uncertainty_flag": result.uncertainty_flag,
                "consensus_rationale": result.consensus_rationale,
                "strengths": result.strengths,
                "weaknesses": result.weaknesses,
                "improvement_suggestions": result.improvement_suggestions,
                "runs_count": len(result.runs),
            },
        )
        self.session.add(pipeline_result)
        await self.session.flush()

        # 4. Liên kết PipelineResultEvidence
        links = [
            PipelineResultEvidence(
                pipeline_result_id=pipeline_result.id,
                evidence_item_id=e_model.id,
                usage="support",
            )
            for e_model in evidence_item_models
        ]
        self.session.add_all(links)

        # 5. Lưu từng lượt điểm RubricCriterionScore
        score_models: list[RubricCriterionScore] = []
        for run in result.runs:
            score_models.append(
                RubricCriterionScore(
                    id=uuid4(),
                    pipeline_result_id=pipeline_result.id,
                    rubric_criterion_id=result.criterion_id,
                    run_index=run.run_index,
                    raw_score=Decimal(str(run.raw_score)),
                    normalized_score=Decimal(str(run.normalized_score)),
                    rationale=run.rationale,
                    variance=Decimal(str(result.variance)) if result.variance is not None else None,
                )
            )
        self.session.add_all(score_models)
        await self.session.flush()

        return pipeline_result.id

    async def save_overall_result(
        self,
        submission_id: UUID,
        pipeline_run_id: UUID,
        detail_result: Pipeline1DetailResult,
    ) -> None:
        """Lưu PipelineResult tổng thể cho cả submission."""
        pipeline_result = PipelineResult(
            id=uuid4(),
            pipeline_run_id=pipeline_run_id,
            subject_type="submission",
            subject_id=submission_id,
            status=detail_result.status,
            verdict="PASS" if detail_result.total_normalized_score >= 0.5 else "FAIL",
            confidence=Decimal("0.9000"),
            reason_codes=["REQUIRES_HUMAN_REVIEW"] if detail_result.requires_human_review else [],
            escalation_history=[],
            result=detail_result.model_dump(mode="json"),
        )
        self.session.add(pipeline_result)
        await self.session.flush()

    async def get_latest_detail_result(self, submission_id: UUID) -> Pipeline1DetailResult | None:
        """Truy vấn kết quả Pipeline 1 chi tiết mới nhất của submission."""
        statement = (
            select(PipelineResult)
            .join(PipelineRun, PipelineRun.id == PipelineResult.pipeline_run_id)
            .where(
                PipelineRun.submission_id == submission_id,
                PipelineRun.pipeline == "P1",
                PipelineResult.subject_type == "submission",
            )
            .order_by(PipelineResult.created_at.desc())
        )
        row = (await self.session.scalars(statement)).first()
        if not row or not row.result:
            return None
        return Pipeline1DetailResult.model_validate(row.result)
