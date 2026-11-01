from app.adapters.llm_code_judge import LLMCodeConsistencyJudge
from app.schemas.code_graph_schema import CodeGraph
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
from app.services.layer2.pipeline3.code_retrieval import (
    CodeIndex,
    resolve_ref_to_span,
)
from app.services.layer2.pipeline3.code_text import extract_claim_terms


class CodeSemanticJudgeService:
    def __init__(
        self,
        confidence_threshold: float = 0.70,
        llm: LLMCodeConsistencyJudge | None = None,
        max_cards: int = 6,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.llm = llm
        self.max_cards = max_cards
        self._index_cache: dict[int, CodeIndex] = {}

    @property
    def model(self) -> str | None:
        return self.llm.model if self.llm else None

    @property
    def prompt_version(self) -> str:
        return self.llm.prompt_version if self.llm else "1.0"

    @property
    def version(self) -> str:
        return self.llm.version if self.llm else "heuristic-lexical-1"

    @property
    def uses_llm(self) -> bool:
        return bool(self.llm and self.llm.is_configured)

    def _get_or_create_index(self, code_graph: CodeGraph) -> CodeIndex:
        graph_key = id(code_graph)
        if graph_key not in self._index_cache:
            self._index_cache[graph_key] = CodeIndex(code_graph)
        return self._index_cache[graph_key]

    async def judge(self, work_item: P3WorkItem, code_graph: CodeGraph) -> CodeConsistencyResult:
        """Thực hiện đánh giá ngữ nghĩa Tầng 2 bằng LLM / Code Index Retriever."""
        claim_text = work_item.text_content.strip()
        index = self._get_or_create_index(code_graph)

        # 1. Bóc tách từ khóa claim (bằng tiếng Việt/Anh/acronyms)
        lexical_terms = extract_claim_terms(claim_text)

        # 2. Sử dụng LLM mở rộng thuật ngữ nếu được cấu hình
        llm_terms: list[str] = []
        if self.uses_llm and self.llm:
            llm_terms = await self.llm.expand_search_terms(claim_text)

        combined_terms: list[str] = []
        seen_terms: set[str] = set()
        for t in [*lexical_terms, *llm_terms]:
            if t not in seen_terms:
                seen_terms.add(t)
                combined_terms.append(t)

        # 3. Thu thập thẻ bằng chứng code (Candidate Context Cards)
        cards = index.search(combined_terms, top_k=self.max_cards)

        if not cards or not combined_terms:
            # Không tìm thấy module tương ứng -> NEI
            return CodeConsistencyResult(
                claim_id=work_item.claim_id,
                verdict=CodeConsistencyVerdict.NEI,
                confidence=0.60,
                verification_stage=VerificationStage.SEMANTIC,
                requires_review=True,
                reason_codes=["NO_SEMANTIC_EVIDENCE"],
                stage_history=[VerificationStage.STRUCTURAL, VerificationStage.SEMANTIC],
                rationale=(
                    "Không tìm thấy đoạn mã nguồn hoặc cấu trúc hàm nào phản ánh "
                    "khẳng định được nêu trong báo cáo."
                ),
                evidence_locations=[],
                mismatch_witnesses=[],
            )

        # 4. Phân tích đối chiếu ngữ nghĩa (LLM Judge hoặc Degraded Lexical)
        matching_spans: list[CodeLocationSpan] = []
        mismatch_witnesses: list[MismatchWitness] = []
        reason_codes: list[str] = []

        if self.uses_llm and self.llm:
            try:
                judgement = await self.llm.judge(claim_text, cards)
                verdict = judgement.verdict
                confidence = judgement.confidence
                rationale = judgement.rationale
                reason_codes = [f"LLM_JUDGE_{verdict.value}"]

                # Ánh xạ supporting refs sang code location spans
                for ref in judgement.supporting_refs:
                    span = resolve_ref_to_span(cards, ref)
                    if span and span not in matching_spans:
                        matching_spans.append(span)

                if (
                    not matching_spans
                    and cards
                    and verdict
                    in (
                        CodeConsistencyVerdict.CONSISTENT,
                        CodeConsistencyVerdict.PARTIAL,
                    )
                ):
                    matching_spans.append(cards[0].span)

                # Xử lý mismatch witness nếu INCONSISTENT
                if verdict == CodeConsistencyVerdict.INCONSISTENT:
                    target_span = cards[0].span
                    if judgement.mismatch and judgement.mismatch.ref:
                        resolved = resolve_ref_to_span(cards, judgement.mismatch.ref)
                        if resolved:
                            target_span = resolved

                    expected = (
                        judgement.mismatch.expected_behavior
                        if judgement.mismatch
                        else "Theo khẳng định trong báo cáo"
                    )
                    actual = (
                        judgement.mismatch.actual_behavior
                        if judgement.mismatch
                        else "Hành vi thực tế trong mã nguồn"
                    )

                    snippet_text = (
                        f"Path: {target_span.path} "
                        f"(Lines {target_span.start_line}-{target_span.end_line})"
                    )
                    witness = self.create_semantic_mismatch_witness(
                        work_item=work_item,
                        location=target_span,
                        snippet=snippet_text,
                        expected=expected,
                        actual=actual,
                        rationale=rationale,
                    )
                    mismatch_witnesses.append(witness)

            except Exception as exc:
                # LLM call thất bại -> fallback sang degraded lexical
                best_card = cards[0]
                matching_spans.append(best_card.span)
                verdict = (
                    CodeConsistencyVerdict.PARTIAL
                    if best_card.coverage >= 0.5 and len(best_card.matched_terms) >= 2
                    else CodeConsistencyVerdict.NEI
                )
                confidence = 0.50
                matched_str = ", ".join(best_card.matched_terms)
                rationale = (
                    f"LLM Judge tạm thời không khả dụng ({exc}). Đối chiếu lexical ghi nhận "
                    f"file '{best_card.path}' khớp các từ khóa: {matched_str}."
                )
                reason_codes = ["LLM_JUDGE_FAILED", "DEGRADED_LEXICAL"]
        else:
            # Chế độ không có LLM: Lexical-only degraded
            best_card = cards[0]
            matching_spans.append(best_card.span)
            if best_card.coverage >= 0.5 and len(best_card.matched_terms) >= 2:
                verdict = CodeConsistencyVerdict.PARTIAL
                confidence = 0.55
                rationale = (
                    f"Đối soát lexical ghi nhận các từ khóa ({', '.join(best_card.matched_terms)}) "
                    f"tại '{best_card.path}'. Cần đối soát bổ sung (chế độ không có LLM)."
                )
                reason_codes = ["LEXICAL_PARTIAL_MATCH", "LEXICAL_ONLY"]
            else:
                verdict = CodeConsistencyVerdict.NEI
                confidence = 0.50
                rationale = "Không đủ bằng chứng mã nguồn tương ứng với khẳng định."
                reason_codes = ["NO_SEMANTIC_EVIDENCE", "LEXICAL_ONLY"]

        requires_review = (
            confidence < self.confidence_threshold
            or verdict == CodeConsistencyVerdict.INCONSISTENT
            or verdict == CodeConsistencyVerdict.NEI
            or verdict == CodeConsistencyVerdict.PARTIAL
        )

        return CodeConsistencyResult(
            claim_id=work_item.claim_id,
            verdict=verdict,
            confidence=confidence,
            verification_stage=VerificationStage.SEMANTIC,
            requires_review=requires_review,
            reason_codes=reason_codes,
            stage_history=[VerificationStage.STRUCTURAL, VerificationStage.SEMANTIC],
            rationale=rationale,
            evidence_locations=matching_spans,
            mismatch_witnesses=mismatch_witnesses,
        )

    def create_semantic_mismatch_witness(
        self,
        work_item: P3WorkItem,
        location: CodeLocationSpan,
        snippet: str,
        expected: str,
        actual: str,
        rationale: str,
    ) -> MismatchWitness:
        return MismatchWitness(
            claim_id=work_item.claim_id,
            claim_text=work_item.text_content,
            report_location=work_item.source_span,
            code_location=location,
            code_snippet=snippet,
            mismatch_type=HighlightKind.MISMATCH_SEMANTIC,
            severity=HighlightSeverity.CRITICAL,
            expected_behavior=expected,
            actual_behavior=actual,
            rationale=rationale,
        )
