import math
from collections import defaultdict

from app.schemas.code_graph_schema import CodeGraph, GraphNode
from app.schemas.p3_schema import (
    CodeEvidenceCard,
    CodeEvidenceSymbol,
    CodeLocationSpan,
)
from app.services.layer2.pipeline3.code_roles import (
    detect_file_role,
    get_file_stem,
    is_boilerplate_path,
)
from app.services.layer2.pipeline3.code_text import (
    fold_diacritics,
    identifier_tokens,
    normalize_token,
)


class FileDocContext:
    def __init__(self, path: str) -> None:
        self.path = path
        self.role = detect_file_role(path)
        self.is_boilerplate = is_boilerplate_path(path)
        self.nodes: list[GraphNode] = []
        self.calls: list[str] = []
        self.imports: list[str] = []
        self.min_line = 1000000
        self.max_line = 1
        # term -> weighted frequency
        self.term_weights: dict[str, float] = defaultdict(float)

    def add_node(self, node: GraphNode) -> None:
        self.nodes.append(node)
        if node.location:
            self.min_line = min(self.min_line, node.location.start_line)
            self.max_line = max(self.max_line, node.location.end_line)

        # Trọng số token của tên hàm/lớp
        weight = 1.5 if node.kind in ("class", "interface", "record") else 1.2
        for tok in identifier_tokens(node.name):
            self.term_weights[tok] += weight

    def add_call(self, caller_name: str, callee_name: str) -> None:
        call_str = f"{caller_name} -> {callee_name}"
        if call_str not in self.calls and len(self.calls) < 20:
            self.calls.append(call_str)
        # Thêm token của callee với trọng số 0.6
        for tok in identifier_tokens(callee_name):
            self.term_weights[tok] += 0.6

    def add_import(self, imp_name: str) -> None:
        if imp_name not in self.imports and len(self.imports) < 15:
            self.imports.append(imp_name)
        for tok in identifier_tokens(imp_name):
            self.term_weights[tok] += 0.8


class CodeIndex:
    """Chỉ mục ngữ nghĩa và truy hồi BM25 cấp độ File trong CodeGraph."""

    def __init__(self, code_graph: CodeGraph) -> None:
        self.code_graph = code_graph
        self.docs: dict[str, FileDocContext] = {}
        self.node_id_to_file: dict[str, str] = {}
        self.vocab: set[str] = set()
        self._build_index()

    def _build_index(self) -> None:
        nodes_by_id = {n.id: n for n in self.code_graph.nodes}

        # 1. Gán node có location vào file
        for node in self.code_graph.nodes:
            if node.location:
                path = node.location.path
                self.node_id_to_file[node.id] = path
                if path not in self.docs:
                    self.docs[path] = FileDocContext(path)
                self.docs[path].add_node(node)

        # 2. Xử lý các node không có location (thư viện ngoài, annotations...)
        # Gán theo incident edges
        for edge in self.code_graph.edges:
            src_node = nodes_by_id.get(edge.source)
            tgt_node = nodes_by_id.get(edge.target)

            src_file = self.node_id_to_file.get(edge.source)
            tgt_file = self.node_id_to_file.get(edge.target)

            # Nếu target không có file nhưng edge có location
            if not tgt_file and edge.location:
                tgt_file = edge.location.path

            if src_file and tgt_node and not tgt_node.location:
                # src_file sử dụng tgt_node
                doc = self.docs.get(src_file)
                if doc:
                    doc.add_import(tgt_node.name)

            if src_file and tgt_file and src_file != tgt_file:
                if edge.relation == "calls" and src_node and tgt_node:
                    doc = self.docs.get(src_file)
                    if doc:
                        doc.add_call(src_node.name, tgt_node.name)

        # 3. Bổ sung tokens từ tên file và thư mục
        for path, doc in self.docs.items():
            stem = get_file_stem(path)
            for tok in identifier_tokens(stem):
                doc.term_weights[tok] += 2.0  # Tên file có trọng số cao nhất

            parts = path.replace("\\", "/").split("/")[:-1]
            for part in parts:
                for tok in identifier_tokens(part):
                    doc.term_weights[tok] += 1.0

            for tok in doc.term_weights:
                self.vocab.add(tok)

    def search(self, terms: list[str], top_k: int = 6) -> list[CodeEvidenceCard]:
        """Truy hồi các file/thành phần code có liên quan nhất tới danh sách terms."""
        if not terms or not self.docs:
            return []

        clean_terms: list[str] = []
        for t in terms:
            norm = normalize_token(fold_diacritics(t))
            if norm and norm not in clean_terms:
                clean_terms.append(norm)

        if not clean_terms:
            return []

        # Alias expansion (ví dụ: auth -> authentication, repo -> repository)
        expanded_term_map: dict[str, list[tuple[str, float]]] = {}
        for q in clean_terms:
            expansions: list[tuple[str, float]] = [(q, 1.0)]
            if len(q) >= 4:
                for v in self.vocab:
                    if v != q and (v.startswith(q) or q.startswith(v)):
                        expansions.append((v, 0.65))
            expanded_term_map[q] = expansions

        # Tính IDF
        total_docs = len(self.docs)
        doc_lengths = {p: sum(d.term_weights.values()) for p, d in self.docs.items()}
        avg_doc_len = sum(doc_lengths.values()) / total_docs if total_docs > 0 else 1.0

        doc_scores: dict[str, float] = defaultdict(float)
        matched_terms_per_doc: dict[str, set[str]] = defaultdict(set)

        k1 = 1.2
        b = 0.4

        for orig_q, exp_list in expanded_term_map.items():
            # Gom các từ vựng mở rộng
            vocab_matches = [(w, weight) for w, weight in exp_list if w in self.vocab]
            if not vocab_matches:
                continue

            for word, weight in vocab_matches:
                # df
                df = sum(1 for d in self.docs.values() if word in d.term_weights)
                if df == 0:
                    continue
                idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))

                for path, doc in self.docs.items():
                    tf = doc.term_weights.get(word, 0.0)
                    if tf > 0:
                        matched_terms_per_doc[path].add(orig_q)
                        doc_len = doc_lengths.get(path, 1.0)
                        denom = tf + k1 * (1.0 - b + b * (doc_len / avg_doc_len))
                        term_score = idf * ((tf * (k1 + 1.0)) / denom) * weight
                        doc_scores[path] += term_score

        # Lọc và xếp hạng
        scored_docs: list[tuple[str, float, float, list[str]]] = []
        for path, score in doc_scores.items():
            matched = sorted(matched_terms_per_doc[path])
            coverage = len(matched) / len(clean_terms)
            # Ưu tiên các file non-boilerplate khi bằng điểm
            doc = self.docs[path]
            final_score = score * (0.6 if doc.is_boilerplate else 1.0)
            # Thưởng thêm nếu coverage cao
            final_score *= 1.0 + (coverage * 0.5)
            scored_docs.append((path, final_score, coverage, matched))

        scored_docs.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scored_docs[:top_k]

        cards: list[CodeEvidenceCard] = []
        for idx, (path, score, coverage, matched) in enumerate(top_candidates):
            doc = self.docs[path]
            ref = f"f{idx + 1}"

            # Trích xuất các symbol trong file
            symbols: list[CodeEvidenceSymbol] = []
            for s_idx, node in enumerate(doc.nodes[:12]):
                if node.location:
                    symbols.append(
                        CodeEvidenceSymbol(
                            ref=f"{ref}.s{s_idx + 1}",
                            name=node.name,
                            kind=node.kind,
                            start_line=node.location.start_line,
                            end_line=node.location.end_line,
                        )
                    )

            min_line = doc.min_line if doc.min_line <= doc.max_line else 1
            max_line = max(doc.max_line, min_line)

            cards.append(
                CodeEvidenceCard(
                    ref=ref,
                    path=path,
                    score=round(score, 4),
                    coverage=round(coverage, 2),
                    matched_terms=matched,
                    symbols=symbols,
                    calls=doc.calls[:10],
                    imports=doc.imports[:8],
                    span=CodeLocationSpan(
                        path=path,
                        start_line=min_line,
                        end_line=max_line,
                    ),
                )
            )

        return cards


def resolve_ref_to_span(cards: list[CodeEvidenceCard], ref: str) -> CodeLocationSpan | None:
    """Ánh xạ một ref (f1 hoặc f1.s2) về CodeLocationSpan tương ứng."""
    clean_ref = ref.strip().lower()
    for card in cards:
        if card.ref.lower() == clean_ref:
            return card.span
        for sym in card.symbols:
            if sym.ref.lower() == clean_ref:
                return CodeLocationSpan(
                    path=card.path,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                )
    return None
