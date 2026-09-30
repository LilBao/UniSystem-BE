"""CodeHighlightService.

Analyzes Graphify CodeGraph centrality (Degree, In-Degree, PageRank) to extract:
1. Important Code Highlights: Central Concepts, Core Algorithms, Key Entrypoints.
2. Visual Graph Response: Structured Node/Edge graph for Frontend rendering
   (React Flow / Cytoscape) with dual-span mismatch highlighting.
"""

from typing import Any
from uuid import UUID

import networkx as nx  # type: ignore[import-untyped]

from app.schemas.code_graph_schema import CodeGraph, GraphNode
from app.schemas.p3_schema import (
    CodeConsistencyResult,
    CodeConsistencyVerdict,
    CodeHighlightItem,
    CodeLocationSpan,
    HighlightKind,
    HighlightSeverity,
    MismatchWitness,
    VisualGraphEdge,
    VisualGraphMetrics,
    VisualGraphNode,
    VisualGraphNodeData,
    VisualGraphResponse,
)

CORE_ALGORITHM_PATTERNS = {
    "train",
    "forward",
    "backward",
    "predict",
    "evaluate",
    "loss",
    "optimizer",
    "encoder",
    "decoder",
    "transform",
    "cluster",
    "fit",
}

ENTRYPOINT_NAMES = {"main", "app", "run", "handler", "cli", "start", "serve"}


class CodeHighlightService:
    def __init__(self) -> None:
        pass

    def extract_important_highlights(
        self, code_graph: CodeGraph, top_k: int = 10
    ) -> list[CodeHighlightItem]:
        """Trích xuất danh sách các điểm code quan trọng nhất trong repository."""
        if not code_graph.nodes:
            return []

        # 1. Xây dựng đồ thị NetworkX
        nx_graph = nx.DiGraph()
        nodes_by_id: dict[str, GraphNode] = {}
        for node in code_graph.nodes:
            nx_graph.add_node(node.id, name=node.name, kind=node.kind)
            nodes_by_id[node.id] = node

        for edge in code_graph.edges:
            nx_graph.add_edge(edge.source, edge.target, relation=edge.relation)

        # 2. Tính toán độ đo trung tâm
        try:
            pagerank_scores = nx.pagerank(nx_graph, alpha=0.85)
        except Exception:
            pagerank_scores = {n: 1.0 / len(nx_graph) for n in nx_graph.nodes}

        in_degrees = dict(nx_graph.in_degree())
        out_degrees = dict(nx_graph.out_degree())

        highlights: list[CodeHighlightItem] = []
        max_pr = max(pagerank_scores.values()) if pagerank_scores else 1.0

        for node_id, node in nodes_by_id.items():
            if node.location is None:
                continue

            name_lower = node.name.lower()
            norm_score = (
                pagerank_scores.get(node_id, 0.0) / max_pr if max_pr > 0 else 0.0
            )
            in_deg = in_degrees.get(node_id, 0)
            out_deg = out_degrees.get(node_id, 0)

            kind: HighlightKind | None = None
            title = node.name
            desc = ""

            # Nhận diện Key Entrypoint
            if any(ep == name_lower for ep in ENTRYPOINT_NAMES) or (
                node.kind in ("function", "method") and in_deg == 0 and out_deg > 2
            ):
                kind = HighlightKind.KEY_ENTRYPOINT
                desc = "Điểm khởi tạo / entrypoint điều phối luồng thực thi chính của hệ thống."

            # Nhận diện Core Algorithm
            elif any(pat in name_lower for pat in CORE_ALGORITHM_PATTERNS) or node.kind == "class":
                kind = HighlightKind.CORE_ALGORITHM
                desc = "Khối thuật toán hoặc định nghĩa mô hình / xử lý dữ liệu trọng yếu."

            # Nhận diện Central Concept dựa theo In-Degree / PageRank
            elif norm_score >= 0.6 or in_deg >= 3:
                kind = HighlightKind.CENTRAL_CONCEPT
                desc = f"Khái niệm trung tâm có độ kết nối cao (được tham chiếu {in_deg} lần)."

            if kind is not None:
                loc = CodeLocationSpan(
                    path=node.location.path,
                    start_line=node.location.start_line,
                    end_line=node.location.end_line,
                )
                highlights.append(
                    CodeHighlightItem(
                        id=f"hl_{node.id}",
                        kind=kind,
                        severity=HighlightSeverity.INFO,
                        title=title,
                        description=desc,
                        location=loc,
                        importance_score=round(norm_score, 4),
                    )
                )

        highlights.sort(
            key=lambda x: (x.importance_score or 0.0), reverse=True
        )
        return highlights[:top_k]

    def build_visual_graph(
        self,
        submission_id: UUID,
        code_graph: CodeGraph,
        important_highlights: list[CodeHighlightItem],
        verdicts: list[CodeConsistencyResult],
        mismatch_witnesses: list[MismatchWitness],
        run_id: UUID | None = None,
        filter_mode: str = "all",
        min_importance: float = 0.0,
    ) -> VisualGraphResponse:
        """Dựng dữ liệu đồ thị trực quan (Visual Graph) cho Frontend."""
        important_ids = {hl.id.replace("hl_", "") for hl in important_highlights}
        importance_map = {
            hl.id.replace("hl_", ""): (hl.importance_score or 0.0)
            for hl in important_highlights
        }

        # Tập hợp các claim và vị trí code có mismatch
        mismatched_claim_ids = {w.claim_id for w in mismatch_witnesses}
        mismatched_code_paths = {w.code_location.path for w in mismatch_witnesses}

        graph_nodes: list[VisualGraphNode] = []
        graph_edges: list[VisualGraphEdge] = []

        # 1. Tạo các Nodes đại diện cho Report Claims
        for res in verdicts:
            has_mismatch = res.claim_id in mismatched_claim_ids
            status_str = (
                "mismatch"
                if res.verdict == CodeConsistencyVerdict.INCONSISTENT or has_mismatch
                else (
                    "consistent"
                    if res.verdict == CodeConsistencyVerdict.CONSISTENT
                    else "unsupported"
                )
            )

            # Lọc theo filter_mode
            if filter_mode == "mismatches_only" and not has_mismatch:
                continue

            node_data = VisualGraphNodeData(
                label=f"Claim: {res.claim_id.hex[:6]}",
                kind="CLAIM",
                status=status_str,
                is_important=has_mismatch or res.requires_review,
                importance_score=0.9 if has_mismatch else 0.5,
                has_mismatch=has_mismatch,
                location={"claim_id": str(res.claim_id)},
                snippet=res.rationale,
                cluster_id="claims_cluster",
                cluster_name="Report Claims",
            )
            graph_nodes.append(
                VisualGraphNode(
                    id=f"claim_{res.claim_id}",
                    type="claim_node",
                    data=node_data,
                )
            )

        # 2. Tạo các Nodes đại diện cho Code Entities
        for node in code_graph.nodes:
            is_imp = node.id in important_ids
            score = importance_map.get(node.id, 0.1)
            is_code_mismatch = bool(
                node.location and node.location.path in mismatched_code_paths
            )

            if filter_mode == "mismatches_only" and not is_code_mismatch:
                continue
            if filter_mode == "important_only" and not is_imp and not is_code_mismatch:
                continue
            if score < min_importance and not is_code_mismatch:
                continue

            status_str = "mismatch" if is_code_mismatch else "neutral"
            location_dict: dict[str, Any] = {}
            if node.location:
                location_dict = {
                    "path": node.location.path,
                    "start_line": node.location.start_line,
                    "end_line": node.location.end_line,
                }

            code_data = VisualGraphNodeData(
                label=f"{node.name} ({node.kind})",
                kind=node.kind.upper(),
                status=status_str,
                is_important=is_imp,
                importance_score=round(score, 4),
                has_mismatch=is_code_mismatch,
                location=location_dict,
                cluster_id="code_cluster",
                cluster_name="Source Code Repository",
            )
            graph_nodes.append(
                VisualGraphNode(
                    id=f"code_{node.id}",
                    type="code_node",
                    data=code_data,
                )
            )

        # 3. Tạo Edges giữa Code và Code
        valid_node_ids = {n.id for n in graph_nodes}
        for edge in code_graph.edges:
            src = f"code_{edge.source}"
            tgt = f"code_{edge.target}"
            if src in valid_node_ids and tgt in valid_node_ids:
                graph_edges.append(
                    VisualGraphEdge(
                        id=f"e_{edge.id}",
                        source=src,
                        target=tgt,
                        relation=edge.relation,
                        is_mismatch=False,
                        label=edge.relation,
                    )
                )

        # 4. Tạo Edges đối soát giữa Claim và Code (verifies_against)
        mismatch_edges_count = 0
        for witness in mismatch_witnesses:
            claim_node_id = f"claim_{witness.claim_id}"
            # Tìm code node tương ứng với witness path
            target_code_node = next(
                (
                    n
                    for n in graph_nodes
                    if n.type == "code_node"
                    and n.data.location.get("path") == witness.code_location.path
                ),
                None,
            )
            target_id = target_code_node.id if target_code_node else "code_repo_root"
            if claim_node_id in valid_node_ids:
                mismatch_edges_count += 1
                graph_edges.append(
                    VisualGraphEdge(
                        id=f"edge_mismatch_{witness.claim_id.hex[:6]}",
                        source=claim_node_id,
                        target=target_id,
                        relation="verifies_against",
                        is_mismatch=True,
                        severity=witness.severity,
                        discrepancy_details=witness.rationale,
                        label=f"MISMATCH ({witness.mismatch_type.value})",
                    )
                )

        # Cạnh liên kết cho các claim consistent
        for res in verdicts:
            if res.verdict == CodeConsistencyVerdict.CONSISTENT:
                claim_node_id = f"claim_{res.claim_id}"
                for ev in res.evidence_locations:
                    target_code_node = next(
                        (
                            n
                            for n in graph_nodes
                            if n.type == "code_node"
                            and n.data.location.get("path") == ev.path
                        ),
                        None,
                    )
                    if target_code_node and claim_node_id in valid_node_ids:
                        graph_edges.append(
                            VisualGraphEdge(
                                id=f"edge_match_{res.claim_id.hex[:4]}_{target_code_node.id[:6]}",
                                source=claim_node_id,
                                target=target_code_node.id,
                                relation="verifies_against",
                                is_mismatch=False,
                                label="VERIFIED",
                            )
                        )
                        break

        # 5. Tính toán Metrics
        mismatched_nodes = sum(1 for n in graph_nodes if n.data.has_mismatch)
        important_nodes = sum(1 for n in graph_nodes if n.data.is_important)
        total_claims = len(verdicts)
        consistent_claims = sum(
            1 for r in verdicts if r.verdict == CodeConsistencyVerdict.CONSISTENT
        )
        consistency_score = (
            round(consistent_claims / total_claims, 4) if total_claims > 0 else 1.0
        )

        metrics = VisualGraphMetrics(
            total_nodes=len(graph_nodes),
            total_edges=len(graph_edges),
            important_nodes_count=important_nodes,
            mismatched_nodes_count=mismatched_nodes,
            mismatched_edges_count=mismatch_edges_count,
            consistency_score=consistency_score,
        )

        return VisualGraphResponse(
            submission_id=submission_id,
            run_id=run_id,
            nodes=graph_nodes,
            edges=graph_edges,
            metrics=metrics,
            mismatch_witnesses=mismatch_witnesses,
        )
