import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.adapters.llm_rubric_evaluator import LLMRubricEvaluator
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.p1_repository import P1Repository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.submission_repository import SubmissionRepository
from app.schemas.p1_schema import (
    CriterionScoringResult,
    P1ResultStatus,
    Pipeline1Config,
    Pipeline1DetailResult,
    ScoringMethod,
)
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.layer2.pipeline1.geval_scoring_service import GEvalScoringService
from app.services.layer2.pipeline1.section_understanding_service import (
    SectionUnderstandingService,
)


class Pipeline1Service:
    """Service điều phối toàn bộ Pipeline 1: Tóm tắt & Đánh giá theo Rubric (Rubric Scoring)."""

    def __init__(
        self,
        submission_repository: SubmissionRepository,
        pipeline_repository: PipelineRepository,
        p1_repository: P1Repository,
        section_service: SectionUnderstandingService,
        scoring_service: GEvalScoringService,
        evaluator: LLMRubricEvaluator,
        settings: Settings,
    ) -> None:
        self.submission_repository = submission_repository
        self.pipeline_repository = pipeline_repository
        self.p1_repository = p1_repository
        self.section_service = section_service
        self.scoring_service = scoring_service
        self.evaluator = evaluator
        self.settings = settings

    async def run(
        self,
        submission_id: UUID,
        config: Pipeline1Config | None = None,
    ) -> PipelineRunResponse:
        scoring_config = config or Pipeline1Config(
            scoring_method=ScoringMethod.G_EVAL,
            num_runs=self.settings.rubric_geval_runs,
            variance_threshold=self.settings.rubric_variance_threshold,
        )

        submission = await self.submission_repository.get(submission_id)
        if submission is None:
            raise AppError(ErrorCode.SUBMISSION_NOT_FOUND)

        # 1. Kiểm tra Layer 1 đã chạy thành công trước đó
        layer1_run = await self.pipeline_repository.get_latest_succeeded(submission_id, "L1")
        if layer1_run is None:
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "Layer 1 must succeed before Pipeline 1",
            )

        # 2. Lấy danh sách tiêu chí Rubric
        criteria = await self.p1_repository.list_criteria(submission.rubric_version_id)
        if not criteria:
            raise AppError(
                ErrorCode.RUBRIC_NOT_FOUND,
                "No rubric criteria found for this submission rubric version",
            )

        # 3. Tính toán Fingerprint đầu vào (bảo đảm tính tái lập Idempotency)
        input_fingerprint = self._fingerprint(
            {
                "layer1_output_fingerprint": layer1_run.output_fingerprint,
                "scoring_method": scoring_config.scoring_method.value,
                "num_runs": scoring_config.num_runs,
                "variance_threshold": scoring_config.variance_threshold,
                "evaluator_version": self.evaluator.version,
                "criteria_ids": [str(c.id) for c in criteria],
            }
        )

        # 4. Kiểm tra xem đã có run thành công với cùng fingerprint chưa
        reusable = await self.pipeline_repository.find_reusable_run(
            submission_id, "P1", input_fingerprint
        )
        if reusable is not None:
            return PipelineRunResponse.model_validate(reusable, from_attributes=True)

        # 5. Khởi tạo PipelineRun
        attempt_no = await self.pipeline_repository.next_attempt_no(
            submission_id, "P1", input_fingerprint
        )
        run = await self.pipeline_repository.create_run(
            {
                "submission_id": submission_id,
                "pipeline": "P1",
                "status": "running",
                "attempt_no": attempt_no,
                "code_version": "p1-geval-1",
                "model_version": self.evaluator.model or None,
                "prompt_version": self.evaluator.version,
                "schema_version": "1.0",
                "policy_version": "p1-rubric-scoring-1",
                "input_fingerprint": input_fingerprint,
                "config": scoring_config.model_dump(mode="json"),
                "started_at": datetime.now(UTC),
            }
        )

        # 6. Thu thập blocks, sections, claims từ Layer 1
        blocks = await self.p1_repository.list_document_blocks(submission_id)
        sections = await self.p1_repository.list_document_sections(submission_id)
        claims = await self.p1_repository.list_claims(submission_id)

        # 7. Section Understanding & Evidence Synthesis
        evidence_packs = self.section_service.build_evidence_packs(
            criteria=criteria,
            blocks=blocks,
            sections=sections,
            claims=claims,
        )

        # 8. Chấm điểm từng tiêu chí với G-EVAL / Baseline
        criteria_results: list[CriterionScoringResult] = []
        for pack in evidence_packs:
            result = await self.scoring_service.score_criterion(
                pack=pack,
                method=scoring_config.scoring_method,
                num_runs=scoring_config.num_runs,
                variance_threshold=scoring_config.variance_threshold,
                temperature=scoring_config.temperature,
            )
            await self.p1_repository.save_criterion_evaluation(
                submission_id=submission_id,
                pipeline_run_id=run.id,
                pack=pack,
                result=result,
            )
            criteria_results.append(result)

        # 9. Tính toán điểm tổng hợp và thống kê toàn hệ thống
        total_weight = sum(float(c.weight) for c in criteria) or 1.0
        total_raw = sum(
            r.mean_raw_score * (float(r.weight) / total_weight) for r in criteria_results
        )
        total_normalized = sum(
            r.mean_normalized_score * (float(r.weight) / total_weight) for r in criteria_results
        )
        mean_variance = (
            sum(r.variance for r in criteria_results) / len(criteria_results)
            if criteria_results
            else 0.0
        )
        requires_human_review = any(r.uncertainty_flag for r in criteria_results) or (
            total_normalized < 0.5
        )

        # 10. Tạo Executive Summary tổng hợp
        criteria_summaries = [
            {
                "code": r.criterion_code,
                "title": r.criterion_title,
                "mean_score": r.mean_raw_score,
                "strengths": r.strengths,
                "weaknesses": r.weaknesses,
                "consensus_rationale": r.consensus_rationale,
            }
            for r in criteria_results
        ]
        executive_summary = await self.evaluator.generate_executive_summary(
            submission_title=sections[0].title if sections else None,
            criteria_summaries=criteria_summaries,
        )

        # 11. Lưu kết quả chi tiết tổng thể
        detail_result = Pipeline1DetailResult(
            submission_id=submission_id,
            rubric_version_id=submission.rubric_version_id,
            pipeline_run_id=run.id,
            status=P1ResultStatus.REQUIRES_REVIEW.value if requires_human_review else P1ResultStatus.SUCCEEDED.value,
            scoring_method=scoring_config.scoring_method,
            total_raw_score=round(total_raw, 3),
            total_max_score=10.0,
            total_normalized_score=round(total_normalized, 4),
            mean_variance=round(mean_variance, 4),
            requires_human_review=requires_human_review,
            executive_summary=executive_summary,
            criteria_results=criteria_results,
        )
        await self.p1_repository.save_overall_result(submission_id, run.id, detail_result)

        # 12. Finalize PipelineRun
        metrics = {
            "total_criteria": len(criteria_results),
            "scoring_method": scoring_config.scoring_method.value,
            "total_raw_score": round(total_raw, 3),
            "total_normalized_score": round(total_normalized, 4),
            "mean_variance": round(mean_variance, 4),
            "uncertain_criteria_count": sum(1 for r in criteria_results if r.uncertainty_flag),
            "requires_human_review": requires_human_review,
        }
        output_fingerprint = self._fingerprint(detail_result.model_dump(mode="json"))

        run_status = (
            P1ResultStatus.REQUIRES_REVIEW.value
            if requires_human_review
            else P1ResultStatus.SUCCEEDED.value
        )
        await self.pipeline_repository.finalize(
            run.id,
            status=run_status,
            output_fingerprint=output_fingerprint,
            metrics=metrics,
        )

        return PipelineRunResponse.model_validate(run, from_attributes=True)

    async def get_results(self, submission_id: UUID) -> Pipeline1DetailResult | None:
        """Lấy kết quả đánh giá chi tiết Pipeline 1."""
        return await self.p1_repository.get_latest_detail_result(submission_id)

    @staticmethod
    def _fingerprint(payload: object) -> str:
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(canonical).hexdigest()
