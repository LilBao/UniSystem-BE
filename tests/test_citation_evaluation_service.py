from uuid import uuid4

from app.schemas.p2_schema import (
    CitationResultStatus,
    CitationVerdict,
    CitationVerificationResult,
    VerificationStage,
)
from app.services.layer2.pipeline2.citation_evaluation_service import CitationEvaluationService


def make_pred(
    verdict: CitationVerdict,
    stages: list[VerificationStage] | None = None,
    requires_review: bool = False,
) -> CitationVerificationResult:
    stage_list = stages or [VerificationStage.ABSTRACT]
    return CitationVerificationResult(
        claim_id=uuid4(),
        verdict=verdict,
        confidence=0.9,
        status=(
            CitationResultStatus.SUCCEEDED
            if not requires_review
            else CitationResultStatus.REQUIRES_REVIEW
        ),
        verification_stage=stage_list[-1],
        requires_review=requires_review,
        stage_history=stage_list,
    )


def test_perfect_evaluation_metrics() -> None:
    preds = [
        make_pred(CitationVerdict.SUPPORT),
        make_pred(CitationVerdict.REFUTE),
        make_pred(CitationVerdict.NEI),
    ]
    golds = [
        CitationVerdict.SUPPORT,
        CitationVerdict.REFUTE,
        CitationVerdict.NEI,
    ]

    report = CitationEvaluationService.evaluate(preds, golds)

    assert report.total_pairs == 3
    assert report.pair_accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert report.class_metrics["SUPPORT"].f1 == 1.0
    assert report.class_metrics["REFUTE"].f1 == 1.0
    assert report.class_metrics["NEI"].f1 == 1.0
    assert report.confusion_matrix["SUPPORT"]["SUPPORT"] == 1
    assert report.confusion_matrix["REFUTE"]["REFUTE"] == 1
    assert report.confusion_matrix["NEI"]["NEI"] == 1


def test_imperfect_evaluation_metrics_and_escalation_stats() -> None:
    preds = [
        make_pred(CitationVerdict.SUPPORT, [VerificationStage.ABSTRACT]),
        make_pred(
            CitationVerdict.SUPPORT,
            [VerificationStage.ABSTRACT, VerificationStage.FULL_TEXT],
        ),
        make_pred(
            CitationVerdict.REFUTE,
            [VerificationStage.ABSTRACT, VerificationStage.FULL_TEXT],
        ),
        make_pred(CitationVerdict.NEI, [VerificationStage.ABSTRACT], requires_review=True),
    ]
    golds = [
        CitationVerdict.SUPPORT,  # correct
        CitationVerdict.REFUTE,   # incorrect (predicted SUPPORT, gold REFUTE)
        CitationVerdict.REFUTE,   # correct
        CitationVerdict.NEI,      # correct
    ]

    report = CitationEvaluationService.evaluate(preds, golds)

    # 3 correct out of 4 -> accuracy = 0.75
    assert report.total_pairs == 4
    assert report.pair_accuracy == 0.75
    assert report.escalation_stats["abstract_only_exits"] == 2
    assert report.escalation_stats["full_text_escalations"] == 2
    assert report.escalation_stats["escalation_rate"] == 0.5
    assert report.escalation_stats["requires_review_count"] == 1
