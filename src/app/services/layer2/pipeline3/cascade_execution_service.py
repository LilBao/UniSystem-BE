"""CascadeExecutionService (Tier 3 - Critical Claims).

Tạm thời để stub TODO / Deferred theo yêu cầu kiến trúc:
Không khởi tạo Docker sandbox hoặc runtime execution trong giai đoạn này
nhằm tối ưu tốc độ và tránh lỗi giả do thiếu môi trường (GPU/dataset).
"""

from app.schemas.p3_schema import (
    CodeConsistencyResult,
    CodeConsistencyVerdict,
    P3WorkItem,
    VerificationStage,
)


class CascadeExecutionService:
    def __init__(self) -> None:
        self.is_enabled = False

    async def verify_critical_claim(
        self, work_item: P3WorkItem, tier2_result: CodeConsistencyResult | None = None
    ) -> CodeConsistencyResult:
        """Stub placeholder cho Tầng 3.

        Nếu claim được chuyển tiếp lên Tầng 3, trả về kết quả từ Tầng 2
        (hoặc REQUIRES_REVIEW nếu chưa có) kèm cờ đánh dấu TIER3_SKIPPED.
        """
        if tier2_result is not None:
            return tier2_result

        return CodeConsistencyResult(
            claim_id=work_item.claim_id,
            verdict=CodeConsistencyVerdict.NEI,
            confidence=0.5,
            verification_stage=VerificationStage.SKIPPED_TIER3,
            requires_review=True,
            reason_codes=["TIER3_EXECUTION_SKIPPED"],
            stage_history=[VerificationStage.SKIPPED_TIER3],
            rationale="Tầng 3 (Dynamic Execution) tạm thời được bỏ qua; cần xem xét thủ công.",
        )
