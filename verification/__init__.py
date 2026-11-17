"""
Unified Verification Package Exports
====================================
"""
from __future__ import annotations

from verification.classification_engine import classify_opportunity
from verification.company_verifier import verify_company_authenticity
from verification.application_verifier import verify_application_deadline, parse_deadline_datetime
from verification.eligibility_engine import (
    evaluate_batch_eligibility,
    evaluate_experience_eligibility,
    extract_batches_from_text,
)
from verification.skills_extractor import extract_skills_dynamically
from verification.llm_adapter import LLMVerifierAdapter
from verification.final_approval import MultiGateVerificationEngine

__all__ = [
    "classify_opportunity",
    "verify_company_authenticity",
    "verify_application_deadline",
    "parse_deadline_datetime",
    "evaluate_batch_eligibility",
    "evaluate_experience_eligibility",
    "extract_batches_from_text",
    "extract_skills_dynamically",
    "LLMVerifierAdapter",
    "MultiGateVerificationEngine",
]
