"""Core Data Models for Coverage Lab Opportunities.

Defines schemas for individual fresher jobs and off-campus recruitment drives,
ensuring explicit separation between the two opportunity types.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OpportunityType(str, Enum):
    """Categorizes the fundamental recruitment structure of an opportunity."""
    INDIVIDUAL_FRESHER_JOB = "INDIVIDUAL_FRESHER_JOB"
    OFF_CAMPUS_DRIVE = "OFF_CAMPUS_DRIVE"


class SkillItem(BaseModel):
    """Skill representation with classification (explicit vs inferred)."""
    name: str
    category: str = "general"
    kind: str = "EXPLICIT"  # 'EXPLICIT' or 'INFERRED'
    reasoning: Optional[str] = None
    confidence: float = 1.0


class Opportunity(BaseModel):
    """Unified normalized model representing a fresher job or recruitment drive."""
    id: str = Field(..., description="Unique deterministic identifier (hash or UUID)")
    opportunity_type: OpportunityType = Field(
        default=OpportunityType.INDIVIDUAL_FRESHER_JOB,
        description="Discriminator between individual role and collective drive",
    )
    title: str = Field(..., description="Raw title as posted on source")
    normalized_title: str = Field(..., description="Cleaned and standardized role/drive title")
    company: str = Field(..., description="Target hiring organization")
    location: str = Field(default="Pan India", description="Work location or drive location")
    category: str = Field(default="Full Stack Developer", description="Role/Track category for Google Sheets")
    description: str = Field(default="", description="Full or excerpted opportunity description")
    
    # Eligibility & Experience
    eligible_batches: List[str] = Field(default_factory=list, description="Graduation batch years e.g. ['2025', '2026', '2027']")
    excluded_batches: List[str] = Field(default_factory=list, description="Explicitly barred batch years")
    experience_required: Optional[str] = Field(default=None, description="Raw experience specification")
    min_experience_years: float = Field(default=0.0, description="Minimum numeric experience bound")
    max_experience_years: float = Field(default=1.0, description="Maximum numeric experience bound")
    degree_requirements: List[str] = Field(default_factory=list, description="Academic qualifications (B.E, B.Tech, MCA, etc.)")
    
    # Compensation
    salary_raw: Optional[str] = Field(default=None, description="Raw salary representation")
    min_salary: Optional[float] = Field(default=None, description="Lower compensation bound")
    max_salary: Optional[float] = Field(default=None, description="Upper compensation bound")
    
    # Discovery & Application Lineage
    source_id: str = Field(..., description="Origin source identifier (e.g. 'saarthi_drives', 'elitmus')")
    listing_url: str = Field(..., description="URL where opportunity was discovered")
    apply_url: str = Field(..., description="Application URL extracted from listing")
    official_apply_url: Optional[str] = Field(default=None, description="Resolved official employer link")
    requisition_id: Optional[str] = Field(default=None, description="Corporate requisition tracking code")
    provenance: List[str] = Field(default_factory=list, description="All sources corroborating this opportunity")
    
    # Temporal & Validity
    date_posted: Optional[str] = Field(default=None, description="ISO posting date or timestamp")
    deadline: Optional[str] = Field(default=None, description="Application closing timestamp or date")
    deadline_status: str = Field(default="UNKNOWN", description="OPEN, CLOSED, EXPIRED, UNKNOWN")
    discovered_at: str = Field(..., description="Timestamp when system collected the record")
    
    # Technical Skills Breakdown
    explicit_skills: List[str] = Field(default_factory=list, description="Directly mentioned technologies/tools")
    inferred_skills: List[str] = Field(default_factory=list, description="Logically derived competencies")
    
    # Source Meta
    raw_metadata: Dict[str, Any] = Field(default_factory=dict, description="Preserved source-specific payload")
