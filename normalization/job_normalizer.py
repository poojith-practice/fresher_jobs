"""Job and Opportunity Normalizer for Coverage Lab."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, Dict
from models.opportunity import Opportunity, OpportunityType
from normalization.opportunity_classifier import classify_opportunity_type
from normalization.skills_generator import generate_skills


def normalize_title(title: str) -> str:
    """Cleans punctuation, emoji, and formatting noise from job titles."""
    t = re.sub(r"[\U00010000-\U0010ffff]", "", title)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_opportunity(raw: Dict[str, Any]) -> Opportunity:
    """Transforms a raw scraped dictionary into a strongly-typed Opportunity."""
    raw_title = str(raw.get("title") or "Untitled Listing").strip()
    company = str(raw.get("company") or "Unknown Company").strip()
    apply_url = str(raw.get("apply_url") or raw.get("listing_url") or "").strip()
    listing_url = str(raw.get("listing_url") or apply_url).strip()
    description = str(raw.get("description") or "").strip()
    source_id = str(raw.get("source_id") or "unknown_source")
    raw_metadata = raw.get("raw_metadata") or {}

    # Classify Opportunity Type
    opp_type = classify_opportunity_type(raw_title, description, raw_metadata)

    # Derive Skills
    explicit_skills, inferred_skills = generate_skills(raw_title, description, opp_type)

    # Category derivation for Google Sheets track
    t_low = raw_title.lower()
    if "data" in t_low and "analyst" in t_low:
        category = "Data Analyst"
    elif "business" in t_low and "analyst" in t_low:
        category = "Business Analyst"
    elif "financial" in t_low or "finance" in t_low:
        category = "Financial Analyst"
    elif "analyst" in t_low:
        category = "Analyst"
    elif any(k in t_low for k in ["web", "frontend", "front-end", "ui"]):
        category = "Web Developer"
    elif any(k in t_low for k in ["qa", "test", "quality"]):
        category = "QA Engineer"
    elif opp_type == OpportunityType.OFF_CAMPUS_DRIVE:
        category = "Off-Campus Recruitment Drive"
    else:
        category = "Full Stack Developer"

    # Eligible Batches
    batches = list(raw.get("batches") or [])
    if not batches:
        found_batches = re.findall(r"\b202\d\b", f"{raw_title} {description}")
        batches = list(dict.fromkeys(found_batches))

    # Location normalization
    location = str(raw.get("location") or "Pan India").strip()
    if not location or location.lower() in {"none", "null"}:
        location = "Pan India"

    # Experience string guarantee for Sheets
    exp_str = raw.get("experience_required")
    if not exp_str or exp_str.lower() in {"none", "null", "not specified"}:
        exp_str = "Fresher (0-1 Years)"

    # Salary guarantee for Sheets
    sal_raw = raw.get("salary_raw") or "Best in Industry"

    # Deterministic ID (hash of source, company, normalized title, apply_url)
    norm_title = normalize_title(raw_title)
    hash_seed = f"{company.lower()}:{norm_title.lower()}:{apply_url}"
    opp_id = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()[:16]

    return Opportunity(
        id=opp_id,
        opportunity_type=opp_type,
        title=raw_title,
        normalized_title=norm_title,
        company=company,
        location=location,
        category=category,
        description=description,
        eligible_batches=batches,
        experience_required=exp_str,
        salary_raw=sal_raw,
        min_salary=raw.get("min_salary"),
        max_salary=raw.get("max_salary"),
        source_id=source_id,
        listing_url=listing_url,
        apply_url=apply_url,
        requisition_id=raw.get("raw_id"),
        provenance=[source_id],
        date_posted=raw.get("date_posted") or datetime.utcnow().strftime("%Y-%m-%d"),
        deadline=raw.get("deadline"),
        deadline_status=str(raw.get("deadline_status") or "UNKNOWN"),
        discovered_at=datetime.utcnow().isoformat(),
        explicit_skills=explicit_skills,
        inferred_skills=inferred_skills,
        raw_metadata=raw_metadata,
    )
