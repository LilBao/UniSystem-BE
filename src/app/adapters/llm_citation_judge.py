from app.schemas.p2_schema import (
    CitationEvidence,
    CitationVerificationInput,
    CitationVerificationResult,
)


class LLMCitationJudge:
    """Reserved for the Phase 2 citation judge."""

    async def judge(
        self,
        data: CitationVerificationInput,
        evidence: list[CitationEvidence],
    ) -> CitationVerificationResult:
        # TODO Phase 2: implement claim decomposition and LLM citation judgment.
        raise NotImplementedError("TODO Phase 2: LLM citation judge")
