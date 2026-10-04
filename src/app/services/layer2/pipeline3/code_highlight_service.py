"""CodeHighlightService.

Analyzes Graphify CodeGraph centrality (Degree, In-Degree, PageRank) to extract:
1. Important Code Highlights: Domain Core Features, Core Algorithms, Key Entrypoints.
   Filters out boilerplate classes (ApiResponse, AppException, DTOs, Enums, Utils).
2. Visual Graph Response: Structured Node/Edge graph for Frontend rendering
   (React Flow / Cytoscape) with feature clusters and dual-span mismatch highlighting.
"""

from collections import defaultdict
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
from app.services.layer2.pipeline3.code_roles import (
    detect_file_role,
    extract_feature_key,
    is_boilerplate_path,
)
from app.services.layer2.pipeline3.code_text import identifier_tokens

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

ROLE_WEIGHTS = {
    "controller": 1.0,
    "service": 1.0,
    "entity": 0.85,
    "repository": 0.75,
    "infrastructure": 0.70,
    "component": 0.80,
    "boilerplate": 0.20,
}


class CodeHighlightService:
    def __init__(self) -> None:
        pass

    def extract_important_highlights(
        self, code_graph: CodeGraph, top_k: int = 10
    ) -> list[CodeHighlightItem]:
        """Trích xuất danh sách các tính năng/khối code quan trọng nhất trong repository."""
        if not code_graph.nodes:
            return []

        # 1. Xây dựng đồ thị NetworkX cho toàn bộ CodeGraph
        nx_graph = nx.DiGraph()
        nodes_by_id: dict[str, GraphNode] = {}
        for node in code_graph.nodes:
            nx_graph.add_node(node.id, name=node.name, kind=node.kind)
            nodes_by_id[node.id] = node

        for edge in code_graph.edges:
            nx_graph.add_edge(edge.source, edge.target, relation=edge.relation)

        try:
            pagerank_scores = nx.pagerank(nx_graph, alpha=0.85)
        except Exception:
            pagerank_scores = {n: 1.0 / len(nx_graph) for n in nx_graph.nodes}

        max_pr = max(pagerank_scores.values()) if pagerank_scores else 1.0

        # 2. Gom nhóm các node theo feature và phân loại boilerplate
        feature_nodes: dict[str, list[GraphNode]] = defaultdict(list)
        feature_files: dict[str, set[str]] = defaultdict(set)
        boilerplate_nodes: list[GraphNode] = []

        for node in code_graph.nodes:
            if not node.location:
                continue

            path = node.location.path
            if is_boilerplate_path(path):
                boilerplate_nodes.append(node)
                continue

            feat_key = extract_feature_key(path)
            feature_nodes[feat_key].append(node)
            feature_files[feat_key].add(path)

        # Nếu tất cả các node bị gom vào boilerplate (ví dụ graph nhỏ dạng script),
        # giữ lại toàn bộ để không làm rỗng kết quả
        if not feature_nodes and code_graph.nodes:
            for node in code_graph.nodes:
                if node.location:
                    path = node.location.path
                    feat_key = extract_feature_key(path)
                    feature_nodes[feat_key].append(node)
                    feature_files[feat_key].add(path)

        # 3. Tính điểm quan trọng và tạo CodeHighlightItem cho từng feature
        highlights: list[CodeHighlightItem] = []

        for feat_key, member_nodes in feature_nodes.items():
            paths = feature_files[feat_key]
            layers = sorted(list({detect_file_role(p) for p in paths}))

            # Tìm node đại diện chính (ưu tiên Controller -> Service -> Entity/Class)
            def _node_priority(n: GraphNode) -> tuple[int, float]:
                p = n.location.path if n.location else ""
                role = detect_file_role(p)
                role_score = 3 if role == "controller" else (2 if role == "service" else 1)
                kind_score = 2 if n.kind in ("class", "function") else 1
                pr = pagerank_scores.get(n.id, 0.0)
                return (role_score * 10 + kind_score, pr)

            member_nodes.sort(key=_node_priority, reverse=True)
            primary_node = member_nodes[0]
            if not primary_node.location:
                continue

            # Tính điểm feature tổng hợp từ PageRank và trọng số role
            feat_pr_sum = 0.0
            for n in member_nodes:
                p = n.location.path if n.location else ""
                r = detect_file_role(p)
                w = ROLE_WEIGHTS.get(r, 0.7)
                norm_node_pr = pagerank_scores.get(n.id, 0.0) / max_pr if max_pr > 0 else 0.0
                feat_pr_sum += norm_node_pr * w

            # Chuẩn hóa điểm trung bình tính năng
            avg_feat_score = min(1.0, feat_pr_sum / (len(member_nodes) ** 0.5 or 1.0))

            # Xác định loại Highlight
            kind = HighlightKind.CORE_FEATURE
            clean_title = feat_key.capitalize()

            # Kiểm tra xem có node nào là entrypoint chính không
            has_entrypoint = any(
                n.name.lower() in ENTRYPOINT_NAMES
                or (
                    n.kind in ("function", "method")
                    and nx_graph.in_degree(n.id) == 0
                    and nx_graph.out_degree(n.id) > 2
                )
                for n in member_nodes
            )
            has_algorithm = any(
                any(tok in CORE_ALGORITHM_PATTERNS for tok in identifier_tokens(n.name))
                for n in member_nodes
            )

            if has_entrypoint:
                kind = HighlightKind.KEY_ENTRYPOINT
                desc = (
                    f"Điểm khởi tạo / entrypoint hệ thống: {primary_node.name} "
                    f"({len(member_nodes)} thành phần liên quan)."
                )
            elif has_algorithm:
                kind = HighlightKind.CORE_ALGORITHM
                desc = f"Khối thuật toán hoặc xử lý logic cốt lõi: {primary_node.name}."
            else:
                kind = HighlightKind.CORE_FEATURE
                desc = (
                    f"Tính năng '{clean_title}' bao gồm các tầng: {', '.join(layers)} "
                    f"({len(paths)} files, {len(member_nodes)} methods/classes)."
                )

            # Danh sách các component chính trong feature
            classes_and_funcs = [
                n.name for n in member_nodes if n.kind in ("class", "function", "interface")
            ]
            if not classes_and_funcs:
                classes_and_funcs = [n.name for n in member_nodes[:5]]

            loc = CodeLocationSpan(
                path=primary_node.location.path,
                start_line=primary_node.location.start_line,
                end_line=primary_node.location.end_line,
            )

            highlights.append(
                CodeHighlightItem(
                    id=f"feat_{feat_key}",
                    kind=kind,
                    severity=HighlightSeverity.INFO,
                    title=f"Feature: {clean_title}"
                    if kind == HighlightKind.CORE_FEATURE
                    else primary_node.name,
                    description=desc,
                    location=loc,
                    importance_score=round(avg_feat_score, 4),
                    feature_key=feat_key,
                    layers=layers,
                    components=classes_and_funcs[:8],
                    member_node_ids=[n.id for n in member_nodes],
                    member_paths=sorted(list(paths)),
                )
            )

        # Sắp xếp theo điểm quan trọng giảm dần
        highlights.sort(key=lambda x: x.importance_score or 0.0, reverse=True)
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
        """Dựng dữ liệu đồ thị trực quan (Visual Graph) cho Frontend có gom cụm tính năng."""
        # Tập hợp các node ID quan trọng từ các tính năng
        important_node_ids: set[str] = set()
        node_importance_map: dict[str, float] = {}
        node_feature_map: dict[str, str] = {}

        for hl in important_highlights:
            feat_score = hl.importance_score or 0.5
            for nid in hl.member_node_ids:
                important_node_ids.add(nid)
                node_importance_map[nid] = max(node_importance_map.get(nid, 0.0), feat_score)
                if hl.feature_key:
                    node_feature_map[nid] = hl.feature_key

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
                role="claim",
            )
            graph_nodes.append(
                VisualGraphNode(
                    id=f"claim_{res.claim_id}",
                    type="claim_node",
                    data=node_data,
                )
            )

        # 2. Tạo Cluster Group Nodes cho từng Tính năng quan trọng
        for hl in important_highlights:
            if not hl.feature_key:
                continue
            group_id = f"group_{hl.feature_key}"
            group_data = VisualGraphNodeData(
                label=hl.title,
                kind="FEATURE",
                status="neutral",
                is_important=True,
                importance_score=hl.importance_score or 0.8,
                has_mismatch=any(p in mismatched_code_paths for p in hl.member_paths),
                location={"path": hl.location.path},
                snippet=hl.description,
                cluster_id=f"cluster_{hl.feature_key}",
                cluster_name=hl.title,
                role="feature_group",
            )
            graph_nodes.append(
                VisualGraphNode(
                    id=group_id,
                    type="cluster_group",
                    data=group_data,
                )
            )

        # 3. Tạo các Nodes đại diện cho Code Entities
        for node in code_graph.nodes:
            path = node.location.path if node.location else ""
            is_bp = is_boilerplate_path(path) if path else True
            role = detect_file_role(path) if path else "component"
            feat_key = node_feature_map.get(node.id) or (
                extract_feature_key(path) if path and not is_bp else None
            )

            is_imp = node.id in important_node_ids
            score = node_importance_map.get(node.id, 0.1 if is_bp else 0.4)
            is_code_mismatch = bool(path and path in mismatched_code_paths)

            status_str = "mismatch" if is_code_mismatch else "neutral"
            location_dict: dict[str, Any] = {}
            if node.location:
                location_dict = {
                    "path": node.location.path,
                    "start_line": node.location.start_line,
                    "end_line": node.location.end_line,
                }

            cluster_id = (
                "boilerplate_cluster"
                if is_bp
                else (f"cluster_{feat_key}" if feat_key else "code_cluster")
            )
            cluster_name = (
                "Boilerplate & Utilities"
                if is_bp
                else (f"Feature: {feat_key.capitalize()}" if feat_key else "Source Code")
            )

            code_data = VisualGraphNodeData(
                label=f"{node.name} ({node.kind})",
                kind=node.kind.upper(),
                status=status_str,
                is_important=is_imp,
                importance_score=round(score, 4),
                has_mismatch=is_code_mismatch,
                location=location_dict,
                cluster_id=cluster_id,
                cluster_name=cluster_name,
                role=role,
            )
            graph_nodes.append(
                VisualGraphNode(
                    id=f"code_{node.id}",
                    type="code_node",
                    data=code_data,
                )
            )

        # 4. Tạo Edges giữa Code và Code
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

        # 5. Tạo Edges liên kết giữa các Tính năng (Feature Aggregation Edges)
        seen_feature_edges: set[tuple[str, str]] = set()
        for edge in code_graph.edges:
            src_feat = node_feature_map.get(edge.source)
            tgt_feat = node_feature_map.get(edge.target)
            if src_feat and tgt_feat and src_feat != tgt_feat:
                edge_pair = (src_feat, tgt_feat)
                if edge_pair not in seen_feature_edges:
                    seen_feature_edges.add(edge_pair)
                    src_group = f"group_{src_feat}"
                    tgt_group = f"group_{tgt_feat}"
                    if src_group in valid_node_ids and tgt_group in valid_node_ids:
                        graph_edges.append(
                            VisualGraphEdge(
                                id=f"e_feat_{src_feat}_{tgt_feat}",
                                source=src_group,
                                target=tgt_group,
                                relation="depends_on",
                                is_mismatch=False,
                                label="DEPENDS_ON",
                                is_aggregated=True,
                            )
                        )

        # 6. Tạo Edges đối soát giữa Claim và Code (verifies_against)
        mismatch_edges_count = 0
        for witness in mismatch_witnesses:
            claim_node_id = f"claim_{witness.claim_id}"
            # Tìm node code tương ứng với witness path (ưu tiên class hoặc function)
            candidates = [
                n
                for n in graph_nodes
                if n.type == "code_node"
                and n.data.location.get("path") == witness.code_location.path
            ]
            candidates.sort(
                key=lambda n: 2 if n.data.kind in ("CLASS", "FUNCTION") else 1,
                reverse=True,
            )
            target_code_node = candidates[0] if candidates else None

            if claim_node_id in valid_node_ids and target_code_node:
                mismatch_edges_count += 1
                graph_edges.append(
                    VisualGraphEdge(
                        id=f"edge_mismatch_{witness.claim_id.hex[:6]}",
                        source=claim_node_id,
                        target=target_code_node.id,
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
                    candidates = [
                        n
                        for n in graph_nodes
                        if n.type == "code_node" and n.data.location.get("path") == ev.path
                    ]
                    candidates.sort(
                        key=lambda n: 2 if n.data.kind in ("CLASS", "FUNCTION") else 1,
                        reverse=True,
                    )
                    target_code_node = candidates[0] if candidates else None
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

        # 7. Tính toán Metrics
        mismatched_nodes = sum(1 for n in graph_nodes if n.data.has_mismatch)
        important_nodes = sum(1 for n in graph_nodes if n.data.is_important)
        total_claims = len(verdicts)
        consistent_claims = sum(
            1 for r in verdicts if r.verdict == CodeConsistencyVerdict.CONSISTENT
        )
        consistency_score = round(consistent_claims / total_claims, 4) if total_claims > 0 else 1.0

        metrics = VisualGraphMetrics(
            total_nodes=len(graph_nodes),
            total_edges=len(graph_edges),
            important_nodes_count=important_nodes,
            mismatched_nodes_count=mismatched_nodes,
            mismatched_edges_count=mismatch_edges_count,
            consistency_score=consistency_score,
        )

        response = VisualGraphResponse(
            submission_id=submission_id,
            run_id=run_id,
            nodes=graph_nodes,
            edges=graph_edges,
            metrics=metrics,
            mismatch_witnesses=mismatch_witnesses,
        )

        # Lọc đồ thị theo filter_mode và min_importance nếu có yêu cầu
        return response.filtered(filter_mode=filter_mode, min_importance=min_importance)
