"""Opportunity Classifier for Coverage Lab.

Classifies opportunities into INDIVIDUAL_FRESHER_JOB vs OFF_CAMPUS_DRIVE.
Ensures generic off-campus recruitment programs (TCS NQT, Cognizant GenC,
Wipro Elite, Infosys Graduate Hiring) are not rejected by standard role allowlists.
"""
from __future__ import annotations

import re
from typing import Dict, Any
from models.opportunity import OpportunityType

OFF_CAMPUS_PATTERNS = [
    r"\boff[\s-]?campus\b",
    r"\brecruitment\s+drive\b",
    r"\bhiring\s+drive\b",
    r"\bwalk[\s-]?in\s+drive\b",
    r"\bwalk[\s-]?in\b",
    r"\bpool\s+campus\b",
    r"\bcampus\s+drive\b",
    r"\bnational\s+qualifier\s+test\b",  # TCS NQT
    r"\bqualifier\s+test\b",
    r"\bnqt\b",                          # TCS NQT
    r"\bgenc\b",                         # Cognizant GenC
    r"\belite\b",                        # Wipro Elite
    r"\bnational\s+talent\s+hunt\b",     # Wipro Elite NTH
    r"\bgraduate\s+trainee\s+program\b",
    r"\bgraduate\s+hiring\s+program\b",
    r"\bgraduate\s+hiring\b",
    r"\bentry[\s-]?level\s+drive\b",
    r"\bpooled\s+drive\b",
    r"\bmultiple\s+roles\b",
    r"\bpan[\s-]?india\s+hiring\b",
]

INDIVIDUAL_ROLE_PATTERNS = [
    r"\bdeveloper\b",
    r"\bengineer\b",
    r"\banalyst\b",
    r"\bscientist\b",
    r"\btester\b",
    r"\bconsultant\b",
    r"\bspecialist\b",
    r"\bassociate\b",
]


def classify_opportunity_type(title: str, description: str = "", raw_meta: Dict[str, Any] = None) -> OpportunityType:
    """Classifies an opportunity as either OFF_CAMPUS_DRIVE or INDIVIDUAL_FRESHER_JOB.
    
    A genuine off-campus drive must NOT be constrained to standard single-role filters.
    """
    text = f"{title} {description[:400]}".lower()

    # 1. Check strong off-campus drive patterns in title or text
    for pat in OFF_CAMPUS_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return OpportunityType.OFF_CAMPUS_DRIVE

    # 2. Check source metadata (e.g. if source category is dedicated drive portal)
    if raw_meta and raw_meta.get("driveType") or raw_meta and raw_meta.get("isDriveEnded") is not None:
        return OpportunityType.OFF_CAMPUS_DRIVE

    # 3. Default to individual fresher job if individual engineering role terms dominate
    return OpportunityType.INDIVIDUAL_FRESHER_JOB
