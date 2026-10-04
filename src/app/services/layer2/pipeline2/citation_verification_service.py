from statistics import fmean

from app.adapters.bm25_retriever import BM25Retriever
from app.adapters.llm_citation_judge import LLMCitationJudge
from app.core.config import Settings
from app.schemas.p2_schema import (
    AtomAssessment,
    AtomicClaim,
    CitationEvidence,
    CitationResultStatus,
    CitationVerdict,
    CitationVerificationInput,
    CitationVerificationResult,
    VerificationStage,
)


class CitationVerificationService:
    """Run the staged, confidence-aware citation-verification policy for one claim-reference pair.

    Implements:
    1. Atomic claim decomposition (SciLens-recommended decoupling).
    2. Phase 1: Local / Abstract-level evidence verification.
    3. Confidence-aware escalation: Any NEI or SUPPORT/REFUTE with confidence < threshold
       escalates to Full-Text RAG (using BM25 query retrieval) and Table/Figure checks.
    4. Exact atomic aggregation: A claim is REFUTED if any atomic claim is contradicted;
       SUPPORTED if all atomic claims are supported; otherwise NEI.
    """

    def __init__(
        self,
        judge: LLMCitationJudge,
        settings: Settings,
        retriever: BM25Retriever | None = None,
    ) -> None:
        self.judge = judge
        self.settings = settings
        self.retriever = retriever or BM25Retriever()

    async def verify(
        self,
        data: CitationVerificationInput,
        evidence: list[CitationEvidence],
    ) -> CitationVerificationResult:
        if not evidence:
            return CitationVerificationResult(
                claim_id=data.claim_id,
                verdict=CitationVerdict.NEI,
                confidence=0,
                status=CitationResultStatus.REQUIRES_REVIEW,
                verification_stage=VerificationStage.LOCAL,
                requires_review=True,
                reason_codes=["NO_EVIDENCE_AVAILABLE"],
                stage_history=[VerificationStage.LOCAL],
                rationale="No local, abstract, full-text, table, or figure evidence is available.",
            )

        atomic_claims = await self.judge.decompose(data)
        initial_evidence = [
            item for item in evidence if item.access_status in {None, "local", "abstract"}
        ]
        full_text_evidence = [
            item
            for item in evidence
            if item.access_status == "full_text" and not self._is_table_or_figure(item)
        ]
        table_figure_evidence = [item for item in evidence if self._is_table_or_figure(item)]

        history: list[VerificationStage] = []
        used_evidence: list[CitationEvidence] = []
        latest: CitationVerificationResult | None = None
        stages: list[tuple[VerificationStage, list[CitationEvidence]]] = []

        if initial_evidence:
            initial_stage = (
                VerificationStage.ABSTRACT
                if any(item.access_status == "abstract" for item in initial_evidence)
                else VerificationStage.LOCAL
            )
            stages.append((initial_stage, initial_evidence))

        if full_text_evidence:
            stages.append((VerificationStage.FULL_TEXT, full_text_evidence))

        if table_figure_evidence:
            stages.append((VerificationStage.TABLE_FIGURE, table_figure_evidence))

        for stage, stage_evidence in stages:
            # When escalating to FULL_TEXT or TABLE_FIGURE, rank passages via BM25 retrieval
            if stage in {VerificationStage.FULL_TEXT, VerificationStage.TABLE_FIGURE}:
                query = self._build_retrieval_query(data, atomic_claims)
                stage_candidates = self.retriever.rank(
                    query=query,
                    evidence=stage_evidence,
                    top_k=self.settings.citation_judge_max_evidence_items,
                )
            else:
                stage_candidates = stage_evidence

            latest = await self._judge_stage(data, atomic_claims, stage, stage_candidates)
            history.append(stage)
            used_evidence = self._merge_evidence(used_evidence, latest.evidence)
            latest.evidence = used_evidence
            latest.stage_history = list(history)

            # Confidence-aware escalation check:
            # If high-confidence SUPPORT or REFUTE is achieved, exit early to save cost/latency.
            if not latest.requires_review:
                return latest

        if latest is None:
            return CitationVerificationResult(
                claim_id=data.claim_id,
                verdict=CitationVerdict.NEI,
                confidence=0,
                status=CitationResultStatus.REQUIRES_REVIEW,
                verification_stage=VerificationStage.LOCAL,
                requires_review=True,
                reason_codes=["NO_USABLE_EVIDENCE"],
                atomic_claims=atomic_claims,
                stage_history=[VerificationStage.LOCAL],
                rationale=(
                    "Evidence exists but none is usable by the configured verification stages."
                ),
            )
        return latest

    async def _judge_stage(
        self,
        data: CitationVerificationInput,
        atomic_claims: list[AtomicClaim],
        stage: VerificationStage,
        evidence: list[CitationEvidence],
    ) -> CitationVerificationResult:
        selected = self._bounded_evidence(evidence)
        assessments = await self.judge.judge(data, atomic_claims, selected)
        verdict = self._aggregate_verdict(assessments)
        confidence = self._aggregate_confidence(assessments, verdict)
        requires_review = verdict == CitationVerdict.NEI or (
            confidence < self.settings.citation_judge_confidence_threshold
        )
        reason_codes = [self._reason_code(verdict)]
        if confidence < self.settings.citation_judge_confidence_threshold:
            reason_codes.append("LOW_CONFIDENCE")
        return CitationVerificationResult(
            claim_id=data.claim_id,
            verdict=verdict,
            confidence=confidence,
            status=(
                CitationResultStatus.REQUIRES_REVIEW
                if requires_review
                else CitationResultStatus.SUCCEEDED
            ),
            verification_stage=stage,
            requires_review=requires_review,
            reason_codes=reason_codes,
            evidence=selected,
            atomic_claims=atomic_claims,
            atom_assessments=assessments,
            rationale=" ".join(
                f"{assessment.atom_id}: {assessment.rationale}" for assessment in assessments
            ),
        )

    def _bounded_evidence(self, evidence: list[CitationEvidence]) -> list[CitationEvidence]:
        result: list[CitationEvidence] = []
        seen: set[object] = set()
        remaining = self.settings.citation_judge_max_input_chars
        for item in evidence:
            if (
                item.source_id in seen
                or len(result) >= self.settings.citation_judge_max_evidence_items
            ):
                continue
            if remaining <= 0:
                break
            text = item.text.strip()
            if not text:
                continue
            selected = item.model_copy(update={"text": text[:remaining]})
            result.append(selected)
            seen.add(item.source_id)
            remaining -= len(selected.text)
        return result

    @staticmethod
    def _build_retrieval_query(
        data: CitationVerificationInput, atomic_claims: list[AtomicClaim]
    ) -> str:
        parts = [data.text_content]
        for atom in atomic_claims:
            if atom.text_content != data.text_content:
                parts.append(atom.text_content)
        return " ".join(parts)

    @staticmethod
    def _is_table_or_figure(evidence: CitationEvidence) -> bool:
        block_type = str(evidence.location.get("block_type", "")).lower()
        return block_type in {"table", "figure", "caption"}

    @staticmethod
    def _merge_evidence(
        existing: list[CitationEvidence], incoming: list[CitationEvidence]
    ) -> list[CitationEvidence]:
        by_source = {item.source_id: item for item in existing}
        by_source.update({item.source_id: item for item in incoming})
        return list(by_source.values())

    @staticmethod
    def _aggregate_verdict(assessments: list[AtomAssessment]) -> CitationVerdict:
        """Aggregate verdicts of atomic claims into an overall claim verdict.

        Rule:
        - If any atom is REFUTE -> REFUTE (contradiction falsifies the citation claim).
        - If all atoms are SUPPORT -> SUPPORT.
        - Otherwise (mixture of SUPPORT and NEI, or all NEI) -> NEI.
        """
        verdicts = {item.verdict for item in assessments}
        if CitationVerdict.REFUTE in verdicts:
            return CitationVerdict.REFUTE
        if verdicts == {CitationVerdict.SUPPORT}:
            return CitationVerdict.SUPPORT
        return CitationVerdict.NEI

    @staticmethod
    def _aggregate_confidence(assessments: list[AtomAssessment], verdict: CitationVerdict) -> float:
        """Aggregate confidence across atomic assessments for the determined verdict."""
        relevant = [item.confidence for item in assessments if item.verdict == verdict]
        if not relevant:
            relevant = [item.confidence for item in assessments]
        return min(relevant) if verdict != CitationVerdict.NEI else fmean(relevant)

    @staticmethod
    def _reason_code(verdict: CitationVerdict) -> str:
        return {
            CitationVerdict.SUPPORT: "CITATION_SUPPORTED",
            CitationVerdict.REFUTE: "CITATION_REFUTED",
            CitationVerdict.NEI: "CITATION_INSUFFICIENT_EVIDENCE",
        }[verdict]
