"""Integrated Multi-Pillar Verification Pipeline.

Evaluates Company Authenticity, Opportunity Authenticity,
Fresher Eligibility, and Application Validity.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from models.opportunity import Opportunity, OpportunityType
from models.verification_result import (
    CompanyAuthenticity,
    FresherEligibilityAssessment,
    VerificationDecision,
    VerificationRecord,
)
from verification.batch_eligibility import evaluate_batch_eligibility
from verification.experience_verifier import verify_experience
from verification.application_status import verify_application_status
from verification.company_verifier import verify_company_authenticity
from verification.llm_guardrail import LLMGuardrail

logger = logging.getLogger("coverage_lab.pipeline")


class VerificationPipeline:
    def __init__(self, use_llm: bool = False):
        self.use_llm = use_llm
        self.llm_guardrail = LLMGuardrail() if use_llm else None

    def verify(self, opp: Opportunity) -> VerificationRecord:
        """Executes full multi-pillar verification on an opportunity."""
        record = VerificationRecord(
            opportunity_id=opp.id,
            verified_at=datetime.utcnow().isoformat(),
        )

        rejection_reasons = []
        manual_review_reasons = []

        # -------------------------------------------------------------
        # Pillar 1: Company Authenticity & Fraud Screening
        # -------------------------------------------------------------
        comp_auth, comp_pos, comp_flags = verify_company_authenticity(
            company=opp.company,
            apply_url=opp.apply_url,
            text_content=opp.description,
        )
        record.company_authenticity = comp_auth
        if comp_auth == CompanyAuthenticity.FRAUDULENT:
            rejection_reasons.extend(comp_flags)
            record.decision = VerificationDecision.REJECTED
            record.rejection_reasons = rejection_reasons
            return record

        # -------------------------------------------------------------
        # Pillar 2: Application Validity & Deadlines
        # -------------------------------------------------------------
        app_status, deadline_str, status_reason = verify_application_status(
            deadline_str=opp.deadline,
            text_content=f"{opp.title} {opp.description}",
            explicit_status=opp.deadline_status,
        )
        record.application_validity = app_status
        opp.deadline_status = app_status

        if app_status == "EXPIRED":
            rejection_reasons.append(f"Expired opportunity: {status_reason}")
            record.decision = VerificationDecision.REJECTED
            record.rejection_reasons = rejection_reasons
            return record
        elif app_status == "CLOSED":
            rejection_reasons.append(f"Application closed: {status_reason}")
            record.decision = VerificationDecision.REJECTED
            record.rejection_reasons = rejection_reasons
            return record

        # -------------------------------------------------------------
        # Pillar 3: Fresher & Batch Eligibility
        # -------------------------------------------------------------
        # A. Batch evaluation
        batch_ok, batch_sup, batch_cont = evaluate_batch_eligibility(opp.eligible_batches)
        if not batch_ok:
            rejection_reasons.extend(batch_cont)

        # B. Experience & Contradiction evaluation
        exp_ok, exp_summary, exp_sup, exp_cont = verify_experience(
            title=opp.title,
            description=opp.description,
            batches=opp.eligible_batches,
        )
        if not exp_ok:
            rejection_reasons.extend(exp_cont)

        supporting_all = comp_pos + batch_sup + exp_sup
        contradictions_all = batch_cont + exp_cont

        record.fresher_eligibility = FresherEligibilityAssessment(
            is_fresher_eligible=(batch_ok and exp_ok),
            confidence=0.9 if (batch_ok and exp_ok) else 0.1,
            detected_batches=opp.eligible_batches,
            has_batch_conflict=bool(batch_cont),
            has_experience_conflict=bool(exp_cont),
            experience_summary=exp_summary or "Verified",
            supporting_evidence=supporting_all,
            contradictory_evidence=contradictions_all,
        )

        # -------------------------------------------------------------
        # Pillar 4: Opportunity Authenticity & Type-Aware Evaluation
        # -------------------------------------------------------------
        if opp.opportunity_type == OpportunityType.OFF_CAMPUS_DRIVE:
            # Genuine off-campus drive: does NOT require matching specific single-role keyword
            record.opportunity_authenticity = "VALID_COLLECTIVE_DRIVE"
        else:
            record.opportunity_authenticity = "INDIVIDUAL_FRESHER_ROLE"

        # -------------------------------------------------------------
        # Optional: Secondary LLM Verification (if configured and eligible)
        # -------------------------------------------------------------
        if self.use_llm and self.llm_guardrail and self.llm_guardrail.has_keys() and not rejection_reasons:
            llm_res = self.llm_guardrail.verify_opportunity(opp)
            if llm_res:
                record.auditor = "llm_guardrail"
                if not llm_res.is_fresher_eligible or llm_res.decision == "REJECT":
                    rejection_reasons.extend(llm_res.rejection_reasons or ["Rejected by LLM guardrail"])
                elif llm_res.decision == "MANUAL_REVIEW":
                    manual_review_reasons.append("Flagged for manual review by LLM guardrail")

        # -------------------------------------------------------------
        # Final Decision Synthesis
        # -------------------------------------------------------------
        if rejection_reasons:
            record.decision = VerificationDecision.REJECTED
            record.rejection_reasons = rejection_reasons
        elif manual_review_reasons or (comp_auth == CompanyAuthenticity.UNCORROBORATED and app_status == "UNKNOWN"):
            record.decision = VerificationDecision.MANUAL_REVIEW
            record.manual_review_reasons = manual_review_reasons or ["Uncorroborated third-party blog with unverified application status"]
        else:
            record.decision = VerificationDecision.ACCEPTED

        return record
