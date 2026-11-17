"""
Deterministic Fresher & Batch Eligibility Engine
=================================================
Evaluates candidate graduation cohorts and experience limits against dynamic runtime clock (2026 reference year),
strictly rejecting experienced candidates (>1 yr commercial ceiling) and legacy graduation batches (<2024).
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple
from core.models import OpportunityType

TARGET_FRESHER_BATCHES = [2025, 2026, 2027]
PERMITTED_BATCHES = [2024, 2025, 2026, 2027, 2028]

SENIOR_ROLE_KEYWORDS = [
    r"\bsenior\b", r"\bsr\.\b", r"\blead\b", r"\bprincipal\b",
    r"\barchitect\b", r"\bmanager\b", r"\bdirector\b", r"\bhead\b", r"\bvp\b",
]

EXCLUDE_EXPERIENCE_PATTERNS = [
    r"\b([2-9]|\d{2,})\s*(?:\+|-\s*\d+)?\s*(?:years?|yrs?)\b",
    r"\bminimum\s+([2-9]|\d{2,})\s*(?:years?|yrs?)\b",
    r"\bat\s+least\s+([2-9]|\d{2,})\s*(?:years?|yrs?)\b",
    r"\b([2-9]|\d{2,})\+\s*(?:years?|yrs?)\s+of\s+experience\b",
]

FRESHER_POSITIVE_PATTERNS = [
    r"\b0\s*(?:(?:[-–—]|to)\s*[12])?\s*(?:years?|yrs?)\b",
    r"\bfreshers?\b",
    r"\bno\s+experience\s+(?:required|needed)\b",
    r"\bentry[\s-]?level\b",
    r"\bgraduate\s+trainee\b",
    r"\brecent\s+graduates?\b",
    r"\bcollege\s+(?:students?|graduates?)\b",
]


def extract_batches_from_text(text: str) -> List[int]:
    """Extracts all 4-digit graduation cohorts (e.g. 2024, 2025, 2026, 2027, 2028)."""
    matches = re.findall(r"\b(202[0-9])\b", text)
    batches = sorted(list(set(int(b) for b in matches)))
    return batches


def evaluate_batch_eligibility(batches: List[int]) -> Tuple[bool, List[str], List[str]]:
    """Evaluates whether graduation batches conform to fresher recruitment cohorts.
    
    Returns:
        (is_eligible, supporting_evidence, contradiction_reasons)
    """
    if not batches:
        return True, ["No specific batch restriction stated; open to all eligible graduates"], []

    target_set = set(TARGET_FRESHER_BATCHES)
    permitted_set = set(PERMITTED_BATCHES)
    found_set = set(batches)

    active_matches = found_set.intersection(target_set)
    if active_matches:
        return True, [f"Target fresher batch matched: {', '.join(str(b) for b in sorted(active_matches))}"], []

    permitted_matches = found_set.intersection(permitted_set)
    if permitted_matches:
        return True, [f"Permitted graduate batch matched: {', '.join(str(b) for b in sorted(permitted_matches))}"], []

    # If only older batches (<2024) are present with no modern batch, reject
    legacy_batches = [b for b in batches if b < 2024]
    if legacy_batches and not found_set.intersection(permitted_set):
        return False, [], [f"Ineligible legacy graduation batches: {', '.join(str(b) for b in legacy_batches)}"]

    return True, [], []


def evaluate_experience_eligibility(
    title: str,
    description: str,
    batches: Optional[List[int]] = None,
    opportunity_type: OpportunityType = OpportunityType.INDIVIDUAL_FRESHER_JOB,
) -> Tuple[bool, str, List[str], List[str]]:
    """Evaluates experience bounds and detects subtle fresher contradictions.
    
    Returns:
        (is_eligible, experience_summary, supporting_evidence, contradiction_reasons)
    """
    supporting = []
    contradictions = []

    # 1. Seniority title check
    for sen_pat in SENIOR_ROLE_KEYWORDS:
        if re.search(sen_pat, title, re.IGNORECASE):
            contradictions.append(f"Seniority conflict in title: '{title}' contains senior keyword")
            return False, "Senior Role", supporting, contradictions

    # 2. Check for explicit senior experience (> 1-2 years)
    desc_cleaned = re.sub(r"\b0\s*(?:[-–—]|to)\s*[12]\s*(?:years?|yrs?)\b", "", description, flags=re.IGNORECASE)
    desc_cleaned = re.sub(r"\b(?:internship|project|academic|college)\s+(?:experience|work)\b", "", desc_cleaned, flags=re.IGNORECASE)
    desc_cleaned = re.sub(r"\b(?:freshers?\s*(?:&|and)\s*experienced|0\s*years?)\b", "", desc_cleaned, flags=re.IGNORECASE)

    for exc_pat in EXCLUDE_EXPERIENCE_PATTERNS:
        for match in re.finditer(exc_pat, desc_cleaned, re.IGNORECASE):
            start_idx = match.start()
            prefix = desc_cleaned[max(0, start_idx - 10):start_idx].strip()
            if any(prefix.endswith(f"0{d}") or prefix.endswith(f"0 {d}") for d in ["-", "–", "—", "to"]):
                continue
            matched_str = match.group(0)
            contradictions.append(f"Mandatory professional experience exceeds fresher ceiling: '{matched_str}'")
            break

    # 3. Check for positive fresher evidence
    text = f"{title} {description}"
    has_fresher_mention = False
    for pos_pat in FRESHER_POSITIVE_PATTERNS:
        match = re.search(pos_pat, text, re.IGNORECASE)
        if match:
            has_fresher_mention = True
            supporting.append(f"Explicit fresher requirement stated: '{match.group(0)}'")
            break

    # 4. Contradiction Detection: Target Batch vs Experienced Requirement
    if contradictions:
        if batches and any(b >= 2025 for b in batches):
            contradictions.append("Contradictory requirement: Listing invites target graduation batches but demands commercial multi-year experience")
        return False, "Commercial Experience Required", supporting, contradictions

    # 5. Missing Experience Handling
    if not has_fresher_mention and not contradictions:
        if batches and any(b >= 2025 for b in batches):
            supporting.append(f"Genuine graduate cohort verified by target batch: {', '.join(str(b) for b in batches)}")
            return True, "0 Years (Batch Corroborated)", supporting, []
        if opportunity_type in [OpportunityType.OFF_CAMPUS_DRIVE, OpportunityType.GRADUATE_PROGRAM, OpportunityType.INTERNSHIP]:
            supporting.append("Entry-level nature corroborated by campus recruitment drive / trainee program")
            return True, "0-1 Years (Program Inferred)", supporting, []
        if any(k in title.lower() for k in ["trainee", "associate", "intern", "graduate"]):
            supporting.append("Entry-level title corroborated by trainee/graduate role")
            return True, "0-1 Years (Title Inferred)", supporting, []
        
        supporting.append("No contradictory experience stated")
        return True, "Unspecified (Passes Negative Gating)", supporting, []

    return True, "Fresher Eligible", supporting, []
