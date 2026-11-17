"""Experience Requirement & Contradiction Verifier."""
from __future__ import annotations

import re
from typing import Tuple, List, Optional

EXCLUDE_EXPERIENCE_PATTERNS = [
    r"\b([2-9]|\d{2,})\s*(?:\+|-\s*\d+)?\s*(?:years?|yrs?)\b",           # 2+ years, 3-5 yrs
    r"\bminimum\s+([2-9]|\d{2,})\s*(?:years?|yrs?)\b",                  # minimum 2 years
    r"\bat\s+least\s+([2-9]|\d{2,})\s*(?:years?|yrs?)\b",                # at least 2 years
    r"\b([2-9]|\d{2,})\+\s*(?:years?|yrs?)\s+of\s+experience\b",        # 2+ years of experience
    r"\b1\+\s*(?:years?|yrs?)\s+of\s+(?:non[\s-]internship|professional|full[\s-]time|industry|relevant|software)\b", # 1+ years of non-internship/professional
    r"\b1\+\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b",                # 1+ years of experience
    r"\bminimum\s+1\+?\s*(?:years?|yrs?)\s+of\s+(?:non[\s-]internship|professional|full[\s-]time|industry|relevant)\b",
    r"\bat\s+least\s+1\+?\s*(?:years?|yrs?)\s+of\s+(?:non[\s-]internship|professional|full[\s-]time|industry|relevant)\b",
    r"\bnon[\s-]internship\s+(?:professional\s+)?(?:software\s+development\s+)?experience\b", # non-internship experience
]

FRESHER_POSITIVE_PATTERNS = [
    r"\b0\s*(?:-\s*[12])?\s*(?:years?|yrs?)\b",                          # 0-1 years, 0-2 years
    r"\b0\s*(?:years?|yrs?)\b",                                         # 0 years
    r"\bfreshers?\b",                                                   # fresher / freshers
    r"\bno\s+experience\s+(?:required|needed)\b",                       # no experience required
    r"\bentry[\s-]?level\b",                                            # entry level
    r"\bgraduate\s+trainee\b",                                          # graduate trainee
    r"\brecent\s+graduates?\b",                                         # recent graduates
    r"\bcollege\s+(?:students?|graduates?)\b",                          # college graduates
]

SENIOR_ROLE_KEYWORDS = [
    r"\bsenior\b", r"\bsr\.\b", r"\blead\b", r"\bprincipal\b",
    r"\barchitect\b", r"\bmanager\b", r"\bdirector\b", r"\bhead\b", r"\bvp\b",
]


def verify_experience(
    title: str,
    description: str,
    batches: List[str] = None,
) -> Tuple[bool, Optional[str], List[str], List[str]]:
    """Evaluates experience bounds and detects subtle fresher contradictions.
    
    Returns:
        (is_eligible, detected_exp_summary, supporting_evidence, contradiction_reasons)
    """
    text = f"{title} {description}"
    supporting = []
    contradictions = []

    # 1. Senior role check in title
    for sen_pat in SENIOR_ROLE_KEYWORDS:
        if re.search(sen_pat, title, re.IGNORECASE):
            contradictions.append(f"Seniority conflict in title: '{title}' contains senior keyword")
            return False, "Senior Role", supporting, contradictions

    # 2. Check for explicit senior experience requirements (> 1-2 years)
    # First protect against false positives like "0-2 years" or "intership experience"
    desc_cleaned = re.sub(r"\b0\s*-\s*[12]\s*(?:years?|yrs?)\b", "", description, flags=re.IGNORECASE)
    desc_cleaned = re.sub(r"\b(?:internship|project|academic|college)\s+(?:experience|work)\b", "", desc_cleaned, flags=re.IGNORECASE)

    for exc_pat in EXCLUDE_EXPERIENCE_PATTERNS:
        match = re.search(exc_pat, desc_cleaned, re.IGNORECASE)
        if match:
            matched_str = match.group(0)
            contradictions.append(f"Mandatory professional experience exceeds fresher ceiling: '{matched_str}'")

    # 3. Check for positive fresher evidence
    has_fresher_mention = False
    for pos_pat in FRESHER_POSITIVE_PATTERNS:
        match = re.search(pos_pat, text, re.IGNORECASE)
        if match:
            has_fresher_mention = True
            supporting.append(f"Explicit fresher requirement stated: '{match.group(0)}'")
            break

    # 4. Contradiction Detection: Target Batch vs Experienced
    # CASE 2: "2026 batch eligible, minimum 2 years of professional experience required." -> REJECT
    if contradictions:
        if batches and any(int(b) >= 2025 for b in batches if b.isdigit()):
            contradictions.append("Contradictory requirement: Listing invites target graduation batches but demands commercial multi-year experience")
        return False, "Commercial Experience Required", supporting, contradictions

    # 5. Missing Experience Information Handling
    if not has_fresher_mention and not contradictions:
        # Check if graduate hiring or batch is indicated
        if batches and any(int(b) >= 2025 for b in batches if b.isdigit()):
            supporting.append(f"Genuine graduate cohort verified by target batch: {', '.join(batches)}")
            return True, "0 Years (Batch Corroborated)", supporting, []
        # Trainee / Associate title
        if any(k in title.lower() for k in ["trainee", "associate", "intern", "graduate"]):
            supporting.append("Entry-level title corroborated by trainee/graduate role")
            return True, "0-1 Years (Title Inferred)", supporting, []
        
        # Neutral baseline for standard individual roles with missing explicit field
        supporting.append("No contradictory experience stated")
        return True, "Unspecified (Passes Negative Gating)", supporting, []

    return True, "Fresher Eligible", supporting, []
