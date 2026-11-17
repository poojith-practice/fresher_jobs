"""
Core Data Models & Normalised Opportunity Schema
================================================
Comprehensive, provenance-preserving data models for fresher opportunities,
recruitment drives, extraction evidence, and multi-pillar verification statuses.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OpportunityType(str, Enum):
    INDIVIDUAL_FRESHER_JOB = "INDIVIDUAL_FRESHER_JOB"
    OFF_CAMPUS_DRIVE = "OFF_CAMPUS_DRIVE"
    GRADUATE_PROGRAM = "GRADUATE_PROGRAM"
    INTERNSHIP = "INTERNSHIP"
    WALK_IN_DRIVE = "WALK_IN_DRIVE"
    EXPERIENCED_JOB = "EXPERIENCED_JOB"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"


class DeadlineStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class ApplicationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CAPTCHA_GATED = "CAPTCHA_GATED"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


class CompanyVerificationStatus(str, Enum):
    VERIFIED_EMPLOYER_POSTING = "VERIFIED_EMPLOYER_POSTING"
    VERIFIED_EMPLOYER_DRIVE = "VERIFIED_EMPLOYER_DRIVE"
    AGGREGATOR_ONLY = "AGGREGATOR_ONLY"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class DeterministicStatus(str, Enum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    PENDING = "PENDING"


class LLMStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNAVAILABLE = "UNAVAILABLE"
    PENDING = "PENDING"


class FinalApprovalStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    PENDING = "PENDING"


class EvidenceItem(BaseModel):
    """Raw provenance record for every extracted property."""
    field: str
    value: Any
    source_url: str
    evidence_text: str = ""
    extraction_method: str = "direct_extraction"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    retrieved_at: Optional[str] = None
    is_explicit: bool = True


class SkillEvidence(BaseModel):
    """Evidence-backed technical, domain, or soft skill."""
    name: str
    category: str = "tools_and_technologies"  # required_skills, preferred_skills, tools_and_technologies, domain_skills, soft_skills, inferred_skills
    evidence: str = ""
    evidence_url: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_explicit: bool = True
    is_required: bool = True


class Opportunity(BaseModel):
    """Normalised employment opportunity data model with strict provenance."""
    opportunity_id: str
    title: str
    company: str
    opportunity_type: OpportunityType = OpportunityType.INDIVIDUAL_FRESHER_JOB
    role_family: str = "TECHNOLOGY"
    role: str = ""
    description: Optional[str] = None

    # Source and Routing Links
    source_name: str = ""
    source_listing_url: str = ""
    source_detail_url: str = ""
    employer_career_url: Optional[str] = None
    employer_job_url: Optional[str] = None
    apply_url: Optional[str] = None
    all_source_urls: List[str] = Field(default_factory=list)

    # Location & Mode
    location: List[str] = Field(default_factory=list)
    work_mode: Optional[str] = None
    employment_type: Optional[str] = None

    # Dates & Deadlines
    date_posted: Optional[str] = None
    date_posted_basis: Optional[str] = None
    deadline: Optional[str] = None
    deadline_status: DeadlineStatus = DeadlineStatus.UNKNOWN
    application_status: ApplicationStatus = ApplicationStatus.UNKNOWN
    application_status_evidence: Optional[str] = None

    # Eligibility Metrics
    eligible_graduation_batches: List[int] = Field(default_factory=list)
    eligible_degrees: List[str] = Field(default_factory=list)
    eligible_branches: List[str] = Field(default_factory=list)
    minimum_percentage: Optional[float] = None
    backlog_rules: Optional[str] = None
    experience_min_years: Optional[float] = None
    experience_max_years: Optional[float] = None
    experience_status: str = "UNKNOWN"

    # Skills
    skills: List[str] = Field(default_factory=list)
    required_skills: List[SkillEvidence] = Field(default_factory=list)
    preferred_skills: List[SkillEvidence] = Field(default_factory=list)
    inferred_skills: List[SkillEvidence] = Field(default_factory=list)
    skill_evidence: List[SkillEvidence] = Field(default_factory=list)
    skills_extraction_status: str = "PENDING"

    # Company Verification
    company_verification_status: CompanyVerificationStatus = CompanyVerificationStatus.UNVERIFIED
    employer_verification_url: Optional[str] = None

    # Pipeline Gates
    deterministic_status: DeterministicStatus = DeterministicStatus.PENDING
    llm_status: LLMStatus = LLMStatus.PENDING
    llm_approved: bool = False
    llm_reasoning: Optional[str] = None

    final_status: FinalApprovalStatus = FinalApprovalStatus.PENDING
    rejection_reasons: List[str] = Field(default_factory=list)
    manual_review_reasons: List[str] = Field(default_factory=list)

    # Provenance
    raw_evidence: List[EvidenceItem] = Field(default_factory=list)
    retrieved_at: Optional[str] = None
    last_verified_at: Optional[str] = None
