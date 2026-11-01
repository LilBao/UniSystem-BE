from uuid import uuid4

import pytest

from app.schemas.code_graph_schema import CodeGraph, GraphEdge, GraphLocation, GraphNode
from app.schemas.layer1_schema import CodeProvenance
from app.schemas.p3_schema import (
    CodeConsistencyVerdict,
    HighlightKind,
    P3WorkItem,
    VerificationStage,
)
from app.services.layer2.pipeline3.code_highlight_service import CodeHighlightService
from app.services.layer2.pipeline3.structural_consistency_service import (
    StructuralConsistencyService,
)


def _make_node(
    node_id: str,
    name: str,
    kind: str = "function",
    path: str = "src/model.py",
    start: int = 10,
    end: int = 20,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        name=name,
        kind=kind,
        location=GraphLocation(path=path, start_line=start, end_line=end),
        provenance=CodeProvenance.EXTRACTED,
        evidence={"parser": "tree-sitter", "version": "1.0", "rule": "ast"},
    )


def _make_edge(
    edge_id: str, source: str, target: str, relation: str = "calls"
) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        source=source,
        target=target,
        relation=relation,
        location=None,
        provenance=CodeProvenance.INFERRED,
        confidence=0.9,
        evidence={"parser": "graphify", "version": "1.0", "rule": "call_graph"},
    )


@pytest.mark.asyncio
async def test_structural_framework_match() -> None:
    service = StructuralConsistencyService()
    graph = CodeGraph(
        nodes=[
            _make_node("n1", "torch", kind="module", path="requirements.txt", start=1, end=1),
            _make_node("n2", "ResNetBackbone", kind="class", path="src/model.py", start=5, end=40),
        ],
        edges=[],
    )
    item = P3WorkItem(
        claim_id=uuid4(),
        text_content="Mô hình được xây dựng trên nền tảng thư viện PyTorch.",
    )
    result = await service.verify(item, graph)
    assert result is not None
    assert result.verdict == CodeConsistencyVerdict.CONSISTENT
    assert result.verification_stage == VerificationStage.STRUCTURAL
    assert "STRUCTURAL_MATCH" in result.reason_codes
    assert len(result.evidence_locations) > 0


@pytest.mark.asyncio
async def test_structural_framework_mismatch_creates_witness() -> None:
    service = StructuralConsistencyService()
    graph = CodeGraph(
        nodes=[
            _make_node("n1", "tensorflow", kind="module", path="requirements.txt", start=1, end=1),
        ],
        edges=[],
    )
    item = P3WorkItem(
        claim_id=uuid4(),
        text_content="Nhóm sử dụng PyTorch để huấn luyện mạng nơ-ron.",
        source_span={"page": 3, "line": 15},
    )
    result = await service.verify(item, graph)
    assert result is not None
    assert result.verdict == CodeConsistencyVerdict.INCONSISTENT
    assert result.verification_stage == VerificationStage.STRUCTURAL
    assert "STRUCTURAL_MISMATCH" in result.reason_codes
    assert len(result.mismatch_witnesses) == 1

    witness = result.mismatch_witnesses[0]
    assert witness.mismatch_type == HighlightKind.MISMATCH_STRUCTURAL
    assert "pytorch" in witness.expected_behavior.lower()
    assert "tensorflow" in witness.actual_behavior.lower()
    assert witness.code_location.path == "requirements.txt"


@pytest.mark.asyncio
async def test_structural_optimizer_mismatch() -> None:
    service = StructuralConsistencyService()
    graph = CodeGraph(
        nodes=[
            _make_node("n1", "sgd", kind="function", path="src/train.py", start=50, end=60),
        ],
        edges=[],
    )
    item = P3WorkItem(
        claim_id=uuid4(),
        text_content="Thuật toán huấn luyện sử dụng Adam optimizer với learning rate 0.001.",
    )
    result = await service.verify(item, graph)
    assert result is not None
    assert result.verdict == CodeConsistencyVerdict.INCONSISTENT
    assert "OPTIMIZER_MISMATCH" in result.reason_codes
    assert len(result.mismatch_witnesses) == 1
    assert "ADAM" in result.mismatch_witnesses[0].expected_behavior
    assert "SGD" in result.mismatch_witnesses[0].actual_behavior


@pytest.mark.asyncio
async def test_code_highlight_extraction_and_visual_graph() -> None:
    highlight_service = CodeHighlightService()
    nodes = [
        _make_node("n_main", "main", kind="function", path="main.py", start=1, end=30),
        _make_node("n_train", "train_model", kind="function", path="train.py", start=10, end=80),
        _make_node("n_resnet", "ResNetClassifier", kind="class", path="model.py", start=5, end=60),
        _make_node("n_util", "load_config", kind="function", path="util.py", start=1, end=20),
    ]
    edges = [
        _make_edge("e1", "n_main", "n_train", "calls"),
        _make_edge("e2", "n_train", "n_resnet", "calls"),
        _make_edge("e3", "n_main", "n_util", "calls"),
        _make_edge("e4", "n_train", "n_util", "calls"),
    ]
    graph = CodeGraph(nodes=nodes, edges=edges)

    # 1. Trích xuất Important Code Highlights
    highlights = highlight_service.extract_important_highlights(graph, top_k=5)
    assert len(highlights) > 0
    kinds = {h.kind for h in highlights}
    # Phải phát hiện ít nhất Core Algorithm hoặc Key Entrypoint hoặc Central Concept
    assert len(kinds.intersection({
        HighlightKind.CORE_ALGORITHM,
        HighlightKind.KEY_ENTRYPOINT,
        HighlightKind.CENTRAL_CONCEPT,
    })) > 0

    # 2. Xây dựng Visual Graph
    claim_id = uuid4()
    item = P3WorkItem(claim_id=claim_id, text_content="Report claim")
    structural_service = StructuralConsistencyService()
    verdict = await structural_service.verify(item, graph)
    verdicts = [verdict] if verdict else []

    visual_response = highlight_service.build_visual_graph(
        submission_id=uuid4(),
        code_graph=graph,
        important_highlights=highlights,
        verdicts=verdicts,
        mismatch_witnesses=[],
        filter_mode="all",
    )

    assert visual_response.metrics.total_nodes >= len(nodes)
    assert visual_response.metrics.total_edges >= len(edges)
    assert any(n.id == "code_n_main" for n in visual_response.nodes)
    assert any(e.id == "e_e1" for e in visual_response.edges)
