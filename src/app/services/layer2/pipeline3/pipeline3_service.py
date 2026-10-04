import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.p3_repository import P3Repository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.submission_repository import SubmissionRepository
from app.schemas.p3_schema import (
    CodeConsistencyResult,
    CodeConsistencyVerdict,
    MismatchWitness,
    P3WorkItem,
    VisualGraphResponse,
)
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.layer2.pipeline3.cascade_execution_service import CascadeExecutionService
from app.services.layer2.pipeline3.code_highlight_service import CodeHighlightService
from app.services.layer2.pipeline3.code_semantic_judge_service import CodeSemanticJudgeService
from app.services.layer2.pipeline3.structural_consistency_service import (
    StructuralConsistencyService,
)


class Pipeline3Service:
    def __init__(
        self,
        submission_repository: SubmissionRepository,
        pipeline_repository: PipelineRepository,
        p3_repository: P3Repository,
        structural_verifier: StructuralConsistencyService,
        semantic_judge: CodeSemanticJudgeService,
        cascade_executor: CascadeExecutionService,
        highlight_service: CodeHighlightService,
        semantic_concurrency: int = 4,
    ) -> None:
        self.submission_repository = submission_repository
        self.pipeline_repository = pipeline_repository
        self.p3_repository = p3_repository
        self.structural_verifier = structural_verifier
        self.semantic_judge = semantic_judge
        self.cascade_executor = cascade_executor
        self.highlight_service = highlight_service
        self.semantic_concurrency = semantic_concurrency

    async def run(self, submission_id: UUID) -> PipelineRunResponse:
        """Thực thi Pipeline 3: Code-Report Consistency Verification."""
        submission = await self.submission_repository.get(submission_id)
        if submission is None:
            raise AppError(ErrorCode.SUBMISSION_NOT_FOUND)

        layer1_run = await self.pipeline_repository.get_latest_succeeded(submission_id, "L1")
        if layer1_run is None:
            raise AppError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "Layer 1 must succeed before Pipeline 3",
            )

        # 1. Tải CodeGraph snapshot và dữ liệu claims
        snapshot = await self.p3_repository.get_latest_graph_snapshot(submission_id)
        code_graph = await self.p3_repository.load_code_graph(snapshot)
        work_items = await self.p3_repository.list_work_items(submission_id)

        # 2. Trích xuất Important Code Highlights
        important_highlights = self.highlight_service.extract_important_highlights(
            code_graph, top_k=15
        )

        input_fingerprint = self._fingerprint(
            {
                "layer1_output_fingerprint": layer1_run.output_fingerprint,
                "verification_version": "p3-2",
                "judge_version": self.semantic_judge.version,
                "code_graph_sha": snapshot.source_sha256 if snapshot else "empty",
                "claims": [item.model_dump(mode="json") for item in work_items],
            }
        )

        reusable = await self.pipeline_repository.find_reusable_run(
            submission_id, "P3", input_fingerprint
        )
        if reusable is not None:
            return PipelineRunResponse.model_validate(reusable, from_attributes=True)

        attempt_no = await self.pipeline_repository.next_attempt_no(
            submission_id, "P3", input_fingerprint
        )
        run = await self.pipeline_repository.create_run(
            {
                "submission_id": submission_id,
                "pipeline": "P3",
                "status": "running",
                "attempt_no": attempt_no,
                "code_version": "p3-2",
                "model_version": self.semantic_judge.model or "heuristic-lexical",
                "prompt_version": self.semantic_judge.prompt_version,
                "schema_version": "1.0",
                "policy_version": "p3-consistency-verification-2",
                "input_fingerprint": input_fingerprint,
                "config": {
                    "tier2_mode": "llm" if self.semantic_judge.uses_llm else "lexical_only",
                    "tier3_mode": "skipped_todo",
                    "important_highlights_count": len(important_highlights),
                    "semantic_concurrency": self.semantic_concurrency,
                },
                "started_at": datetime.now(UTC),
            }
        )

        # 3. Leo thang 3 tầng (Tầng 1 -> Tầng 2 -> Tầng 3 Stub)
        # 3a. Chạy Tầng 1 (Structural Consistency) tuần tự nhanh
        tier1_results: list[tuple[P3WorkItem, CodeConsistencyResult | None]] = []
        for item in work_items:
            t1 = await self.structural_verifier.verify(item, code_graph)
            tier1_results.append((item, t1))

        # 3b. Với các item không khớp Tầng 1, đánh giá Tầng 2 (Semantic Judge) đồng thời
        sem = asyncio.Semaphore(self.semantic_concurrency)

        async def _evaluate_item(
            item: P3WorkItem, t1_res: CodeConsistencyResult | None
        ) -> CodeConsistencyResult:
            if t1_res is not None:
                return t1_res
            async with sem:
                t2_res = await self.semantic_judge.judge(item, code_graph)
                if item.is_central or item.testability > 0 or item.impact >= 2:
                    return await self.cascade_executor.verify_critical_claim(item, t2_res)
                return t2_res

        evaluated_results: list[CodeConsistencyResult] = await asyncio.gather(
            *[_evaluate_item(item, t1) for item, t1 in tier1_results]
        )

        results: list[CodeConsistencyResult] = []
        all_mismatch_witnesses: list[MismatchWitness] = []
        snapshot_id = snapshot.id if snapshot else None

        for item, final_result in zip(work_items, evaluated_results, strict=True):
            await self.p3_repository.save_result(
                submission_id, run.id, snapshot_id, item, final_result
            )
            results.append(final_result)
            all_mismatch_witnesses.extend(final_result.mismatch_witnesses)

        # 4. Xây dựng Visual Graph cho Frontend
        visual_graph = self.highlight_service.build_visual_graph(
            submission_id=submission_id,
            code_graph=code_graph,
            important_highlights=important_highlights,
            verdicts=results,
            mismatch_witnesses=all_mismatch_witnesses,
            run_id=run.id,
        )

        # 5. Hoàn tất PipelineRun
        status = self._run_status(results)
        metrics = {
            "total_claims": len(results),
            "consistent_count": sum(
                1 for r in results if r.verdict == CodeConsistencyVerdict.CONSISTENT
            ),
            "inconsistent_count": sum(
                1 for r in results if r.verdict == CodeConsistencyVerdict.INCONSISTENT
            ),
            "partial_count": sum(1 for r in results if r.verdict == CodeConsistencyVerdict.PARTIAL),
            "nei_count": sum(1 for r in results if r.verdict == CodeConsistencyVerdict.NEI),
            "requires_review_count": sum(1 for r in results if r.requires_review),
            "mismatches_found": len(all_mismatch_witnesses),
            "important_highlights": [h.model_dump(mode="json") for h in important_highlights],
            "visual_graph": visual_graph.model_dump(mode="json"),
        }

        output_fingerprint = self._fingerprint([item.model_dump(mode="json") for item in results])
        await self.pipeline_repository.finalize(
            run.id,
            status=status,
            output_fingerprint=output_fingerprint,
            metrics=metrics,
        )
        return PipelineRunResponse.model_validate(run, from_attributes=True)

    async def get_visual_graph(
        self,
        submission_id: UUID,
        filter_mode: str = "all",
        min_importance: float = 0.0,
    ) -> VisualGraphResponse:
        """API truy vấn Visual Graph cho Frontend."""
        cached = await self.p3_repository.get_visual_graph(
            submission_id, filter_mode=filter_mode, min_importance=min_importance
        )
        if cached is not None:
            return cached

        # Nếu chưa chạy pipeline hoặc chưa có cache, sinh đồ thị rỗng hợp lệ
        snapshot = await self.p3_repository.get_latest_graph_snapshot(submission_id)
        code_graph = await self.p3_repository.load_code_graph(snapshot)
        important = self.highlight_service.extract_important_highlights(code_graph)
        return self.highlight_service.build_visual_graph(
            submission_id=submission_id,
            code_graph=code_graph,
            important_highlights=important,
            verdicts=[],
            mismatch_witnesses=[],
            filter_mode=filter_mode,
            min_importance=min_importance,
        )

    @staticmethod
    def _run_status(results: list[CodeConsistencyResult]) -> str:
        if not results:
            return "abstained"
        if any(r.requires_review for r in results):
            return "requires_review"
        inconsistent = sum(1 for r in results if r.verdict == CodeConsistencyVerdict.INCONSISTENT)
        if inconsistent > 0:
            return "partial"
        return "succeeded"

    @staticmethod
    def _fingerprint(payload: Any) -> str:
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
