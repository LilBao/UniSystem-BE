import asyncio
import math
from typing import Any

from app.adapters.llm_rubric_evaluator import LLMRubricEvaluator
from app.schemas.p1_schema import (
    CriterionEvidencePack,
    CriterionScoringResult,
    ScoringMethod,
    SingleScoreRun,
)


class GEvalScoringService:
    """Service thực hiện quy trình chấm điểm G-EVAL với Multi-run Self-Consistency và thống kê Variance."""

    def __init__(
        self,
        evaluator: LLMRubricEvaluator,
        default_runs: int = 3,
        default_variance_threshold: float = 0.15,
    ) -> None:
        self.evaluator = evaluator
        self.default_runs = default_runs
        self.default_variance_threshold = default_variance_threshold

    async def score_criterion(
        self,
        pack: CriterionEvidencePack,
        method: ScoringMethod = ScoringMethod.G_EVAL,
        num_runs: int | None = None,
        variance_threshold: float | None = None,
        temperature: float = 0.3,
    ) -> CriterionScoringResult:
        runs_count = num_runs or self.default_runs
        var_threshold = (
            variance_threshold
            if variance_threshold is not None
            else self.default_variance_threshold
        )

        # Baseline Zero-shot / Few-shot chỉ cần chạy 1 lần; G-EVAL chạy 3-5 lần Multi-run Self-Consistency
        effective_runs = runs_count if method == ScoringMethod.G_EVAL else 1

        # Chạy song song các lượt chấm
        tasks = [
            self.evaluator.evaluate_criterion_run(
                pack=pack,
                method=method,
                run_index=i + 1,
                temperature=temperature if method == ScoringMethod.G_EVAL else 0.0,
            )
            for i in range(effective_runs)
        ]
        runs = await asyncio.gather(*tasks)

        # Tính toán thống kê
        raw_scores = [r.raw_score for r in runs]
        mean_raw = sum(raw_scores) / len(raw_scores)
        
        # Sample variance s^2
        if len(raw_scores) > 1:
            variance = sum((x - mean_raw) ** 2 for x in raw_scores) / (len(raw_scores) - 1)
        else:
            variance = 0.0
        std_dev = math.sqrt(variance)

        # Chuẩn hóa điểm
        score_range = pack.max_score - pack.min_score
        normalized_mean = (
            (mean_raw - pack.min_score) / score_range if score_range > 0 else 1.0
        )
        normalized_mean = max(0.0, min(1.0, normalized_mean))

        # Kiểm tra ngưỡng dao động (Uncertainty threshold)
        uncertainty_flag = variance > var_threshold

        # Tổng hợp Consensus Rationale, Strengths, Weaknesses, Suggestions
        consensus_rationale = self._synthesize_consensus_rationale(runs, mean_raw, variance)
        strengths = self._aggregate_unique_items([r.strengths for r in runs])
        weaknesses = self._aggregate_unique_items([r.weaknesses for r in runs])
        suggestions = self._aggregate_suggestions(runs)

        return CriterionScoringResult(
            criterion_id=pack.criterion_id,
            criterion_code=pack.criterion_code,
            criterion_title=pack.criterion_title,
            weight=pack.weight,
            min_score=pack.min_score,
            max_score=pack.max_score,
            scoring_method=method,
            runs=runs,
            mean_raw_score=round(mean_raw, 3),
            mean_normalized_score=round(normalized_mean, 4),
            variance=round(variance, 4),
            std_dev=round(std_dev, 4),
            uncertainty_flag=uncertainty_flag,
            consensus_rationale=consensus_rationale,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_suggestions=suggestions,
        )

    @staticmethod
    def _synthesize_consensus_rationale(
        runs: list[SingleScoreRun],
        mean_score: float,
        variance: float,
    ) -> str:
        if not runs:
            return "Không có dữ liệu đánh giá."

        base_rationale = runs[0].rationale
        if len(runs) == 1:
            return base_rationale

        variance_note = (
            f" (Độ ổn định cao, phương sai {variance:.3f})"
            if variance <= 0.15
            else f" (Có độ dao động giữa các lượt chấm, phương sai {variance:.3f})"
        )
        return (
            f"Đánh giá đồng thuận (Điểm TB: {mean_score:.2f}/10 qua {len(runs)} lượt chấm G-EVAL{variance_note}):\n"
            f"{base_rationale}"
        )

    @staticmethod
    def _aggregate_unique_items(item_lists: list[list[str]], max_items: int = 5) -> list[str]:
        seen = set()
        result: list[str] = []
        for lst in item_lists:
            for item in lst:
                clean = item.strip()
                if clean and clean.lower() not in seen:
                    seen.add(clean.lower())
                    result.append(clean)
                if len(result) >= max_items:
                    break
            if len(result) >= max_items:
                break
        return result

    @staticmethod
    def _aggregate_suggestions(runs: list[SingleScoreRun], max_items: int = 4) -> list[str]:
        suggestions: list[str] = []
        seen = set()
        for r in runs:
            for w in r.weaknesses:
                if w and w.lower() not in seen:
                    seen.add(w.lower())
                    suggestions.append(f"Cần khắc phục: {w}")
                if len(suggestions) >= max_items:
                    break
        return suggestions
