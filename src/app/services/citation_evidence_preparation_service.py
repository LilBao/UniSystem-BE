from app.schemas.p2_schema import (
    CitationEvidence,
    CitationResultStatus,
    CitationVerificationInput,
    CitationVerificationResult,
    VerificationStage,
)


class CitationEvidencePreparationService:
    async def prepare(
        self,
        data: CitationVerificationInput,
        evidence: list[CitationEvidence],
    ) -> CitationVerificationResult:
        # TODO Phase 2: decompose claims and use an LLM to judge citation evidence.
        if evidence:
            return CitationVerificationResult(
                claim_id=data.claim_id,
                status=CitationResultStatus.REQUIRES_REVIEW,
                verification_stage=self._evidence_stage(evidence),
                requires_review=True,
                reason_codes=["PHASE1_EVIDENCE_READY"],
                evidence=evidence,
                rationale="Local or abstract evidence is ready for citation verification.",
            )
        return CitationVerificationResult(
            claim_id=data.claim_id,
            status=CitationResultStatus.REQUIRES_REVIEW,
            verification_stage=VerificationStage.LOCAL,
            requires_review=True,
            reason_codes=["NO_LOCAL_OR_ABSTRACT_EVIDENCE"],
            rationale="No local or abstract evidence is available.",
        )

    @staticmethod
    def _evidence_stage(evidence: list[CitationEvidence]) -> VerificationStage:
        return (
            VerificationStage.ABSTRACT
            if any(item.access_status == "abstract" for item in evidence)
            else VerificationStage.LOCAL
        )
