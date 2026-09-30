from dataclasses import dataclass
from typing import Any

from app.schemas.p2_schema import CitationVerdict, CitationVerificationResult


@dataclass
class ClassMetric:
    precision: float
    recall: float
    f1: float
    support_count: int


@dataclass
class CitationEvaluationReport:
    total_pairs: int
    pair_accuracy: float
    macro_f1: float
    class_metrics: dict[str, ClassMetric]
    confusion_matrix: dict[str, dict[str, int]]
    escalation_stats: dict[str, Any]


class CitationEvaluationService:
    """Evaluates citation verification results against ground truth.

    Computes Macro-F1 and Citation Pair Accuracy as defined in revised-proposal-v2.pdf:
    - Macro-F1 across SUPPORT, REFUTE, and NEI classes.
    - Citation Pair Accuracy over all claim-evidence pairs.
    - Escalation statistics (abstract exits vs full-text escalations).
    """

    LABELS = [
        CitationVerdict.SUPPORT.value,
        CitationVerdict.REFUTE.value,
        CitationVerdict.NEI.value,
    ]

    @classmethod
    def evaluate(
        cls,
        predictions: list[CitationVerificationResult],
        ground_truths: list[CitationVerdict],
    ) -> CitationEvaluationReport:
        if len(predictions) != len(ground_truths):
            raise ValueError("Number of predictions must match number of ground truths")

        total = len(predictions)
        if total == 0:
            return CitationEvaluationReport(
                total_pairs=0,
                pair_accuracy=0.0,
                macro_f1=0.0,
                class_metrics={
                    label: ClassMetric(0.0, 0.0, 0.0, 0) for label in cls.LABELS
                },
                confusion_matrix={
                    gold: {pred: 0 for pred in cls.LABELS} for gold in cls.LABELS
                },
                escalation_stats={},
            )

        confusion: dict[str, dict[str, int]] = {
            gold: {pred: 0 for pred in cls.LABELS} for gold in cls.LABELS
        }
        correct = 0

        for pred_result, gold in zip(predictions, ground_truths, strict=True):
            pred_val = (
                pred_result.verdict.value
                if pred_result.verdict is not None
                else CitationVerdict.NEI.value
            )
            gold_val = gold.value
            if pred_val in cls.LABELS and gold_val in cls.LABELS:
                confusion[gold_val][pred_val] += 1
            if pred_val == gold_val:
                correct += 1

        class_metrics: dict[str, ClassMetric] = {}
        f1_scores: list[float] = []

        for label in cls.LABELS:
            tp = confusion[label][label]
            fp = sum(confusion[g][label] for g in cls.LABELS if g != label)
            fn = sum(confusion[label][p] for p in cls.LABELS if p != label)
            support_count = tp + fn

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (
                (2 * precision * recall) / (precision + recall)
                if (precision + recall) > 0
                else 0.0
            )

            class_metrics[label] = ClassMetric(
                precision=round(precision, 4),
                recall=round(recall, 4),
                f1=round(f1, 4),
                support_count=support_count,
            )
            f1_scores.append(f1)

        macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0
        pair_accuracy = correct / total if total > 0 else 0.0

        escalated_full_text = sum(
            1 for p in predictions if "FULL_TEXT" in [s.value for s in p.stage_history]
        )
        abstract_only = sum(
            1 for p in predictions if [s.value for s in p.stage_history] == ["ABSTRACT"]
        )

        escalation_stats = {
            "total_evaluated": total,
            "abstract_only_exits": abstract_only,
            "full_text_escalations": escalated_full_text,
            "escalation_rate": (
                round(escalated_full_text / total, 4) if total > 0 else 0.0
            ),
            "requires_review_count": sum(1 for p in predictions if p.requires_review),
        }

        return CitationEvaluationReport(
            total_pairs=total,
            pair_accuracy=round(pair_accuracy, 4),
            macro_f1=round(macro_f1, 4),
            class_metrics=class_metrics,
            confusion_matrix=confusion,
            escalation_stats=escalation_stats,
        )
