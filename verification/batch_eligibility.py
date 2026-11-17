"""Graduation Batch Eligibility Evaluator."""
from __future__ import annotations

import re
from typing import List, Tuple
from config.settings import PERMITTED_BATCHES, CURRENT_TARGET_BATCHES


def extract_batches(text: str) -> List[str]:
    """Extracts all 4-digit graduation years matching 202X."""
    matches = re.findall(r"\b(202[3-9])\b", text)
    return sorted(list(set(matches)))


def evaluate_batch_eligibility(batches: List[str]) -> Tuple[bool, List[str], List[str]]:
    """Evaluates whether detected batches conform to target fresher hiring cohorts.
    
    Returns:
        (is_eligible, supporting_evidence, contradiction_reasons)
    """
    if not batches:
        # Absence of explicit batch does not automatically disqualify an individual fresher role
        return True, ["No batch restriction stated"], []

    target_set = set(CURRENT_TARGET_BATCHES)
    permitted_set = set(PERMITTED_BATCHES)
    found_set = set(batches)

    # Any intersection with current target batches (2025, 2026, 2027) is strong positive evidence
    active_matches = found_set.intersection(target_set)
    if active_matches:
        return True, [f"Target fresher batch matched: {', '.join(sorted(active_matches))}"], []

    # Permitted historical/upcoming batches (e.g. 2024 recent graduates or 2028 pre-final)
    permitted_matches = found_set.intersection(permitted_set)
    if permitted_matches:
        return True, [f"Permitted graduate batch matched: {', '.join(sorted(permitted_matches))}"], []

    # Only strictly older batches (e.g. 2020, 2021, 2022) with no modern batch is disqualified
    older_batches = [b for b in batches if int(b) < 2024]
    if older_batches and not found_set.intersection(permitted_set):
        return False, [], [f"Ineligible legacy graduation batches: {', '.join(older_batches)}"]

    return True, [], []
