from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.dependencies import get_pipeline1_service
from app.main import app
from app.models.layer1_model import Claim, DocumentBlock, DocumentSection
from app.models.pipeline_model import PipelineRun
from app.models.rubric_model import RubricCriterion
from app.models.submission_model import Submission
from app.schemas.p1_schema import (
    CriterionEvidencePack,
    CriterionScoringResult,
    Pipeline1Config,
    Pipeline1DetailResult,
    ScoringMethod,
    SingleScoreRun,
)
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.layer2.pipeline1.geval_scoring_service import GEvalScoringService
from app.services.layer2.pipeline1.pipeline1_service import Pipeline1Service
from app.services.layer2.pipeline1.section_understanding_service import (
    SectionUnderstandingService,
)


class MockRubricEvaluator:
    def __init__(self) -> None:
        self.model = "mock-geval-llm"
        self.version = "mock-geval-llm:geval-cot-1"

    async def evaluate_criterion_run(
        self,
        pack: CriterionEvidencePack,
        method: ScoringMethod,
        run_index: int,
        temperature: float = 0.3,
    ) -> SingleScoreRun:
        score = 8.5
        normalized = (score - pack.min_score) / (pack.max_score - pack.min_score)
        return SingleScoreRun(
            run_index=run_index,
            raw_score=score,
            normalized_score=normalized,
            cot_steps=["Step 1: Check requirement", "Step 2: Assign score"],
            rationale=f"Mock evaluation for {pack.criterion_code}",
            strengths=["Clear implementation"],
            weaknesses=["Add more benchmarks"],
            cited_evidence=["Evidence quote"],
        )

    async def generate_executive_summary(
        self,
        submission_title: str | None,
        criteria_summaries: list[dict],
    ) -> str:
        return "Executive Summary: The project demonstrates good technical depth across all criteria."


@pytest.mark.asyncio
async def test_pipeline1_run_flow() -> None:
    submission_id = uuid4()
    run_id = uuid4()
    rubric_version_id = uuid4()

    mock_submission_repo = AsyncMock()
    mock_submission_repo.get.return_value = Submission(
        id=submission_id,
        project_id=uuid4(),
        group_id=uuid4(),
        submitted_by_user_id=uuid4(),
        rubric_version_id=rubric_version_id,
        status="processing",
    )

    layer1_run = PipelineRun(
        id=uuid4(),
        submission_id=submission_id,
        pipeline="L1",
        status="succeeded",
        attempt_no=1,
        code_version="1.0",
        schema_version="1.0",
        policy_version="1.0",
        input_fingerprint="fp_in_l1",
        output_fingerprint="fp_out_l1",
    )
    mock_pipeline_repo = AsyncMock()
    mock_pipeline_repo.get_latest_succeeded.return_value = layer1_run
    mock_pipeline_repo.find_reusable_run.return_value = None
    mock_pipeline_repo.next_attempt_no.return_value = 1

    created_run = PipelineRun(
        id=run_id,
        submission_id=submission_id,
        pipeline="P1",
        status="running",
        attempt_no=1,
        code_version="p1-geval-1",
        schema_version="1.0",
        policy_version="1.0",
        input_fingerprint="fp_in_p1",
        started_at=datetime.now(UTC),
    )
    mock_pipeline_repo.create_run.return_value = created_run

    crit1 = RubricCriterion(
        id=uuid4(),
        rubric_version_id=rubric_version_id,
        code="CRIT-1",
        title="Đặt vấn đề & Mục tiêu",
        description="Mục tiêu nghiên cứu",
        weight=0.5,
        min_score=0.0,
        max_score=10.0,
        ordinal=1,
        grading_rules={},
    )
    crit2 = RubricCriterion(
        id=uuid4(),
        rubric_version_id=rubric_version_id,
        code="CRIT-2",
        title="Kiến trúc hệ thống",
        description="Mô tả kiến trúc",
        weight=0.5,
        min_score=0.0,
        max_score=10.0,
        ordinal=2,
        grading_rules={},
    )

    mock_p1_repo = AsyncMock()
    mock_p1_repo.list_criteria.return_value = [crit1, crit2]
    mock_p1_repo.list_document_blocks.return_value = []
    mock_p1_repo.list_document_sections.return_value = []
    mock_p1_repo.list_claims.return_value = []
    mock_p1_repo.save_criterion_evaluation.return_value = uuid4()
    mock_p1_repo.save_overall_result.return_value = None

    evaluator = MockRubricEvaluator()
    settings = Settings()

    service = Pipeline1Service(
        submission_repository=mock_submission_repo,
        pipeline_repository=mock_pipeline_repo,
        p1_repository=mock_p1_repo,
        section_service=SectionUnderstandingService(),
        scoring_service=GEvalScoringService(evaluator=evaluator, default_runs=3),
        evaluator=evaluator,
        settings=settings,
    )

    response = await service.run(submission_id)

    assert response.submission_id == submission_id
    assert response.pipeline == "P1"
    assert mock_pipeline_repo.finalize.called
    assert mock_p1_repo.save_criterion_evaluation.call_count == 2
    assert mock_p1_repo.save_overall_result.called


@pytest.mark.asyncio
async def test_pipeline1_layer1_not_succeeded_raises_error() -> None:
    submission_id = uuid4()
    mock_submission_repo = AsyncMock()
    mock_submission_repo.get.return_value = Submission(
        id=submission_id,
        rubric_version_id=uuid4(),
        status="processing",
    )

    mock_pipeline_repo = AsyncMock()
    mock_pipeline_repo.get_latest_succeeded.return_value = None  # No Layer 1 succeeded

    mock_p1_repo = AsyncMock()
    evaluator = MockRubricEvaluator()
    settings = Settings()

    service = Pipeline1Service(
        submission_repository=mock_submission_repo,
        pipeline_repository=mock_pipeline_repo,
        p1_repository=mock_p1_repo,
        section_service=SectionUnderstandingService(),
        scoring_service=GEvalScoringService(evaluator=evaluator),
        evaluator=evaluator,
        settings=settings,
    )

    with pytest.raises(AppError) as exc_info:
        await service.run(submission_id)

    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION


@pytest.mark.asyncio
async def test_pipeline1_api_endpoints() -> None:
    submission_id = uuid4()
    run_id = uuid4()

    mock_service = AsyncMock()

    mock_run_response = PipelineRunResponse(
        id=run_id,
        submission_id=submission_id,
        pipeline="P1",
        status="succeeded",
        attempt_no=1,
        code_version="p1-geval-1",
        schema_version="1.0",
        policy_version="p1-rubric-scoring-1",
        input_fingerprint="test_fp",
        output_fingerprint="test_out_fp",
        config={},
        metrics={"total_criteria": 2, "total_raw_score": 8.5},
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    mock_service.run.return_value = mock_run_response

    mock_detail_result = Pipeline1DetailResult(
        submission_id=submission_id,
        rubric_version_id=uuid4(),
        pipeline_run_id=run_id,
        status="succeeded",
        scoring_method=ScoringMethod.G_EVAL,
        total_raw_score=8.5,
        total_max_score=10.0,
        total_normalized_score=0.85,
        mean_variance=0.04,
        requires_human_review=False,
        executive_summary="Dự án hoàn thành xuất sắc các tiêu chí.",
        criteria_results=[],
    )
    mock_service.get_results.return_value = mock_detail_result

    app.dependency_overrides[get_pipeline1_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Test POST run pipeline 1
            post_resp = await client.post(f"/api/v1/submissions/{submission_id}/pipelines/p1")
            assert post_resp.status_code == 200
            post_data = post_resp.json()
            assert post_data["pipeline"] == "P1"
            assert post_data["status"] == "succeeded"

            # 2. Test GET results
            get_resp = await client.get(f"/api/v1/submissions/{submission_id}/pipelines/p1/results")
            assert get_resp.status_code == 200
            get_data = get_resp.json()
            assert get_data["submission_id"] == str(submission_id)
            assert get_data["total_raw_score"] == 8.5
            assert "xuất sắc" in get_data["executive_summary"]
    finally:
        app.dependency_overrides.clear()
