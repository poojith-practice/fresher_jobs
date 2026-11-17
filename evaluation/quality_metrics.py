"""Quality Metrics & Accuracy Calculator for Coverage Lab."""
from __future__ import annotations

from typing import Any, Dict, List
from models.verification_result import VerificationDecision, VerificationRecord


def compute_metrics(
    verifications: List[VerificationRecord],
    ground_truth_labels: Dict[str, VerificationDecision] = None,
) -> Dict[str, Any]:
    """Computes distribution metrics and precision/recall if ground truth available."""
    total = len(verifications)
    if total == 0:
        return {"total": 0, "accepted": 0, "rejected": 0, "manual_review": 0}

    accepted = sum(1 for v in verifications if v.decision == VerificationDecision.ACCEPTED)
    rejected = sum(1 for v in verifications if v.decision == VerificationDecision.REJECTED)
    manual_review = sum(1 for v in verifications if v.decision == VerificationDecision.MANUAL_REVIEW)

    metrics: Dict[str, Any] = {
        "total_evaluated": total,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "manual_review_count": manual_review,
        "acceptance_rate": round((accepted / total) * 100, 2),
        "rejection_rate": round((rejected / total) * 100, 2),
        "manual_review_rate": round((manual_review / total) * 100, 2),
    }

    if ground_truth_labels:
        tp = fp = tn = fn = 0
        for v in verifications:
            gt = ground_truth_labels.get(v.opportunity_id)
            if not gt:
                continue

            pred_pos = (v.decision == VerificationDecision.ACCEPTED)
            true_pos = (gt == VerificationDecision.ACCEPTED)

            if pred_pos and true_pos:
                tp += 1
            elif pred_pos and not true_pos:
                fp += 1
            elif not pred_pos and not true_pos:
                tn += 1
            elif not pred_pos and true_pos:
                fn += 1

        precision = round(tp / (tp + fp), 3) if (tp + fp) > 0 else 1.0
        recall = round(tp / (tp + fn), 3) if (tp + fn) > 0 else 1.0
        f1 = round(2 * (precision * recall) / (precision + recall), 3) if (precision + recall) > 0 else 0.0

        metrics.update({
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
        })

    return metrics
