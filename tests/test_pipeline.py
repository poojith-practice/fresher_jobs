"""Unit Tests for Multi-Pillar Verification Pipeline against Benchmark Cases."""
from evaluation.dataset_builder import get_benchmark_dataset
from verification.verification_pipeline import VerificationPipeline


def test_verification_pipeline_evaluates_all_benchmark_cases():
    pipeline = VerificationPipeline(use_llm=False)
    cases = get_benchmark_dataset()

    for opp, expected_decision, description in cases:
        record = pipeline.verify(opp)
        assert record.decision == expected_decision, (
            f"Failed on {opp.id} ({opp.title}): expected {expected_decision}, got {record.decision}. "
            f"Reasons: {record.rejection_reasons}"
        )
