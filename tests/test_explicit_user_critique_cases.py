"""
Explicit User Critique & Master QA Regression Test Suite
=========================================================
Codifies every single failure case and architectural mandate from the user's critique:
1. Non-tech role exclusion (Pharma production, Adhesive technologist, Chef, KYC, Audio listener, Finance FP&A).
2. Expired drives (Synopsys 20 October 2026).
3. Category archives & navbar links (CampusDrive 2027 Batch Drives, FreshersDunia Interview Questions).
4. Closed requisition detection (IBM closedjob URL).
5. Upfront fee fraud vs legitimate negation ("never asks for fee").
6. Experience ceiling & contradiction enforcement (Senior roles, 3+ years).
7. Mandatory fail-closed approval gate truth table.
8. Dynamic skills zero-hallucination.
9. CSV output purity (verified_fresher_jobs.csv strictly contains APPROVED records only).
"""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path
import pytest

from core.models import (
    Opportunity,
    OpportunityType,
    DeadlineStatus,
    ApplicationStatus,
    CompanyVerificationStatus,
    DeterministicStatus,
    LLMStatus,
    FinalApprovalStatus,
)
from verification.classification_engine import classify_opportunity
from verification.application_verifier import verify_application_deadline
from verification.company_verifier import verify_company_authenticity
from verification.skills_extractor import extract_skills_dynamically
from verification.final_approval import MultiGateVerificationEngine
from storage.exports import export_to_csv
from models.verification_result import CompanyAuthenticity


# ==============================================================================
# 1. Non-Tech Role Triage Regressions
# ==============================================================================

def test_critique_ajanta_pharma_officer_production_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="Officer - Production (7536) at Ajanta Pharma",
        description="Tablet manufacturing, pharma packaging, GMP compliance",
        company="Ajanta Pharma",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_critique_asian_paints_adhesive_technologist_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="EXECUTIVE N - ADHESIVE TECHNOLOGIST at Asian Paints",
        description="Paint formulation, chemical polymers, adhesives",
        company="Asian Paints",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_critique_marriott_commis_chef_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="Commis I at Marriott International",
        description="Food preparation, kitchen hygiene, culinary standards",
        company="Marriott International",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_critique_slice_video_kyc_associate_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="KYC Associate",
        description="Slice hiring Video KYC associate for customer document verification",
        company="Slice",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_critique_amazon_audible_content_listener_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="Digital Content Associate - Audio Listening",
        description="Listen to audiobooks for quality and audio clarity",
        company="Amazon",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_critique_amazon_fpa_financial_analyst_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="Financial Analyst - FP&A",
        description="Corporate finance, P&L reporting, ledger reconciliation",
        company="Amazon",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_critique_goldman_sachs_client_ops_analyst_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="Operations Analyst - Equities Client Operations",
        description="Settlements, clearing, trade booking, client onboarding",
        company="Goldman Sachs",
    )
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


# ==============================================================================
# 2. Navigation, Category & Website Menu Exclusions
# ==============================================================================

def test_critique_category_link_2027_batch_drives_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="2027 Batch Drives",
        description="Browse all 2027 batch campus drives on CampusDrive",
    )
    assert opp_type == OpportunityType.UNRELATED


def test_critique_navbar_link_interview_questions_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="INTERVIEW QUESTIONS",
        description="Technical interview questions and answers for freshers",
    )
    assert opp_type == OpportunityType.UNRELATED


def test_critique_navbar_link_work_from_home_rejected():
    opp_type, role_family, reasons = classify_opportunity(
        title="WORK FROM HOME JOBS",
        description="List of work from home jobs across India",
    )
    assert opp_type == OpportunityType.UNRELATED


# ==============================================================================
# 3. Deadline Expiry & Closed Requisitions
# ==============================================================================

def test_critique_synopsys_expired_october_deadline_rejected():
    dl_status, app_status, parsed, rejections = verify_application_deadline(
        deadline_str="20 October 2026",
        text_content="Synopsys EDA Compiler Software Engineer Hiring 2026. Last Date to Register: 20 October 2026",
    )
    assert dl_status == DeadlineStatus.EXPIRED
    assert app_status == ApplicationStatus.CLOSED
    assert any("expired" in r.lower() for r in rejections)


def test_critique_ibm_closedjob_url_rejected():
    dl_status, app_status, parsed, rejections = verify_application_deadline(
        text_content="Application closed. Visit https://careers.ibm.com/en_US/closedjob to browse active listings.",
    )
    assert dl_status == DeadlineStatus.CLOSED
    assert app_status == ApplicationStatus.CLOSED


# ==============================================================================
# 4. Upfront Scam Detection vs Fee Negation Awareness
# ==============================================================================

def test_critique_upfront_training_fee_scam_flagged():
    status, supporting, contradictions = verify_company_authenticity(
        company="FakeCorp",
        apply_url="https://fakecorp.xyz/apply",
        text_content="Candidate must pay registration fee of Rs. 1500 before the interview",
    )
    assert status == CompanyAuthenticity.FRAUDULENT
    assert any("fee" in c.lower() for c in contradictions)


def test_critique_fee_negation_not_flagged_as_fraud():
    status, supporting, contradictions = verify_company_authenticity(
        company="Tata Consultancy Services",
        apply_url="https://nextstep.tcs.com",
        text_content="TCS never asks for any registration fee or security deposit at any stage of hiring.",
    )
    assert status != CompanyAuthenticity.FRAUDULENT
    assert not any("fee" in c.lower() for c in contradictions)


# ==============================================================================
# 5. Mandatory Fail-Closed Approval Gate Truth Table
# ==============================================================================

def test_critique_deterministic_pass_without_llm_is_manual_review_never_approved():
    engine = MultiGateVerificationEngine(require_llm=False)
    opp = Opportunity(
        opportunity_id="test_sde_1",
        title="Graduate Software Engineer",
        company="HPE",
        description="We are looking for Graduate Software Engineer batch 2026 0-1 years experience in Python",
        apply_url="https://careers.hpe.com/jobs/123",
        deadline="2026-12-31",
    )
    res = engine.verify_opportunity(opp)
    assert res.deterministic_status == DeterministicStatus.PASSED
    # MUST be MANUAL_REVIEW, NEVER APPROVED!
    assert res.final_status == FinalApprovalStatus.MANUAL_REVIEW
    assert any("LLM approval has not been executed" in r for r in res.manual_review_reasons)


def test_critique_unverified_employer_with_llm_approval_is_manual_review():
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "LLM Approved", [])

    opp = Opportunity(
        opportunity_id="test_sde_2",
        title="Junior Python Developer",
        company="Unknown Stealth Startup",
        description="Hiring freshers batch 2026 for Python web development",
        apply_url="https://unknown-random-blog.xyz/job/123",  # Unverified domain
        deadline="2026-12-31",
    )
    res = engine.verify_opportunity(opp)
    assert res.deterministic_status == DeterministicStatus.PASSED
    assert res.llm_status == LLMStatus.APPROVED
    # Even if LLM approves, unverified employer domain forces MANUAL_REVIEW!
    assert res.final_status == FinalApprovalStatus.MANUAL_REVIEW
    assert any("Employer cannot be independently verified" in r for r in res.manual_review_reasons)


def test_critique_expired_job_overrides_llm_approval_to_rejected():
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "LLM hallucinated pass", [])

    opp = Opportunity(
        opportunity_id="test_sde_3",
        title="Synopsys EDA Compiler Software Engineer",
        company="Synopsys",
        description="Hiring 2026 graduates. Last Date to Register: 20 October 2026",
        apply_url="https://synopsys.com/careers/123",
        deadline="2026-10-20",  # Expired
    )
    res = engine.verify_opportunity(opp)
    # Expired deadline must strictly REJECT the opportunity regardless of LLM
    assert res.deterministic_status == DeterministicStatus.REJECTED
    assert res.final_status == FinalApprovalStatus.REJECTED


def test_critique_genuine_sde_with_llm_and_verified_employer_is_approved():
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "Verified genuine SDE fresher opportunity", [])

    opp = Opportunity(
        opportunity_id="test_sde_4",
        title="Software Development Engineer I",
        company="Amazon",
        description="Requirements: Bachelor degree in Computer Science. 0-1 years software development experience. Knowledge of Python, Java.",
        apply_url="https://www.amazon.jobs/en/jobs/254321",
        deadline="2026-12-31",
    )
    res = engine.verify_opportunity(opp)
    assert res.deterministic_status == DeterministicStatus.PASSED
    assert res.llm_status == LLMStatus.APPROVED
    assert res.final_status == FinalApprovalStatus.APPROVED
    assert "Python" in res.skills
    assert "Java" in res.skills


# ==============================================================================
# 6. Dynamic Skills Zero-Hallucination
# ==============================================================================

def test_critique_generic_drive_extracts_no_hallucinated_skills():
    jd = "National Engineering Off-Campus Drive 2026. Open for all BE/BTech graduates across India. Apply online."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    assert skills == []
    assert status == "NO_ROLE_SPECIFIC_SKILLS_PUBLISHED"


# ==============================================================================
# 7. Tabular CSV Purity Guarantee
# ==============================================================================

def test_critique_csv_purity_verified_jobs_has_zero_rejected_records(tmp_path, monkeypatch):
    import storage.exports
    monkeypatch.setattr(storage.exports, "OUTPUT_DIR", tmp_path)

    opp_approved = Opportunity(
        opportunity_id="app_1",
        title="Software Engineer Fresher",
        company="Amazon",
        final_status=FinalApprovalStatus.APPROVED,
    )
    opp_rejected_pharma = Opportunity(
        opportunity_id="rej_1",
        title="Officer - Production (7536)",
        company="Ajanta Pharma",
        final_status=FinalApprovalStatus.REJECTED,
    )
    opp_rejected_chef = Opportunity(
        opportunity_id="rej_2",
        title="Commis I",
        company="Marriott International",
        final_status=FinalApprovalStatus.REJECTED,
    )
    opp_manual = Opportunity(
        opportunity_id="man_1",
        title="Junior Developer",
        company="Unverified Corp",
        final_status=FinalApprovalStatus.MANUAL_REVIEW,
    )

    all_opps = [opp_approved, opp_rejected_pharma, opp_rejected_chef, opp_manual]
    csv_file = storage.exports.export_to_csv(all_opps, "verified_fresher_jobs.csv")

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        headers = reader[0]
        data_rows = reader[1:]

    # Must contain ONLY 1 row (the approved one)
    assert len(data_rows) == 1
    assert data_rows[0][1] == "Software Engineer Fresher"
    assert data_rows[0][2] == "Amazon"
    assert data_rows[0][20] == "APPROVED"

    # Verify rejected file exists and contains exactly the 2 rejected rows
    rej_file = tmp_path / "rejected_fresher_jobs.csv"
    assert rej_file.exists()
    with open(rej_file, "r", encoding="utf-8") as f:
        rej_rows = list(csv.reader(f))[1:]
    assert len(rej_rows) == 2
    assert any("Ajanta Pharma" in r[2] for r in rej_rows)
    assert any("Marriott International" in r[2] for r in rej_rows)


def test_critique_employer_brand_mismatch_deloitte_with_infosys_url_is_rejected():
    """Verify that a blog listing claiming to be Deloitte but linking to Infosys career portal is rejected."""
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "LLM hallucinated pass", [])

    opp = Opportunity(
        opportunity_id="deloitte_fake_link",
        title="Associate Analyst For Freshers",
        company="Deloitte Off Campus 2026",
        description="Deloitte Off Campus 2026 is inviting applications for Associate Analyst. Batch 2026 eligible.",
        apply_url="https://career.infosys.com/jobdesc?jobReferenceCode=PROGEN-EXTERNAL-256139",
        deadline="2026-12-31",
    )
    res = engine.verify_opportunity(opp)
    assert res.deterministic_status == DeterministicStatus.REJECTED
    assert res.final_status == FinalApprovalStatus.REJECTED
    assert any("Employer mismatch" in r for r in res.rejection_reasons)

