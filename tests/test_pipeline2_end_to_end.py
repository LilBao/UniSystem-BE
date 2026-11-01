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
from app.services.layer2.pipeline2.citation_evaluation_service import CitationEvaluationService
from app.services.layer2.pipeline2.citation_verification_service import CitationVerificationService


class MockCitationJudge:
    """Mock LLM judge providing deterministic responses for sample citation dataset."""

    def __init__(self) -> None:
        self.call_history: list[tuple[str, str]] = []

    async def decompose(self, data: CitationVerificationInput) -> list[AtomicClaim]:
        if "and reduces latency" in data.text_content:
            return [
                AtomicClaim(
                    atom_id="atom-1",
                    text_content="Method improves classification accuracy.",
                ),
                AtomicClaim(atom_id="atom-2", text_content="Method reduces latency by 50%."),
            ]
        return [AtomicClaim(atom_id="atom-1", text_content=data.text_content)]

    async def judge(
        self,
        data: CitationVerificationInput,
        atomic_claims: list[AtomicClaim],
        evidence: list[CitationEvidence],
    ) -> list[AtomAssessment]:
        stage = evidence[0].access_status if evidence else "none"
        self.call_history.append((data.text_content, stage or "none"))

        assessments: list[AtomAssessment] = []
        for atom in atomic_claims:
            # Case 1: Abstract supported claim
            if "ResNet architecture" in atom.text_content:
                assessments.append(
                    AtomAssessment(
                        atom_id=atom.atom_id,
                        verdict=CitationVerdict.SUPPORT,
                        confidence=0.95,
                        rationale="Abstract explicitly states the ResNet architecture depth.",
                        supporting_evidence_ids=[evidence[0].source_id],
                    )
                )
            # Case 2: Full-text needed (abstract NEI)
            elif "hyperparameter tuning" in atom.text_content:
                if stage == "abstract":
                    assessments.append(
                        AtomAssessment(
                            atom_id=atom.atom_id,
                            verdict=CitationVerdict.NEI,
                            confidence=0.40,
                            rationale="Abstract only mentions general optimization.",
                        )
                    )
                else:
                    assessments.append(
                        AtomAssessment(
                            atom_id=atom.atom_id,
                            verdict=CitationVerdict.SUPPORT,
                            confidence=0.92,
                            rationale="Section 4.2 confirms learning rate of 0.001 was used.",
                            supporting_evidence_ids=[evidence[0].source_id],
                        )
                    )
            # Case 3: Low confidence abstract -> escalates to high confidence full text
            elif "quantum supremacy" in atom.text_content:
                if stage == "abstract":
                    assessments.append(
                        AtomAssessment(
                            atom_id=atom.atom_id,
                            verdict=CitationVerdict.SUPPORT,
                            confidence=0.68,  # Below 0.80 threshold
                            rationale="Abstract hints at quantum advantage.",
                        )
                    )
                else:
                    assessments.append(
                        AtomAssessment(
                            atom_id=atom.atom_id,
                            verdict=CitationVerdict.SUPPORT,
                            confidence=0.96,
                            rationale="Section 5 confirms 200-second benchmark result.",
                            supporting_evidence_ids=[evidence[0].source_id],
                        )
                    )
            # Case 4: Multi-atom with 1 refuted atom
            elif "reduces latency" in atom.text_content:
                assessments.append(
                    AtomAssessment(
                        atom_id=atom.atom_id,
                        verdict=CitationVerdict.REFUTE,
                        confidence=0.91,
                        rationale="Table 4 shows latency increased by 12% rather than decreased.",
                        contradicting_evidence_ids=[evidence[0].source_id],
                    )
                )
            elif "improves classification accuracy" in atom.text_content:
                assessments.append(
                    AtomAssessment(
                        atom_id=atom.atom_id,
                        verdict=CitationVerdict.SUPPORT,
                        confidence=0.94,
                        rationale="Table 4 shows accuracy improved from 82% to 89%.",
                        supporting_evidence_ids=[evidence[0].source_id],
                    )
                )
            # Case 5: NEI even in full text
            else:
                assessments.append(
                    AtomAssessment(
                        atom_id=atom.atom_id,
                        verdict=CitationVerdict.NEI,
                        confidence=0.30,
                        rationale="No mention of this assertion in abstract or full text.",
                    )
                )

        return assessments


@pytest.mark.asyncio
async def test_pipeline2_sample_citation_suite_end_to_end() -> None:
    """Deliverable Tuần 12: Verify Pipeline 2 on sample citations."""
    settings = Settings(
        citation_judge_confidence_threshold=0.80,
        citation_judge_max_input_chars=24000,
        citation_judge_max_evidence_items=12,
        citation_judge_max_atomic_claims=8,
    )
    judge = MockCitationJudge()
    service = CitationVerificationService(judge, settings)  # type: ignore[arg-type]

    # Prepare 5 sample test cases:
    cases = [
        # Case 1: Supported by abstract (exits early)
        (
            CitationVerificationInput(
                claim_id=uuid4(),
                text_content="ResNet architecture utilizes 152 layers.",
                citation_marker="[1]",
                submission_reference_id=uuid4(),
            ),
            [
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="We introduce deep residual nets up to 152 layers.",
                    access_status="abstract",
                ),
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="Full text detailed layer specifications.",
                    access_status="full_text",
                ),
            ],
            CitationVerdict.SUPPORT,
            VerificationStage.ABSTRACT,
        ),
        # Case 2: NEI on abstract -> escalates to full text -> SUPPORT
        (
            CitationVerificationInput(
                claim_id=uuid4(),
                text_content="The model used hyperparameter tuning with learning rate 0.001.",
                citation_marker="[2]",
                submission_reference_id=uuid4(),
            ),
            [
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="Abstract summarizes overall architecture without hyperparameters.",
                    access_status="abstract",
                ),
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text=(
                        "In Section 4.2 hyperparameter tuning experiments set "
                        "initial learning rate to 0.001."
                    ),
                    access_status="full_text",
                ),
            ],
            CitationVerdict.SUPPORT,
            VerificationStage.FULL_TEXT,
        ),
        # Case 3: Low confidence SUPPORT on abstract (<0.80) -> escalates to full text
        (
            CitationVerificationInput(
                claim_id=uuid4(),
                text_content="Demonstrated quantum supremacy over classical supercomputers.",
                citation_marker="[3]",
                submission_reference_id=uuid4(),
            ),
            [
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="Our processor shows promise towards quantum supremacy.",
                    access_status="abstract",
                ),
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text=(
                        "Our Sycamore quantum processor takes approximately 200 seconds "
                        "to sample quantum supremacy."
                    ),
                    access_status="full_text",
                ),
            ],
            CitationVerdict.SUPPORT,
            VerificationStage.FULL_TEXT,
        ),
        # Case 4: Multi-atom claim with 1 refuted atom -> overall REFUTE
        (
            CitationVerificationInput(
                claim_id=uuid4(),
                text_content=(
                    "The algorithm improves classification accuracy and reduces latency by 50%."
                ),
                citation_marker="[4]",
                submission_reference_id=uuid4(),
            ),
            [
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="Table 4 experimental comparison of accuracy and latency benchmarks.",
                    access_status="abstract",
                ),
            ],
            CitationVerdict.REFUTE,
            VerificationStage.ABSTRACT,
        ),
        # Case 5: Unmentioned claim -> NEI after full escalation
        (
            CitationVerificationInput(
                claim_id=uuid4(),
                text_content="Method was deployed to autonomous rover on Mars in 2021.",
                citation_marker="[5]",
                submission_reference_id=uuid4(),
            ),
            [
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="Abstract discussing earth-based robotics.",
                    access_status="abstract",
                ),
                CitationEvidence(
                    source_type="reference_passage",
                    source_id=uuid4(),
                    text="Full text discussing industrial factory floor navigation.",
                    access_status="full_text",
                ),
            ],
            CitationVerdict.NEI,
            VerificationStage.FULL_TEXT,
        ),
    ]

    results = []
    gold_verdicts = []

    for inp, evidence, expected_verdict, expected_stage in cases:
        res = await service.verify(inp, evidence)
        results.append(res)
        gold_verdicts.append(expected_verdict)

        assert res.verdict == expected_verdict
        assert res.verification_stage == expected_stage
        if expected_verdict == CitationVerdict.NEI:
            assert res.requires_review is True
        else:
            assert res.status == CitationResultStatus.SUCCEEDED

    # Evaluate using the proposal's evaluation metric framework
    report = CitationEvaluationService.evaluate(results, gold_verdicts)

    assert report.total_pairs == 5
    assert report.pair_accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert report.escalation_stats["abstract_only_exits"] == 2
    assert report.escalation_stats["full_text_escalations"] == 3
    assert report.escalation_stats["escalation_rate"] == 0.6
