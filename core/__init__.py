"""Core package for Fresher Job Scraper Coverage Lab."""
from core.models import (
    Opportunity,
    OpportunityType,
    DeadlineStatus,
    ApplicationStatus,
    CompanyVerificationStatus,
    DeterministicStatus,
    LLMStatus,
    FinalApprovalStatus,
    EvidenceItem,
    SkillEvidence,
)

__all__ = [
    "Opportunity",
    "OpportunityType",
    "DeadlineStatus",
    "ApplicationStatus",
    "CompanyVerificationStatus",
    "DeterministicStatus",
    "LLMStatus",
    "FinalApprovalStatus",
    "EvidenceItem",
    "SkillEvidence",
]
