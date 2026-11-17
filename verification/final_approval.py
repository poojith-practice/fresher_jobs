"""
Multi-Gate Final Approval Engine & Consistency Checker
======================================================
Synthesizes deterministic gates (Role Classification, Company Verification, Deadline Expiry,
Fresher Eligibility, Dynamic Skills Extraction) with fail-closed LLM approval.
Enforces multi-gate consistency checking to guarantee 100% adherence to fresher hiring criteria.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional

from core.models import (
    Opportunity,
    OpportunityType,
    DeadlineStatus,
    ApplicationStatus,
    CompanyVerificationStatus,
    DeterministicStatus,
    LLMStatus,
    FinalApprovalStatus,
    ApplicationVerificationResult,
)
from verification.classification_engine import classify_opportunity
from verification.company_verifier import verify_company_authenticity
from verification.application_verifier import verify_application_deadline
from extraction.apply_link_resolver import ApplyLinkResolver
from verification.eligibility_engine import (
    evaluate_batch_eligibility,
    evaluate_experience_eligibility,
    extract_batches_from_text,
)
from verification.skills_extractor import extract_skills_dynamically
from verification.llm_adapter import LLMVerifierAdapter
from models.verification_result import CompanyAuthenticity

logger = logging.getLogger("verification.final_approval")


def application_is_verified_open(opp: Opportunity) -> bool:
    """Verifies that an opportunity has independently established current live openness."""
    if opp.application_status != ApplicationStatus.OPEN:
        return False
    res = opp.application_verification_result
    if not res:
        return False
    if res.status != "OPEN":
        return False
    if res.http_status != 200:
        return False
    if not res.checked_at:
        return False
    if not res.evidence_text:
        return False
    if res.closed_notice_found:
        return False
    return True


class MultiGateVerificationEngine:
    """Rigorous multi-pillar verification engine."""

    def __init__(self, require_llm: bool = True):
        self.require_llm = require_llm
        self.llm_adapter = LLMVerifierAdapter()

    def verify_opportunity(self, opp: Opportunity) -> Opportunity:
        """Runs full multi-pillar verification on an opportunity and updates its status in-place."""
        rejection_reasons: List[str] = []
        manual_review_reasons: List[str] = []

        # -------------------------------------------------------------
        # Gate 1: Role Classification & Non-Tech Triage
        # -------------------------------------------------------------
        opp_type, role_family, class_reasons = classify_opportunity(
            title=opp.title,
            description=opp.description or "",
            company=opp.company or "",
        )
        opp.opportunity_type = opp_type
        opp.role_family = role_family

        if opp_type == OpportunityType.UNRELATED:
            rejection_reasons.append(f"Non-tech / non-software role: {'; '.join(class_reasons)}")
        elif opp_type == OpportunityType.EXPERIENCED_JOB:
            rejection_reasons.append(f"Experienced / senior role: {'; '.join(class_reasons)}")

        # -------------------------------------------------------------
        # Gate 2: Company Authenticity & Scam Screening
        # -------------------------------------------------------------
        comp_status, comp_pos, comp_contras = verify_company_authenticity(
            company=opp.company,
            apply_url=opp.apply_url or opp.source_detail_url or "",
            text_content=opp.description or "",
        )
        if comp_status == CompanyAuthenticity.VERIFIED_OFFICIAL:
            opp.company_verification_status = CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING
        elif comp_status == CompanyAuthenticity.REPUTABLE_AGGREGATOR:
            opp.company_verification_status = CompanyVerificationStatus.AGGREGATOR_ONLY
        elif comp_status in (CompanyAuthenticity.FRAUDULENT, CompanyAuthenticity.SUSPICIOUS):
            opp.company_verification_status = CompanyVerificationStatus.CONFLICTING_EVIDENCE
        else:
            opp.company_verification_status = CompanyVerificationStatus.UNVERIFIED

        if comp_status in (CompanyAuthenticity.FRAUDULENT, CompanyAuthenticity.SUSPICIOUS) or any("scam" in c.lower() or "fee" in c.lower() or "mismatch" in c.lower() for c in comp_contras):
            rejection_reasons.append(f"Recruitment integrity contradiction: {'; '.join(comp_contras)}")

        # -------------------------------------------------------------
        # Gate 3: Application Deadlines & Live Requisition Verification
        # -------------------------------------------------------------
        deadline_st, app_st, parsed_dl, dl_rejections = verify_application_deadline(
            deadline_str=opp.deadline,
            text_content=f"{opp.title} {opp.description or ''}",
            explicit_status=opp.deadline_status.value if opp.deadline_status else None,
        )
        opp.deadline_status = deadline_st
        opp.application_status = app_st
        if parsed_dl:
            opp.deadline = parsed_dl

        if dl_rejections:
            rejection_reasons.extend(dl_rejections)

        # Inspect live application destination
        target_apply_url = opp.apply_url or (opp.source_detail_url if opp.company_verification_status == CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING else None)
        if opp.application_verification_result:
            live_res = opp.application_verification_result
            if live_res.status == "OPEN":
                opp.application_status = ApplicationStatus.OPEN
                opp.application_status_evidence = live_res.evidence_text
            elif live_res.status == "CLOSED":
                opp.application_status = ApplicationStatus.CLOSED
                opp.deadline_status = DeadlineStatus.CLOSED
                rejection_reasons.append(live_res.evidence_text or "Application closed on live employer portal")
        elif target_apply_url:
            req_m = re.search(r"/(?:jobs?|requisitions?|job|postings?)/([a-zA-Z0-9_-]{4,})", target_apply_url, re.I)
            expected_req_id = req_m.group(1) if req_m else (opp.opportunity_id if opp.opportunity_id and not opp.opportunity_id.startswith(("cd_", "j4f_")) else None)
            
            live_res = ApplyLinkResolver.verify_application_live(
                target_apply_url,
                expected_requisition_id=expected_req_id,
                expected_company=opp.company,
            )
            opp.application_verification_result = live_res
            
            if live_res.status == "OPEN":
                opp.application_status = ApplicationStatus.OPEN
                opp.application_status_evidence = live_res.evidence_text
            elif live_res.status == "CLOSED":
                opp.application_status = ApplicationStatus.CLOSED
                opp.deadline_status = DeadlineStatus.CLOSED
                rejection_reasons.append(live_res.evidence_text or "Application closed on live employer portal")
            elif live_res.status == "EXPIRED":
                opp.application_status = ApplicationStatus.CLOSED
                opp.deadline_status = DeadlineStatus.EXPIRED
                rejection_reasons.append(live_res.evidence_text or "Application deadline expired on live employer portal")
            elif live_res.status == "LOGIN_REQUIRED":
                opp.application_status = ApplicationStatus.LOGIN_REQUIRED
                manual_review_reasons.append("Login wall encountered on employer portal")
            elif live_res.status == "UNREACHABLE":
                opp.application_status = ApplicationStatus.UNREACHABLE
                manual_review_reasons.append(f"Employer portal unreachable: {live_res.error}")
            elif live_res.status == "UNAVAILABLE":
                opp.application_status = ApplicationStatus.UNKNOWN
                manual_review_reasons.append(live_res.evidence_text or "Requisition ID not found on employer page")
            else:
                opp.application_status = ApplicationStatus.UNKNOWN
                manual_review_reasons.append(live_res.evidence_text or "Live application status cannot be verified as currently open")
        else:
            opp.application_status = ApplicationStatus.UNKNOWN
            manual_review_reasons.append("No verified direct employer application URL found")

        # -------------------------------------------------------------
        # Gate 4: Graduation Batch & Experience Eligibility
        # -------------------------------------------------------------
        if not opp.eligible_graduation_batches:
            batches_found = extract_batches_from_text(f"{opp.title} {opp.description or ''}")
            opp.eligible_graduation_batches = batches_found

        batch_ok, batch_sup, batch_contras = evaluate_batch_eligibility(opp.eligible_graduation_batches)
        if not batch_ok:
            rejection_reasons.extend(batch_contras)

        exp_ok, exp_summary, exp_sup, exp_contras = evaluate_experience_eligibility(
            title=opp.title,
            description=opp.description or "",
            batches=opp.eligible_graduation_batches,
            opportunity_type=opp.opportunity_type,
        )
        opp.experience_status = exp_summary
        if not exp_ok:
            if exp_summary == "NOT_SPECIFIED":
                manual_review_reasons.append("Experience requirement not specified in source posting")
            else:
                rejection_reasons.extend(exp_contras)

        # -------------------------------------------------------------
        # Gate 5: Dynamic Skills Extraction (No Hallucination)
        # -------------------------------------------------------------
        all_skills, req_ev, pref_ev, all_ev, skill_status = extract_skills_dynamically(
            description=opp.description or "",
            title=opp.title,
            source_url=opp.source_detail_url or opp.apply_url or "",
        )
        opp.skills = all_skills
        opp.required_skills = req_ev
        opp.preferred_skills = pref_ev
        opp.skill_evidence = all_ev
        opp.skills_extraction_status = skill_status

        # -------------------------------------------------------------
        # Gate 6: Deterministic Gate Decision
        # -------------------------------------------------------------
        if rejection_reasons:
            opp.deterministic_status = DeterministicStatus.REJECTED
        else:
            opp.deterministic_status = DeterministicStatus.PASSED

        # -------------------------------------------------------------
        # Gate 7: LLM Approval Gate (Fail-Closed)
        # -------------------------------------------------------------
        if self.require_llm:
            if opp.deterministic_status == DeterministicStatus.PASSED:
                llm_st, llm_ok, llm_reason, llm_rejections = self.llm_adapter.verify_opportunity(opp)
                opp.llm_status = llm_st
                opp.llm_approved = llm_ok
                opp.llm_reasoning = llm_reason

                if llm_st in (LLMStatus.MANUAL_REVIEW, LLMStatus.UNAVAILABLE, LLMStatus.PENDING):
                    manual_review_reasons.append(llm_reason or f"LLM status: {llm_st.value}")
                elif not llm_ok:
                    rejection_reasons.extend(llm_rejections or ["Rejected by LLM verifier"])
            else:
                opp.llm_status = LLMStatus.PENDING
                opp.llm_approved = False
                opp.llm_reasoning = "Skipped LLM invocation due to deterministic rejection"

        # -------------------------------------------------------------
        # Gate 8: Final Approval Synthesis (Strict Truth Table)
        # -------------------------------------------------------------
        opp.rejection_reasons = sorted(list(set(rejection_reasons)))
        opp.manual_review_reasons = sorted(list(set(manual_review_reasons)))
        opp.last_verified_at = datetime.utcnow().isoformat()

        if opp.deterministic_status != DeterministicStatus.PASSED or opp.rejection_reasons:
            opp.final_status = FinalApprovalStatus.REJECTED
        elif not self.require_llm:
            opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
            if "LLM approval has not been executed" not in opp.manual_review_reasons:
                opp.manual_review_reasons.append("Deterministic checks passed, but LLM approval has not been executed")
        elif opp.llm_status == LLMStatus.APPROVED and opp.llm_approved:
            # Strict multi-pillar assertions: every requirement must be independently satisfied
            if not application_is_verified_open(opp):
                opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
                if "Application is not independently verified as currently open" not in opp.manual_review_reasons:
                    opp.manual_review_reasons.append("Application is not independently verified as currently open")
            if opp.company_verification_status != CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING:
                opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
                if "Employer cannot be independently verified" not in opp.manual_review_reasons:
                    opp.manual_review_reasons.append("Employer cannot be independently verified")
            if opp.experience_status in ["Senior Role", "Commercial Experience Required"]:
                opp.final_status = FinalApprovalStatus.REJECTED
            elif opp.experience_status == "NOT_SPECIFIED":
                opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
                if "Experience requirement not specified" not in opp.manual_review_reasons:
                    opp.manual_review_reasons.append("Experience requirement not specified")
            if opp.manual_review_reasons:
                opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
            elif not opp.rejection_reasons:
                opp.final_status = FinalApprovalStatus.APPROVED
        elif opp.llm_status == LLMStatus.MANUAL_REVIEW:
            opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
        elif opp.llm_status in (LLMStatus.UNAVAILABLE, LLMStatus.PENDING):
            opp.final_status = FinalApprovalStatus.MANUAL_REVIEW
            opp.manual_review_reasons.append("LLM verifier unavailable or pending")
        else:
            opp.final_status = FinalApprovalStatus.REJECTED

        return opp

    def verify_batch(self, opportunities: List[Opportunity]) -> List[Opportunity]:
        """Verifies a list of opportunities in batch."""
        return [self.verify_opportunity(opp) for opp in opportunities]
