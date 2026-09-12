import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.p2_repository import P2Repository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.submission_repository import SubmissionRepository
from app.schemas.p2_schema import (
    CitationResultStatus,
    CitationVerificationResult,
    VerificationStage,
)
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.citation_evidence_preparation_service import (
    CitationEvidencePreparationService,
)
from app.services.reference_resolution_service import ReferenceResolutionService


class Pipeline2Service:
    def __init__(
        self,
        submission_repository: SubmissionRepository,
        pipeline_repository: PipelineRepository,
        p2_repository: P2Repository,
        reference_resolver: ReferenceResolutionService,
        evidence_preparer: CitationEvidencePreparationService,
    ) -> None:
        self.submission_repository = submission_repository
        self.pipeline_repository = pipeline_repository
        self.p2_repository = p2_repository
        self.reference_resolver = reference_resolver
        self.evidence_preparer = evidence_preparer

    async def run(self, submission_id: UUID) -> PipelineRunResponse:
        submission = await self.submission_repository.get(submission_id)
        if submission is None:
            raise AppError(ErrorCode.SUBMISSION_NOT_FOUND)

        layer1_run = await self.pipeline_repository.get_latest_succeeded(submission_id, "L1")
        if layer1_run is None:
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "Layer 1 must succeed before Pipeline 2",
            )

        resolution_metrics = await self.reference_resolver.resolve_submission(submission_id)
        work_items = await self.p2_repository.list_work_items(submission_id)
        input_fingerprint = self._fingerprint(
            {
                "layer1_output_fingerprint": layer1_run.output_fingerprint,
                "phase1_version": "p2-phase1-1",
                "pairs": [item.model_dump(mode="json") for item in work_items],
            }
        )
        reusable = await self.pipeline_repository.find_reusable_run(
            submission_id, "P2", input_fingerprint
        )
        if reusable is not None:
            return PipelineRunResponse.model_validate(reusable, from_attributes=True)

        attempt_no = await self.pipeline_repository.next_attempt_no(
            submission_id, "P2", input_fingerprint
        )
        run = await self.pipeline_repository.create_run(
            {
                "submission_id": submission_id,
                "pipeline": "P2",
                "status": "running",
                "attempt_no": attempt_no,
                "code_version": "p2-phase1-1",
                "model_version": None,
                "prompt_version": None,
                "schema_version": "1.0",
                "policy_version": "p2-feedback-only-1",
                "input_fingerprint": input_fingerprint,
                "config": {
                    "reference_resolution": resolution_metrics,
                },
                "started_at": datetime.now(UTC),
            }
        )

        results: list[CitationVerificationResult] = []
        for work_item in work_items:
            try:
                result = await self.evidence_preparer.prepare(work_item.input, work_item.evidence)
            except AppError as exc:
                result = CitationVerificationResult(
                    claim_id=work_item.input.claim_id,
                    status=CitationResultStatus.FAILED,
                    verification_stage=VerificationStage.LOCAL,
                    requires_review=True,
                    reason_codes=[exc.code.value],
                    rationale=exc.message,
                )
            await self.p2_repository.save_result(submission_id, run.id, work_item, result)
            results.append(result)

        status = self._run_status(results)
        metrics = {
            "total_pairs": len(results),
            "succeeded": sum(item.status == CitationResultStatus.SUCCEEDED for item in results),
            "requires_review": sum(
                item.status == CitationResultStatus.REQUIRES_REVIEW for item in results
            ),
            "failed": sum(item.status == CitationResultStatus.FAILED for item in results),
            "reference_resolution": resolution_metrics,
        }
        output_fingerprint = self._fingerprint(
            [item.model_dump(mode="json") for item in results]
        )
        await self.pipeline_repository.finalize(
            run.id,
            status=status,
            output_fingerprint=output_fingerprint,
            metrics=metrics,
        )
        return PipelineRunResponse.model_validate(run, from_attributes=True)

    @staticmethod
    def _run_status(results: list[CitationVerificationResult]) -> str:
        if not results:
            return "abstained"
        failed = sum(item.status == CitationResultStatus.FAILED for item in results)
        if failed == len(results):
            return "failed"
        if failed:
            return "partial"
        if any(item.requires_review for item in results):
            return "requires_review"
        return "succeeded"

    @staticmethod
    def _fingerprint(payload: object) -> str:
        canonical = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        return hashlib.sha256(canonical).hexdigest()
