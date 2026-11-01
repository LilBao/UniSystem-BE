from uuid import uuid4

import pytest

from app.core.config import Settings
from app.schemas.p2_schema import (
    AtomAssessment,
    AtomicClaim,
    CitationEvidence,
    CitationResultStatus,
    CitationVerdict,
    CitationVerificationInput,
    VerificationStage,
)
from app.services.layer2.pipeline2.citation_verification_service import CitationVerificationService


class FakeCitationJudge:
    def __init__(self, batches: list[list[AtomAssessment]]) -> None:
        self.batches = batches
        self.calls: list[list[CitationEvidence]] = []

    async def decompose(self, data: CitationVerificationInput) -> list[AtomicClaim]:
        return [AtomicClaim(atom_id="atom-1", text_content=data.text_content)]

    async def judge(
        self,
        data: CitationVerificationInput,
        atomic_claims: list[AtomicClaim],
        evidence: list[CitationEvidence],
    ) -> list[AtomAssessment]:
        self.calls.append(evidence)
        return self.batches.pop(0)


def make_input() -> CitationVerificationInput:
    return CitationVerificationInput(
        claim_id=uuid4(),
        text_content="The proposed method improves accuracy.",
        citation_marker="[1]",
        submission_reference_id=uuid4(),
    )


def make_evidence(access_status: str, *, block_type: str = "text") -> CitationEvidence:
    return CitationEvidence(
        source_type="reference_passage",
        source_id=uuid4(),
        text="The experiment reports the proposed method improves accuracy over the baseline.",
        location={"block_type": block_type},
        access_status=access_status,
    )


def make_service(judge: FakeCitationJudge) -> CitationVerificationService:
    settings = Settings(
        citation_judge_confidence_threshold=0.8,
        citation_judge_max_input_chars=24000,
        citation_judge_max_evidence_items=12,
        citation_judge_max_atomic_claims=8,
    )
    return CitationVerificationService(judge, settings)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_abstract_support_exits_without_full_text() -> None:
    evidence = make_evidence("abstract")
    judge = FakeCitationJudge(
        [
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.91,
                    rationale="The abstract directly reports the claimed improvement.",
                    supporting_evidence_ids=[evidence.source_id],
                )
            ]
        ]
    )

    result = await make_service(judge).verify(make_input(), [evidence])

    assert result.status == CitationResultStatus.SUCCEEDED
    assert result.verdict == CitationVerdict.SUPPORT
    assert result.verification_stage == VerificationStage.ABSTRACT
    assert result.stage_history == [VerificationStage.ABSTRACT]
    assert len(judge.calls) == 1


@pytest.mark.asyncio
async def test_nei_from_abstract_escalates_to_full_text() -> None:
    abstract = make_evidence("abstract")
    full_text = make_evidence("full_text")
    judge = FakeCitationJudge(
        [
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.NEI,
                    confidence=0.45,
                    rationale="The abstract is not specific enough.",
                )
            ],
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.93,
                    rationale="The full text reports the improvement.",
                    supporting_evidence_ids=[full_text.source_id],
                )
            ],
        ]
    )

    result = await make_service(judge).verify(make_input(), [abstract, full_text])

    assert result.status == CitationResultStatus.SUCCEEDED
    assert result.verdict == CitationVerdict.SUPPORT
    assert result.verification_stage == VerificationStage.FULL_TEXT
    assert result.stage_history == [VerificationStage.ABSTRACT, VerificationStage.FULL_TEXT]
    assert len(judge.calls) == 2
    assert judge.calls[1][0].source_id == full_text.source_id
    assert {item.source_id for item in result.evidence} == {
        abstract.source_id,
        full_text.source_id,
    }


@pytest.mark.asyncio
async def test_no_evidence_returns_nei_without_calling_llm() -> None:
    judge = FakeCitationJudge([])

    result = await make_service(judge).verify(make_input(), [])

    assert result.status == CitationResultStatus.REQUIRES_REVIEW
    assert result.verdict == CitationVerdict.NEI
    assert result.confidence == 0
    assert result.reason_codes == ["NO_EVIDENCE_AVAILABLE"]
    assert judge.calls == []


@pytest.mark.asyncio
async def test_refute_atom_overrides_support_atom() -> None:
    evidence = make_evidence("abstract")
    judge = FakeCitationJudge(
        [
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.95,
                    rationale="Accuracy improvement is confirmed.",
                    supporting_evidence_ids=[evidence.source_id],
                ),
                AtomAssessment(
                    atom_id="atom-2",
                    verdict=CitationVerdict.REFUTE,
                    confidence=0.88,
                    rationale="Latency claim is contradicted by Table 3.",
                    contradicting_evidence_ids=[evidence.source_id],
                ),
            ]
        ]
    )

    async def fake_decompose(data: CitationVerificationInput) -> list[AtomicClaim]:
        return [
            AtomicClaim(atom_id="atom-1", text_content="Method improves accuracy."),
            AtomicClaim(atom_id="atom-2", text_content="Method reduces latency."),
        ]

    judge.decompose = fake_decompose  # type: ignore[method-assign]

    result = await make_service(judge).verify(make_input(), [evidence])

    assert result.status == CitationResultStatus.SUCCEEDED
    assert result.verdict == CitationVerdict.REFUTE
    assert result.confidence == 0.88
    assert "CITATION_REFUTED" in result.reason_codes


@pytest.mark.asyncio
async def test_support_and_nei_atoms_result_in_nei() -> None:
    evidence = make_evidence("abstract")
    judge = FakeCitationJudge(
        [
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.90,
                    rationale="First claim is supported.",
                    supporting_evidence_ids=[evidence.source_id],
                ),
                AtomAssessment(
                    atom_id="atom-2",
                    verdict=CitationVerdict.NEI,
                    confidence=0.50,
                    rationale="Second claim has no evidence in abstract.",
                ),
            ]
        ]
    )

    async def fake_decompose(data: CitationVerificationInput) -> list[AtomicClaim]:
        return [
            AtomicClaim(atom_id="atom-1", text_content="Method improves accuracy."),
            AtomicClaim(atom_id="atom-2", text_content="Method runs on mobile."),
        ]

    judge.decompose = fake_decompose  # type: ignore[method-assign]

    result = await make_service(judge).verify(make_input(), [evidence])

    assert result.verdict == CitationVerdict.NEI
    assert result.requires_review is True


@pytest.mark.asyncio
async def test_low_confidence_support_escalates_to_full_text() -> None:
    abstract = make_evidence("abstract")
    full_text = make_evidence("full_text")
    judge = FakeCitationJudge(
        [
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.65,  # below 0.80 threshold
                    rationale="Weak hint of improvement in abstract.",
                    supporting_evidence_ids=[abstract.source_id],
                )
            ],
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.94,  # high confidence in full text
                    rationale="Section 4 details strong empirical improvement.",
                    supporting_evidence_ids=[full_text.source_id],
                )
            ],
        ]
    )

    result = await make_service(judge).verify(make_input(), [abstract, full_text])

    assert result.status == CitationResultStatus.SUCCEEDED
    assert result.verdict == CitationVerdict.SUPPORT
    assert result.confidence == 0.94
    assert result.verification_stage == VerificationStage.FULL_TEXT
    assert result.stage_history == [VerificationStage.ABSTRACT, VerificationStage.FULL_TEXT]
    assert len(judge.calls) == 2


@pytest.mark.asyncio
async def test_bm25_retrieval_reorders_full_text_passages() -> None:
    abstract = make_evidence("abstract")
    distractor = CitationEvidence(
        source_type="reference_passage",
        source_id=uuid4(),
        text="The history of distributed databases began decades ago.",
        location={"block_type": "text"},
        access_status="full_text",
    )
    relevant = CitationEvidence(
        source_type="reference_passage",
        source_id=uuid4(),
        text="Our experiment confirms the proposed method improves accuracy by 14 percent.",
        location={"block_type": "text"},
        access_status="full_text",
    )
    judge = FakeCitationJudge(
        [
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.NEI,
                    confidence=0.40,
                    rationale="Abstract lacks specific numbers.",
                )
            ],
            [
                AtomAssessment(
                    atom_id="atom-1",
                    verdict=CitationVerdict.SUPPORT,
                    confidence=0.92,
                    rationale="Full text confirms the 14% improvement.",
                    supporting_evidence_ids=[relevant.source_id],
                )
            ],
        ]
    )

    # Note distractor is placed before relevant in input list
    result = await make_service(judge).verify(make_input(), [abstract, distractor, relevant])

    assert result.verdict == CitationVerdict.SUPPORT
    assert result.verification_stage == VerificationStage.FULL_TEXT
    # Second judge call received ranked evidence where relevant was placed first
    second_call_evidence = judge.calls[1]
    assert second_call_evidence[0].source_id == relevant.source_id
    assert second_call_evidence[0].retrieval_score is not None
    assert second_call_evidence[0].retrieval_score > (second_call_evidence[1].retrieval_score or 0)
