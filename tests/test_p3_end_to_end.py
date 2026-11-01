from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_pipeline3_service
from app.main import app
from app.models.pipeline_model import PipelineRun
from app.models.submission_model import Submission
from app.schemas.code_graph_schema import CodeGraph, GraphLocation, GraphNode
from app.schemas.layer1_schema import CodeProvenance
from app.schemas.p3_schema import (
    P3WorkItem,
    VisualGraphMetrics,
    VisualGraphNode,
    VisualGraphNodeData,
    VisualGraphResponse,
)
from app.services.layer2.pipeline3.cascade_execution_service import CascadeExecutionService
from app.services.layer2.pipeline3.code_highlight_service import CodeHighlightService
from app.services.layer2.pipeline3.code_semantic_judge_service import CodeSemanticJudgeService
from app.services.layer2.pipeline3.pipeline3_service import Pipeline3Service
from app.services.layer2.pipeline3.structural_consistency_service import (
    StructuralConsistencyService,
)


def _make_sample_graph() -> CodeGraph:
    return CodeGraph(
        nodes=[
            GraphNode(
                id="n_train",
                name="train_model",
                kind="function",
                location=GraphLocation(path="src/train.py", start_line=10, end_line=50),
                provenance=CodeProvenance.EXTRACTED,
                evidence={"parser": "graphify", "version": "1.0", "rule": "ast"},
            ),
            GraphNode(
                id="n_torch",
                name="torch",
                kind="module",
                location=GraphLocation(path="requirements.txt", start_line=1, end_line=1),
                provenance=CodeProvenance.EXTRACTED,
                evidence={"parser": "graphify", "version": "1.0", "rule": "ast"},
            ),
        ],
        edges=[],
    )


@pytest.mark.asyncio
async def test_pipeline3_run_flow() -> None:
    submission_id = uuid4()
    run_id = uuid4()

    mock_submission_repo = AsyncMock()
    mock_submission_repo.get.return_value = Submission(
        id=submission_id,
        project_id=uuid4(),
        group_id=uuid4(),
        submitted_by_user_id=uuid4(),
        rubric_version_id=uuid4(),
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
        input_fingerprint="fp1",
        output_fingerprint="fp_l1",
    )
    mock_pipeline_repo = AsyncMock()
    mock_pipeline_repo.get_latest_succeeded.return_value = layer1_run
    mock_pipeline_repo.find_reusable_run.return_value = None
    mock_pipeline_repo.next_attempt_no.return_value = 1

    created_run = PipelineRun(
        id=run_id,
        submission_id=submission_id,
        pipeline="P3",
        status="running",
        attempt_no=1,
        code_version="p3-1",
        schema_version="1.0",
        policy_version="1.0",
        input_fingerprint="in_fp",
        started_at=datetime.now(UTC),
    )
    mock_pipeline_repo.create_run.return_value = created_run

    mock_p3_repo = AsyncMock()
    mock_p3_repo.get_latest_graph_snapshot.return_value = None
    mock_p3_repo.load_code_graph.return_value = _make_sample_graph()
    mock_p3_repo.list_work_items.return_value = [
        P3WorkItem(
            claim_id=uuid4(),
            text_content="Dự án sử dụng thư viện PyTorch để huấn luyện mô hình.",
        ),
        P3WorkItem(
            claim_id=uuid4(),
            text_content="Nhóm sử dụng thuật toán cosine annealing learning rate scheduler.",
        ),
    ]

    service = Pipeline3Service(
        submission_repository=mock_submission_repo,
        pipeline_repository=mock_pipeline_repo,
        p3_repository=mock_p3_repo,
        structural_verifier=StructuralConsistencyService(),
        semantic_judge=CodeSemanticJudgeService(),
        cascade_executor=CascadeExecutionService(),
        highlight_service=CodeHighlightService(),
    )

    response = await service.run(submission_id)
    assert response.submission_id == submission_id
    assert response.pipeline == "P3"
    assert mock_pipeline_repo.finalize.called
    assert mock_p3_repo.save_result.call_count == 2


@pytest.mark.asyncio
async def test_pipeline3_api_graph_endpoint() -> None:
    submission_id = uuid4()
    run_id = uuid4()

    mock_service = AsyncMock()

    sample_visual_graph = VisualGraphResponse(
        submission_id=submission_id,
        run_id=run_id,
        nodes=[
            VisualGraphNode(
                id="claim_1",
                type="claim_node",
                data=VisualGraphNodeData(
                    label="Claim: Adam Optimizer",
                    kind="CLAIM",
                    status="consistent",
                    is_important=True,
                ),
            )
        ],
        edges=[],
        metrics=VisualGraphMetrics(
            total_nodes=1,
            total_edges=0,
            important_nodes_count=1,
            mismatched_nodes_count=0,
            mismatched_edges_count=0,
            consistency_score=1.0,
        ),
        mismatch_witnesses=[],
    )
    mock_service.get_visual_graph.return_value = sample_visual_graph

    app.dependency_overrides[get_pipeline3_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/submissions/{submission_id}/pipelines/p3/graph")
            assert resp.status_code == 200
            data = resp.json()
            assert data["submission_id"] == str(submission_id)
            assert len(data["nodes"]) == 1
            assert data["metrics"]["total_nodes"] == 1
    finally:
        app.dependency_overrides.clear()
