"""Unified Fresher Eligibility Verification Module.

Combines dynamic graduation batch validation, experience boundary checks,
and contradiction detection into a single cohesive eligibility assessment.
"""
from __future__ import annotations

from typing import List, Tuple, Optional
from models.opportunity import Opportunity, OpportunityType
from models.verification_result import FresherEligibilityAssessment
from verification.batch_eligibility import extract_batches, evaluate_batch_eligibility
from verification.experience_verifier import verify_experience


def verify_fresher_eligibility(
    opp: Opportunity,
) -> FresherEligibilityAssessment:
    """Evaluates multi-dimensional fresher eligibility for an opportunity.
    
    Verifies:
      1. Graduation batch eligibility (2024-2028 target cohorts).
      2. Experience limits (0-1.0 yr max).
      3. Contradiction between target batch and multi-year experience demands.
      4. Trainee cohort exemptions for university recruitment.
      5. Seniority conflicts in job titles.
    """
    text = f"{opp.title} {opp.description} {' '.join(opp.eligible_batches)}"
    
    # 1. Extract batches if not pre-populated
    detected_batches = opp.eligible_batches or extract_batches(text)
    batch_ok, batch_support, batch_contra = evaluate_batch_eligibility(detected_batches)
    
    # 2. Verify experience bounds and contradiction
    exp_ok, exp_summary, exp_support, exp_contra = verify_experience(
        title=opp.title,
        description=opp.description,
        batches=detected_batches,
    )
    
    all_support = batch_support + exp_support
    all_contra = batch_contra + exp_contra
    
    is_eligible = batch_ok and exp_ok
    
    # Assess overall confidence
    if is_eligible and detected_batches and exp_summary:
        confidence = 0.98
    elif is_eligible:
        confidence = 0.85
    else:
        confidence = 0.95
        
    return FresherEligibilityAssessment(
        is_fresher_eligible=is_eligible,
        detected_batches=detected_batches,
        has_batch_conflict=not batch_ok,
        has_experience_conflict=not exp_ok,
        experience_summary=exp_summary or "Not specified",
        supporting_evidence=all_support,
        contradictory_evidence=all_contra,
        confidence=confidence,
    )
