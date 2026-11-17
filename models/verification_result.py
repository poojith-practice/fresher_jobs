"""Verification Result and Audit Models for Coverage Lab.

Maintains multi-dimensional verification audits: Company Authenticity,
Opportunity Authenticity, Fresher Eligibility, and Application Validity.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VerificationDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    VERIFICATION_INCOMPLETE = "VERIFICATION_INCOMPLETE"


class CompanyAuthenticity(str, Enum):
    VERIFIED_OFFICIAL = "VERIFIED_OFFICIAL"          # Direct official corporate domain
    REPUTABLE_AGGREGATOR = "REPUTABLE_AGGREGATOR"    # Trusted tier-1 partner (eLitmus, Saarthi)
    UNCORROBORATED = "UNCORROBORATED"                # Third-party blog with unverified claim
    SUSPICIOUS = "SUSPICIOUS"                        # Domain mismatches or suspicious metadata
    FRAUDULENT = "FRAUDULENT"                        # Upfront registration fee / fake company


class FresherEligibilityAssessment(BaseModel):
    """Detailed evaluation of entry-level and batch eligibility."""
    is_fresher_eligible: bool = Field(..., description="True if genuinely entry-level / freshers allowed")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    detected_batches: List[str] = Field(default_factory=list)
    has_batch_conflict: bool = Field(default=False)
    has_experience_conflict: bool = Field(default=False)
    experience_summary: str = Field(default="")
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)


class VerificationRecord(BaseModel):
    """Four-pillar audit record for every evaluated opportunity."""
    opportunity_id: str
    decision: VerificationDecision = VerificationDecision.VERIFICATION_INCOMPLETE
    
    # 4 Pillars of Verification
    company_authenticity: CompanyAuthenticity = CompanyAuthenticity.UNCORROBORATED
    opportunity_authenticity: str = "PENDING"
    fresher_eligibility: Optional[FresherEligibilityAssessment] = None
    application_validity: str = "UNKNOWN"  # 'OPEN', 'CLOSED', 'EXPIRED', 'UNKNOWN', 'BROKEN_LINK'
    
    # Audit trail
    rejection_reasons: List[str] = Field(default_factory=list)
    manual_review_reasons: List[str] = Field(default_factory=list)
    verified_at: Optional[str] = None
    auditor: str = "deterministic_rule_engine"  # or 'llm_guardrail'
    notes: Optional[str] = None
