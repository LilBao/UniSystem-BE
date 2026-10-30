import pytest
from uuid import uuid4

from app.core.config import Settings
from app.models.layer1_model import Claim, DocumentBlock, DocumentSection
from app.models.rubric_model import RubricCriterion
from app.schemas.p1_schema import (
    CriterionEvidenceItem,
    CriterionEvidencePack,
    ScoringMethod,
    SingleScoreRun,
)
from app.services.layer2.pipeline1.geval_scoring_service import GEvalScoringService
from app.services.layer2.pipeline1.section_understanding_service import (
    SectionUnderstandingService,
)


class MockRubricEvaluator:
    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = scores or [8.0, 8.5, 8.2]
        self.call_count = 0

    async def evaluate_criterion_run(
        self,
        pack: CriterionEvidencePack,
        method: ScoringMethod,
        run_index: int,
        temperature: float = 0.3,
    ) -> SingleScoreRun:
        score = self.scores[self.call_count % len(self.scores)]
        self.call_count += 1
        normalized = (score - pack.min_score) / (pack.max_score - pack.min_score)

        return SingleScoreRun(
            run_index=run_index,
            raw_score=score,
            normalized_score=normalized,
            cot_steps=[f"Step 1: Evaluated {pack.criterion_code}", "Step 2: Scored based on evidence"],
            rationale=f"Mock rationale for {pack.criterion_code} run {run_index}",
            strengths=["Good structure", "Clear methodology"],
            weaknesses=["Needs more empirical verification"],
            cited_evidence=["Citation from report"],
        )

    async def generate_executive_summary(
        self,
        submission_title: str | None,
        criteria_summaries: list[dict],
    ) -> str:
        return f"Executive summary for {submission_title or 'project'}: Well executed."


@pytest.mark.asyncio
async def test_geval_multi_run_variance_computation() -> None:
    # 3 lượt chấm: 8.0, 8.5, 8.1
    evaluator = MockRubricEvaluator([8.0, 8.5, 8.1])
    service = GEvalScoringService(evaluator=evaluator, default_runs=3, default_variance_threshold=0.15)

    pack = CriterionEvidencePack(
        criterion_id=uuid4(),
        criterion_code="CRIT-1",
        criterion_title="Đặt vấn đề",
        criterion_description="Tính cấp thiết của đề tài",
        grading_rules={},
        min_score=0.0,
        max_score=10.0,
        weight=0.25,
        evidence_items=[],
        synthesized_context="Ngữ cảnh nghiên cứu về NLP và GenAI.",
    )

    result = await service.score_criterion(pack, method=ScoringMethod.G_EVAL, num_runs=3)

    assert result.criterion_code == "CRIT-1"
    assert len(result.runs) == 3
    # mean: (8.0 + 8.5 + 8.1) / 3 = 8.2
    assert pytest.approx(result.mean_raw_score, 0.01) == 8.2
    assert pytest.approx(result.mean_normalized_score, 0.01) == 0.82
    # variance: ((8.0-8.2)^2 + (8.5-8.2)^2 + (8.1-8.2)^2) / 2 = (0.04 + 0.09 + 0.01) / 2 = 0.07
    assert pytest.approx(result.variance, 0.01) == 0.07
    assert not result.uncertainty_flag  # 0.07 <= 0.15
    assert "Đánh giá đồng thuận" in result.consensus_rationale


@pytest.mark.asyncio
async def test_geval_high_variance_flag() -> None:
    # Lượt chấm dao động mạnh: 5.0, 9.0, 7.0
    # mean = 7.0, variance = ((5-7)^2 + (9-7)^2 + (7-7)^2)/2 = (4 + 4 + 0)/2 = 4.0
    evaluator = MockRubricEvaluator([5.0, 9.0, 7.0])
    service = GEvalScoringService(evaluator=evaluator, default_runs=3, default_variance_threshold=0.5)

    pack = CriterionEvidencePack(
        criterion_id=uuid4(),
        criterion_code="CRIT-3",
        criterion_title="Kiến trúc hệ thống",
        criterion_description="Thiết kế chi tiết giải pháp",
        grading_rules={},
        min_score=0.0,
        max_score=10.0,
        weight=0.3,
        evidence_items=[],
        synthesized_context="Kiến trúc multi-agent.",
    )

    result = await service.score_criterion(pack, method=ScoringMethod.G_EVAL, num_runs=3)

    assert pytest.approx(result.mean_raw_score, 0.01) == 7.0
    assert result.variance > 0.5
    assert result.uncertainty_flag is True  # High variance triggers review flag


def test_section_understanding_evidence_pack_builder() -> None:
    service = SectionUnderstandingService(max_evidence_items=5)

    criterion = RubricCriterion(
        id=uuid4(),
        rubric_version_id=uuid4(),
        code="CRIT-2",
        title="Tổng quan tài liệu & Nghiên cứu liên quan",
        description="Khảo sát các nghiên cứu trước đây về NLP và LLM evaluation",
        weight=0.2,
        min_score=0.0,
        max_score=10.0,
        ordinal=2,
        grading_rules={"required": "Có ít nhất 5 tài liệu tham khảo"},
    )

    art_id = uuid4()
    sec_id = uuid4()
    section = DocumentSection(
        id=sec_id,
        artifact_id=art_id,
        title="2. Tổng quan nghiên cứu",
        level=1,
        ordinal=2,
        page_start=3,
        page_end=5,
        section_path=["2. Tổng quan nghiên cứu"],
    )

    b1 = DocumentBlock(
        id=uuid4(),
        artifact_id=art_id,
        section_id=sec_id,
        block_type="text",
        page_no=3,
        reading_order=1,
        text_content="Nghiên cứu về NLP đã có nhiều bước tiến lớn từ khi mô hình Transformer ra đời. Các bài báo khảo sát tài liệu gần đây chỉ ra research gap...",
        bbox={},
        parser_version="test",
    )
    b2 = DocumentBlock(
        id=uuid4(),
        artifact_id=art_id,
        section_id=None,
        block_type="text",
        page_no=10,
        reading_order=20,
        text_content="Hướng dẫn cài đặt môi trường chạy Docker và npm install trên máy tính.",
        bbox={},
        parser_version="test",
    )

    claim = Claim(
        id=uuid4(),
        submission_id=uuid4(),
        source_block_id=b1.id,
        claim_type="text",
        text_content="Bài báo tổng quan tài liệu các công trình nghiên cứu NLP liên quan trong 5 năm gần nhất.",
        is_atomic=False,
        qualifiers={},
        source_span={},
        extractor_version="test",
    )

    pack = service.build_single_pack(
        criterion=criterion,
        blocks=[b1, b2],
        section_map={sec_id: section},
        claims=[claim],
    )

    assert pack.criterion_code == "CRIT-2"
    assert len(pack.evidence_items) > 0
    # Block 1 và Claim phải có điểm relevance cao hơn block 2
    top_item = pack.evidence_items[0]
    assert "Transformer" in top_item.text or "NLP" in top_item.text
    assert "BẰNG CHỨNG" in pack.synthesized_context
