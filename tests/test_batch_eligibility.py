"""Unit Tests for Dynamic Graduation Batch Eligibility."""
from verification.batch_eligibility import extract_batches, evaluate_batch_eligibility


def test_extract_batches():
    text = "We are inviting candidates from 2025, 2026, and 2027 passing out batches."
    batches = extract_batches(text)
    assert batches == ["2025", "2026", "2027"]


def test_evaluate_target_batches():
    ok, sup, cont = evaluate_batch_eligibility(["2026"])
    assert ok is True
    assert len(sup) > 0
    assert len(cont) == 0


def test_evaluate_older_ineligible_batch():
    ok, sup, cont = evaluate_batch_eligibility(["2020", "2021"])
    assert ok is False
    assert len(cont) > 0


def test_missing_batch_passes_neutral():
    ok, sup, cont = evaluate_batch_eligibility([])
    assert ok is True
    assert len(cont) == 0
