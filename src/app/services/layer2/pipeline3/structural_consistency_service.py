"""StructuralConsistencyService (Tier 1: EXTRACTED).

Deterministic, AST-level verification between natural language claims and
Graphify CodeGraph representations. Matches extracted symbols (classes,
functions, module imports, framework mentions) with zero LLM overhead.
"""

import re

from app.schemas.code_graph_schema import CodeGraph, GraphNode
from app.schemas.p3_schema import (
    CodeConsistencyResult,
    CodeConsistencyVerdict,
    CodeLocationSpan,
    HighlightKind,
    HighlightSeverity,
    MismatchWitness,
    P3WorkItem,
    VerificationStage,
)

# Known framework mutually-exclusive groups (if report claims group A but code imports group B)
FRAMEWORK_GROUPS: dict[str, set[str]] = {
    "pytorch": {"torch", "torchvision", "torchaudio", "pytorch_lightning", "lightning"},
    "tensorflow": {"tensorflow", "tf", "keras"},
    "sklearn": {"sklearn", "scikit-learn"},
    "fastapi": {"fastapi", "starlette"},
    "flask": {"flask"},
    "django": {"django"},
}

KNOWN_OPTIMIZERS = {"adam", "adamw", "sgd", "rmsprop", "adagrad", "adadelta"}
KNOWN_ARCHITECTURES = {
    "resnet",
    "vgg",
    "bert",
    "yolo",
    "transformer",
    "lstm",
    "gru",
    "cnn",
    "mlp",
    "svm",
    "randomforest",
    "unet",
    "efficientnet",
}


class StructuralConsistencyService:
    def __init__(self) -> None:
        pass

    async def verify(
        self, work_item: P3WorkItem, code_graph: CodeGraph
    ) -> CodeConsistencyResult | None:
        """Kiểm chứng cấu trúc Tầng 1.

        Trả về CodeConsistencyResult nếu khớp hoặc mâu thuẫn tất định;
        Trả về None nếu không đủ căn cứ cấu trúc (cần leo thang Tầng 2).
        """
        claim_text = work_item.text_content.lower()

        # 1. Trích xuất các thực thể trong đồ thị mã nguồn
        nodes_by_name: dict[str, list[GraphNode]] = {}
        imported_modules: set[str] = set()

        for node in code_graph.nodes:
            norm_name = node.name.lower()
            nodes_by_name.setdefault(norm_name, []).append(node)
            if node.kind in ("module", "import"):
                imported_modules.add(norm_name)

        # 2. Kiểm tra Framework / Thư viện mâu thuẫn hoặc khớp
        framework_match_result = self._check_framework_consistency(
            work_item, claim_text, imported_modules, code_graph
        )
        if framework_match_result is not None:
            return framework_match_result

        # 3. Kiểm tra Optimizer / Thuật toán mâu thuẫn hoặc khớp
        optimizer_result = self._check_optimizer_consistency(
            work_item, claim_text, nodes_by_name, code_graph
        )
        if optimizer_result is not None:
            return optimizer_result

        # 4. Kiểm tra sự tồn tại của các Định danh (Identifier matching: Class / Function)
        identifier_result = self._check_identifiers_match(work_item, claim_text, nodes_by_name)
        if identifier_result is not None:
            return identifier_result

        # Không đủ căn cứ tĩnh -> Chuyển tiếp Tầng 2
        return None

    def _check_framework_consistency(
        self,
        work_item: P3WorkItem,
        claim_text: str,
        imported_modules: set[str],
        code_graph: CodeGraph,
    ) -> CodeConsistencyResult | None:
        for group_name, identifiers in FRAMEWORK_GROUPS.items():
            claimed_in_text = any(ident in claim_text for ident in identifiers)
            if not claimed_in_text:
                continue

            # Báo cáo khẳng định dùng group_name
            found_in_code = any(
                any(ident in mod for ident in identifiers) for mod in imported_modules
            )

            # Tìm xem có framework đối lập hay không (ví dụ claim pytorch nhưng chỉ có tensorflow)
            competing_groups = [g for g in ("pytorch", "tensorflow") if g != group_name]
            competing_found = [
                g
                for g in competing_groups
                if any(
                    any(ident in mod for ident in FRAMEWORK_GROUPS[g]) for mod in imported_modules
                )
            ]

            if found_in_code:
                matched_nodes = [
                    n
                    for n in code_graph.nodes
                    if any(ident in n.name.lower() for ident in identifiers)
                    and n.location is not None
                ]
                evidence_locs = [
                    CodeLocationSpan(
                        path=n.location.path,  # type: ignore[union-attr]
                        start_line=n.location.start_line,  # type: ignore[union-attr]
                        end_line=n.location.end_line,  # type: ignore[union-attr]
                    )
                    for n in matched_nodes[:3]
                ]
                return CodeConsistencyResult(
                    claim_id=work_item.claim_id,
                    verdict=CodeConsistencyVerdict.CONSISTENT,
                    confidence=0.95,
                    verification_stage=VerificationStage.STRUCTURAL,
                    requires_review=False,
                    reason_codes=["STRUCTURAL_MATCH", f"FRAMEWORK_{group_name.upper()}_MATCH"],
                    stage_history=[VerificationStage.STRUCTURAL],
                    rationale=(
                        f"Mã nguồn có khai báo và nhập thư viện {group_name.title()} "
                        "khớp với báo cáo."
                    ),
                    evidence_locations=evidence_locs,
                )

            if competing_found:
                # Mâu thuẫn rõ ràng: Claim PyTorch nhưng code dùng TensorFlow
                competing_name = competing_found[0]
                competing_nodes = [
                    n
                    for n in code_graph.nodes
                    if any(ident in n.name.lower() for ident in FRAMEWORK_GROUPS[competing_name])
                    and n.location is not None
                ]
                if competing_nodes and competing_nodes[0].location:
                    first_loc = competing_nodes[0].location
                    loc = CodeLocationSpan(
                        path=first_loc.path,
                        start_line=first_loc.start_line,
                        end_line=first_loc.end_line,
                    )
                else:
                    loc = CodeLocationSpan(path="requirements.txt", start_line=1, end_line=1)
                witness = MismatchWitness(
                    claim_id=work_item.claim_id,
                    claim_text=work_item.text_content,
                    report_location=work_item.source_span,
                    code_location=loc,
                    code_snippet=f"Imported framework: {competing_name}",
                    mismatch_type=HighlightKind.MISMATCH_STRUCTURAL,
                    severity=HighlightSeverity.CRITICAL,
                    expected_behavior=f"Sử dụng framework {group_name.title()}",
                    actual_behavior=f"Mã nguồn thực tế sử dụng {competing_name.title()}",
                    rationale=(
                        f"Báo cáo khẳng định dùng {group_name.title()} nhưng mã nguồn "
                        f"nhập {competing_name.title()}."
                    ),
                )
                return CodeConsistencyResult(
                    claim_id=work_item.claim_id,
                    verdict=CodeConsistencyVerdict.INCONSISTENT,
                    confidence=0.95,
                    verification_stage=VerificationStage.STRUCTURAL,
                    requires_review=True,
                    reason_codes=["STRUCTURAL_MISMATCH", "FRAMEWORK_MISMATCH"],
                    stage_history=[VerificationStage.STRUCTURAL],
                    rationale=witness.rationale,
                    evidence_locations=[loc],
                    mismatch_witnesses=[witness],
                )

        return None

    def _check_optimizer_consistency(
        self,
        work_item: P3WorkItem,
        claim_text: str,
        nodes_by_name: dict[str, list[GraphNode]],
        code_graph: CodeGraph,
    ) -> CodeConsistencyResult | None:
        claimed_optimizers = [opt for opt in KNOWN_OPTIMIZERS if opt in claim_text]
        if not claimed_optimizers:
            return None

        claimed_opt = claimed_optimizers[0]
        # Tìm optimizer thực tế trong code
        found_in_code = [
            opt for opt in KNOWN_OPTIMIZERS if any(opt in name for name in nodes_by_name)
        ]

        if claimed_opt in found_in_code:
            matched_nodes = [
                n
                for n in code_graph.nodes
                if claimed_opt in n.name.lower() and n.location is not None
            ]
            evidence_locs = [
                CodeLocationSpan(
                    path=n.location.path,  # type: ignore[union-attr]
                    start_line=n.location.start_line,  # type: ignore[union-attr]
                    end_line=n.location.end_line,  # type: ignore[union-attr]
                )
                for n in matched_nodes[:2]
            ]
            return CodeConsistencyResult(
                claim_id=work_item.claim_id,
                verdict=CodeConsistencyVerdict.CONSISTENT,
                confidence=0.92,
                verification_stage=VerificationStage.STRUCTURAL,
                requires_review=False,
                reason_codes=["STRUCTURAL_MATCH", "OPTIMIZER_MATCH"],
                stage_history=[VerificationStage.STRUCTURAL],
                rationale=(
                    f"Thuật toán tối ưu hóa {claimed_opt.upper()} được tìm thấy trong mã nguồn."
                ),
                evidence_locations=evidence_locs,
            )

        competing_opts = [opt for opt in found_in_code if opt != claimed_opt]
        if competing_opts:
            competing_opt = competing_opts[0]
            competing_nodes = [
                n
                for n in code_graph.nodes
                if competing_opt in n.name.lower() and n.location is not None
            ]
            if competing_nodes and competing_nodes[0].location:
                first_opt_loc = competing_nodes[0].location
                loc = CodeLocationSpan(
                    path=first_opt_loc.path,
                    start_line=first_opt_loc.start_line,
                    end_line=first_opt_loc.end_line,
                )
            else:
                loc = CodeLocationSpan(path="train.py", start_line=1, end_line=1)
            witness = MismatchWitness(
                claim_id=work_item.claim_id,
                claim_text=work_item.text_content,
                report_location=work_item.source_span,
                code_location=loc,
                code_snippet=f"Implemented optimizer: {competing_opt.upper()}",
                mismatch_type=HighlightKind.MISMATCH_STRUCTURAL,
                severity=HighlightSeverity.CRITICAL,
                expected_behavior=f"Sử dụng optimizer {claimed_opt.upper()}",
                actual_behavior=f"Mã nguồn triển khai {competing_opt.upper()}",
                rationale=(
                    f"Báo cáo mô tả {claimed_opt.upper()} nhưng mã nguồn khởi tạo "
                    f"{competing_opt.upper()}."
                ),
            )
            return CodeConsistencyResult(
                claim_id=work_item.claim_id,
                verdict=CodeConsistencyVerdict.INCONSISTENT,
                confidence=0.92,
                verification_stage=VerificationStage.STRUCTURAL,
                requires_review=True,
                reason_codes=["STRUCTURAL_MISMATCH", "OPTIMIZER_MISMATCH"],
                stage_history=[VerificationStage.STRUCTURAL],
                rationale=witness.rationale,
                evidence_locations=[loc],
                mismatch_witnesses=[witness],
            )

        return None

    def _check_identifiers_match(
        self,
        work_item: P3WorkItem,
        claim_text: str,
        nodes_by_name: dict[str, list[GraphNode]],
    ) -> CodeConsistencyResult | None:
        # Tìm các từ viết theo chuẩn CamelCase hoặc snake_case trong câu claim gốc
        words = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", work_item.text_content)
        matched_locs: list[CodeLocationSpan] = []

        for word in words:
            word_lower = word.lower()
            if word_lower in nodes_by_name:
                for node in nodes_by_name[word_lower]:
                    if node.location is not None:
                        matched_locs.append(
                            CodeLocationSpan(
                                path=node.location.path,
                                start_line=node.location.start_line,
                                end_line=node.location.end_line,
                            )
                        )

        if matched_locs:
            return CodeConsistencyResult(
                claim_id=work_item.claim_id,
                verdict=CodeConsistencyVerdict.CONSISTENT,
                confidence=0.90,
                verification_stage=VerificationStage.STRUCTURAL,
                requires_review=False,
                reason_codes=["STRUCTURAL_MATCH", "IDENTIFIER_MATCH"],
                stage_history=[VerificationStage.STRUCTURAL],
                rationale=(
                    "Tìm thấy định danh hàm/lớp/module tương ứng trực tiếp trong cây "
                    "AST đồ thị mã nguồn."
                ),
                evidence_locations=matched_locs[:3],
            )

        return None
