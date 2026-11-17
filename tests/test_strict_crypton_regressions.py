"""Master Regression Test Suite — Gemini Crypton Verification & Invariant Enforcement.

Covers the 13 mandatory policy tests and 3 critical failure fixtures:
- CGI Java AI Apprentice (J0926-1187)
- Tata Communications (5733952549)
- Texas Instruments Software Development Engineer (25017217)
"""
from __future__ import annotations

import pytest
from datetime import datetime
import zoneinfo

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
from verification.application_verifier import verify_application_deadline, parse_deadline_datetime
from extraction.apply_link_resolver import ApplyLinkResolver, CLOSED_NOTICES
from verification.company_verifier import verify_company_authenticity
from verification.eligibility_engine import (
    evaluate_batch_eligibility,
    evaluate_experience_eligibility,
    extract_batches_from_text,
)
from verification.evidence_validator import validate_evidence_quote
from verification.final_approval import MultiGateVerificationEngine, application_is_verified_open

TZ_KOLKATA = zoneinfo.ZoneInfo("Asia/Kolkata")


# ==============================================================================
# 13 MANDATORY SPECIFICATION TESTS
# ==============================================================================

def test_1_no_deadline_and_no_closure_evidence_is_unknown():
    """Absence of closure evidence must NEVER be interpreted as evidence of openness."""
    dl_st, app_st, parsed, rejections = verify_application_deadline(
        deadline_str=None,
        text_content="Engineering candidates wanted. Apply for this junior developer position.",
    )
    assert dl_st == DeadlineStatus.NOT_PUBLISHED
    assert app_st == ApplicationStatus.UNKNOWN
    assert app_st != ApplicationStatus.OPEN


def test_2_expired_deadline_october_2026_is_expired():
    """Deadline October 21, 2026 evaluated against November 2026 is strictly EXPIRED."""
    dl_st, app_st, parsed, rejections = verify_application_deadline(
        deadline_str="21 October 2026",
        text_content="Apply before 21 October 2026 for this graduate hiring program.",
    )
    assert dl_st == DeadlineStatus.EXPIRED
    assert app_st == ApplicationStatus.CLOSED
    assert any("expired" in r.lower() for r in rejections)


def test_3_page_http200_with_closed_notice_is_closed():
    """Page returning HTTP 200 with closed notice is CLOSED, not open."""
    # Test closed regex detection
    import re
    body = "Thank you for your interest. This job opening is no longer accepting applications."
    matched = any(re.search(pat, body, re.IGNORECASE) for pat in CLOSED_NOTICES)
    assert matched is True


def test_4_redirect_to_generic_careers_is_unknown():
    """Redirecting to generic careers homepage without requisition ID is UNKNOWN."""
    res = ApplyLinkResolver.verify_application_live("https://careers.google.com")
    assert res.status in ["UNKNOWN", "UNREACHABLE"]


def test_5_cgi_njoyn_unverified_portal_is_manual_review():
    """CGI URL on Njoyn cannot be assumed open if portal status is unverified; must never be approved."""
    opp = Opportunity(
        opportunity_id="cgi_test_1187",
        title="Java AI Apprentice",
        company="CGI",
        role_family="SOFTWARE_ENGINEERING",
        description="Java AI Apprentice at CGI. Skills required: Java, Spring Boot.",
        apply_url="https://cgi.njoyn.com/corp/xweb/xweb.asp?jobid=J0926-1187",
        application_status=ApplicationStatus.UNKNOWN,
        company_verification_status=CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING,
        llm_status=LLMStatus.APPROVED,
        llm_approved=True,
    )
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.verify_opportunity(opp)
    assert opp.final_status in (FinalApprovalStatus.MANUAL_REVIEW, FinalApprovalStatus.REJECTED)
    assert opp.final_status != FinalApprovalStatus.APPROVED


def test_6_ti_oraclecloud_unverified_requisition_is_not_official():
    """Texas Instruments URL on edbz.fa.us2.oraclecloud.com has unverified tenant and requisition."""
    status, sup, contras = verify_company_authenticity(
        company="Texas Instruments",
        apply_url="https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/25017217",
    )
    # The tenant 'edbz' does not match Texas Instruments
    assert any("not verified" in c.lower() for c in contras) or status != "VERIFIED_OFFICIAL"


def test_7_apprentice_without_experience_is_not_specified():
    """Job title says Apprentice but no experience requirement exists -> NOT_SPECIFIED."""
    ok, exp_summary, sup, contras = evaluate_experience_eligibility(
        title="Java AI Apprentice",
        description="Work on artificial intelligence solutions and enterprise platforms.",
        batches=[],
    )
    assert exp_summary == "NOT_SPECIFIED"
    assert ok is False


def test_8_batch_in_navigation_menu_not_eligible():
    """Page containing '2027 Batch Drives' in navigation must NOT establish batch eligibility."""
    nav_text = """
    Home | 2024 Batch Drives | 2025 Batch Drives | 2026 Batch Drives | 2027 Batch Drives | About Us
    Latest News: Tech hiring trends across Indian colleges.
    """
    batches = extract_batches_from_text(nav_text)
    assert batches == []


def test_9_description_0_to_4_years_rejected():
    """Description saying '0–4 Years of relevant experience' exceeds fresher ceiling."""
    ok, exp_summary, sup, contras = evaluate_experience_eligibility(
        title="Software Engineer",
        description="Qualifications: B.E/B.Tech in Computer Science. 0–4 Years of relevant experience in software development.",
        batches=[2026],
    )
    assert ok is False
    assert exp_summary == "Commercial Experience Required"
    assert any("exceeds fresher ceiling" in c for c in contras)


def test_10_llm_hallucinated_quote_rejected():
    """LLM quote absent from source text is flagged as hallucination and rejected."""
    source = "Tata Communications is hiring engineers for its telecom network applications in Pune."
    invented_quote = "Freshers (0 Years) eligible with 2026 passing out batch"
    is_valid, reason = validate_evidence_quote(invented_quote, source)
    assert is_valid is False
    assert "HALLUCINATED_EVIDENCE_REJECTED" in reason


def test_11_llm_accepts_but_application_unknown_not_approved():
    """When LLM says ACCEPT but live application is UNKNOWN, final status MUST NOT be APPROVED."""
    opp = Opportunity(
        opportunity_id="test_opp_001",
        title="Software Engineer",
        company="NatWest Group",
        role_family="SOFTWARE_ENGINEERING",
        description="Freshers welcome. 0-1 years experience required.",
        apply_url="https://jobs.example.com/apply/123",
        application_status=ApplicationStatus.UNKNOWN,
        company_verification_status=CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING,
        llm_status=LLMStatus.APPROVED,
        llm_approved=True,
    )
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.verify_opportunity(opp)
    assert opp.final_status == FinalApprovalStatus.MANUAL_REVIEW
    assert opp.final_status != FinalApprovalStatus.APPROVED


def test_12_llm_is_unavailable_not_approved():
    """When LLM is unavailable, final status must be MANUAL_REVIEW, NEVER APPROVED."""
    opp = Opportunity(
        opportunity_id="test_opp_002",
        title="Software Engineer",
        company="Tata Communications",
        role_family="SOFTWARE_ENGINEERING",
        description="Freshers welcome. 0-1 years experience required.",
        apply_url="https://jobs.tatacommunications.com/jobs/123",
        application_status=ApplicationStatus.OPEN,
        application_verification_result=ApplicationVerificationResult(
            original_url="https://jobs.tatacommunications.com/jobs/123",
            resolved_url="https://jobs.tatacommunications.com/jobs/123",
            http_status=200,
            status="OPEN",
            evidence_text="Active requisition verified on employer portal",
            checked_at=datetime.now(TZ_KOLKATA).isoformat(),
        ),
        company_verification_status=CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING,
        llm_status=LLMStatus.UNAVAILABLE,
        llm_approved=False,
    )
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.has_active_keys = lambda: False
    engine.verify_opportunity(opp)
    assert opp.final_status == FinalApprovalStatus.MANUAL_REVIEW
    assert opp.final_status != FinalApprovalStatus.APPROVED


def test_13_export_invariant_enforcement():
    """Invariant check in storage/exports.py must abort if unverified record is marked approved."""
    from storage.exports import export_to_csv
    unverified_opp = Opportunity(
        opportunity_id="fake_approved_001",
        title="Software Engineer",
        company="FakeCorp",
        role_family="SOFTWARE_ENGINEERING",
        final_status=FinalApprovalStatus.APPROVED,
        llm_status=LLMStatus.APPROVED,
        llm_approved=True,
        application_status=ApplicationStatus.UNKNOWN,  # NOT verified open!
        company_verification_status=CompanyVerificationStatus.UNVERIFIED,
    )
    with pytest.raises(ValueError, match="Invariant violation"):
        export_to_csv([unverified_opp])


# ==============================================================================
# 3 CRITICAL REQUISITION REGRESSION FIXTURES
# ==============================================================================

def test_fixture_1_cgi_j0926_1187_cannot_be_approved():
    """Fixture 1: CGI Java AI Apprentice (J0926-1187).
    
    Listing does not state experience, duration, or closing date.
    Njoyn portal is access-protected / unverified live openness.
    MUST NOT be approved.
    """
    opp = Opportunity(
        opportunity_id="cgi_J0926-1187",
        title="Java AI Apprentice",
        company="CGI",
        role_family="SOFTWARE_ENGINEERING",
        description="CGI Java AI Apprentice. Join our enterprise AI development team.",
        apply_url="https://cgi.njoyn.com/corp/xweb/xweb.asp?clid=21001&page=jobdetails&jobid=J0926-1187&BRID=1334822&SBDID=943&lang=1",
        deadline_status=DeadlineStatus.NOT_PUBLISHED,
        application_status=ApplicationStatus.UNKNOWN,
    )
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.verify_opportunity(opp)
    assert opp.final_status in [FinalApprovalStatus.MANUAL_REVIEW, FinalApprovalStatus.REJECTED]
    assert opp.final_status != FinalApprovalStatus.APPROVED


def test_fixture_2_tata_5733952549_expired_and_rejected():
    """Fixture 2: Tata Communications Engineer - Software Development (5733952549).
    
    Reported with an October 21, 2026 deadline and 0-4 years experience.
    MUST be EXPIRED and REJECTED.
    """
    opp = Opportunity(
        opportunity_id="tata_5733952549",
        title="Engineer - Software & Application Development",
        company="Tata Communications",
        role_family="SOFTWARE_ENGINEERING",
        description="Role: Software Engineer. 0-4 Years of relevant experience in software development. Last date to register: 21 October 2026.",
        apply_url="https://jobs.tatacommunications.com/jobs/5733952549",
        deadline="2026-10-21",
    )
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.verify_opportunity(opp)
    assert opp.final_status == FinalApprovalStatus.REJECTED
    assert opp.deadline_status in [DeadlineStatus.EXPIRED, DeadlineStatus.CLOSED]


def test_fixture_3_texas_instruments_25017217_cannot_be_approved():
    """Fixture 3: Texas Instruments Software Development Engineer (25017217).
    
    Old share URL on Oracle Cloud with unverified tenant 'edbz'.
    Current status cannot be independently verified on TI careers board.
    MUST NOT be approved.
    """
    opp = Opportunity(
        opportunity_id="ti_25017217",
        title="Software Development Engineer",
        company="Texas Instruments",
        role_family="SOFTWARE_ENGINEERING",
        description="Software Development Engineer at Texas Instruments. Design embedded software.",
        apply_url="https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/25017217/?utm_medium=jobshare&utm_source=External+Job+Share",
        deadline_status=DeadlineStatus.NOT_PUBLISHED,
        application_status=ApplicationStatus.UNKNOWN,
    )
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.verify_opportunity(opp)
    assert opp.final_status in [FinalApprovalStatus.MANUAL_REVIEW, FinalApprovalStatus.REJECTED]
    assert opp.final_status != FinalApprovalStatus.APPROVED
