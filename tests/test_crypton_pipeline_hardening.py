"""Hardening and Pipeline Integration Regression Test Suite.

Verifies:
1. classify_page_type rejects category hubs, nav, prep, and accepts real job/drive details.
2. campusdrive extraction never falls back to article URLs and never fabricates 0-1 years.
3. LLM evidence validator rejects fabricated experience_quote and batch_quote.
4. Application verifier enforces exact employer, query parameter req IDs, and rejects generic forms.
5. Invariant assertions fail closed across all pipeline outputs.
"""
from __future__ import annotations

import pytest
from datetime import datetime
from bs4 import BeautifulSoup

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
from extraction.page_type_classifier import classify_page_type, PageType
from extraction.apply_link_resolver import ApplyLinkResolver
from scrapers.campusdrive import extract_campusdrive_detail
from verification.final_approval import MultiGateVerificationEngine, assert_approval_invariants
from verification.llm_adapter import LLMVerifierAdapter, LLMDecisionSchema


# ==============================================================================
# 1. PAGE TYPE CLASSIFIER & EXTRACTION INTEGRATION TESTS
# ==============================================================================

def test_page_type_classifier_rejects_category_pages():
    """CampusDrive 2027 and 2026 Batch Drives must be classified as CATEGORY_PAGE."""
    html_category = """
    <html>
      <head><title>2027 Batch Drives - Latest Off Campus Drives</title></head>
      <body>
        <h1>2027 Batch Drives</h1>
        <div class="post-item"><h2>Company A Hiring</h2></div>
        <div class="post-item"><h2>Company B Hiring</h2></div>
        <div class="post-item"><h2>Company C Hiring</h2></div>
        <div class="post-item"><h2>Company D Hiring</h2></div>
      </body>
    </html>
    """
    ptype, reason = classify_page_type(
        url="https://campusdrive.in/category/2027-batch-drives",
        html_content=html_category,
        title="2027 Batch Drives - Latest Off Campus Drives",
    )
    assert ptype == PageType.CATEGORY_PAGE
    assert "category" in reason.lower()

    # 2026 Batch Drives
    ptype_2026, _ = classify_page_type(
        url="https://campusdrive.in/2026-batch-drives",
        html_content=html_category,
        title="2026 Batch Drives",
    )
    assert ptype_2026 == PageType.CATEGORY_PAGE


def test_page_type_classifier_rejects_interview_questions():
    """FreshersDunia Interview Questions must be classified as NAVIGATION."""
    html_prep = """
    <html>
      <head><title>INTERVIEW QUESTIONS - TCS, Infosys, Cognizant</title></head>
      <body>
        <h1>TCS Top 50 Interview Questions and Answers</h1>
        <p>Prepare for your upcoming technical interview with these solved questions.</p>
      </body>
    </html>
    """
    ptype, reason = classify_page_type(
        url="https://freshersdunia.com/interview-questions",
        html_content=html_prep,
        title="INTERVIEW QUESTIONS - TCS, Infosys, Cognizant",
    )
    assert ptype == PageType.NAVIGATION
    assert "prep" in reason.lower() or "interview" in reason.lower()


def test_page_type_classifier_accepts_real_job_detail():
    """A real individual job detail page must be classified as JOB_DETAIL."""
    html_job = """
    <html>
      <head><title>Amazon - Software Development Engineer I</title></head>
      <body>
        <h1>Software Development Engineer I</h1>
        <h2>Job Description</h2>
        <p>We are looking for an SDE I to build scalable cloud microservices.</p>
        <h2>Eligibility Criteria</h2>
        <p>B.E/B.Tech in CS/IT. Passing out year 2026.</p>
        <a href="https://amazon.jobs/apply" class="btn-apply">Apply Online</a>
      </body>
    </html>
    """
    ptype, reason = classify_page_type(
        url="https://campusdrive.in/amazon-sde-hiring-2026",
        html_content=html_job,
        title="Amazon - Software Development Engineer I",
    )
    assert ptype == PageType.JOB_DETAIL


def test_page_type_classifier_accepts_genuine_drive_detail():
    """A genuine recruitment drive posting must be classified as DRIVE_DETAIL."""
    html_drive = """
    <html>
      <head><title>TCS Off Campus Drive 2026 - Register Online</title></head>
      <body>
        <h1>TCS National Qualifier Test (NQT) Off Campus Drive 2026</h1>
        <h2>Eligibility Criteria</h2>
        <p>Eligible Batches: 2026 passing out students. B.E/B.Tech/MCA.</p>
        <a href="https://nextstep.tcs.com/apply" class="btn">Apply Now</a>
      </body>
    </html>
    """
    ptype, reason = classify_page_type(
        url="https://campusdrive.in/tcs-nqt-off-campus-drive-2026",
        html_content=html_drive,
        title="TCS Off Campus Drive 2026 - Register Online",
    )
    assert ptype == PageType.DRIVE_DETAIL


# ==============================================================================
# 2. CAMPUSDRIVE EXTRACTION DEFECT REPAIRS
# ==============================================================================

def test_campusdrive_extraction_does_not_fallback_to_article_url(monkeypatch):
    """When direct employer apply link is missing, apply_url must be None."""
    html_without_apply = """
    <html>
      <body>
        <article>
          <h1>Cognizant Off Campus Drive - Graduate Trainee</h1>
          <p>Cognizant is hiring graduate engineer trainees.</p>
          <p>Last Date to Register: 30 November 2026</p>
        </article>
      </body>
    </html>
    """
    import scrapers.campusdrive as cd_module
    monkeypatch.setattr(cd_module.http_client, "get", lambda url: (html_without_apply, 200, "SUCCESS"))

    detail = extract_campusdrive_detail("https://campusdrive.in/cognizant-graduate-trainee")
    assert detail.get("apply_url") is None
    assert detail.get("apply_url") != "https://campusdrive.in/cognizant-graduate-trainee"


def test_campusdrive_extraction_does_not_fabricate_0_to_1_years(monkeypatch):
    """When experience is unstated, min/max must be None and status NOT_SPECIFIED."""
    html_unstated_exp = """
    <html>
      <body>
        <article>
          <h1>Accenture Hiring Associate Software Engineer</h1>
          <p>Join Accenture Advanced Technology Centers in India.</p>
          <a href="https://accenture.com/apply">Apply Now</a>
        </article>
      </body>
    </html>
    """
    import scrapers.campusdrive as cd_module
    monkeypatch.setattr(cd_module.http_client, "get", lambda url: (html_unstated_exp, 200, "SUCCESS"))

    detail = extract_campusdrive_detail("https://campusdrive.in/accenture-ase-hiring")
    assert detail["experience_min_years"] is None
    assert detail["experience_max_years"] is None
    assert detail["experience_status"] == "NOT_SPECIFIED"


# ==============================================================================
# 3. LLM EVIDENCE VALIDATOR DEFECT REPAIRS
# ==============================================================================

def test_llm_adapter_rejects_fabricated_experience_quote():
    """LLM verifier rejects responses with fabricated experience quotes."""
    adapter = LLMVerifierAdapter()
    data = {
        "opportunity_type": "INDIVIDUAL_FRESHER_JOB",
        "is_fresher_eligible": True,
        "confidence": 0.95,
        "eligible_batches": ["2026"],
        "experience_assessment": "FRESHER_ELIGIBLE",
        "experience_quote": "0-0 years experience required for recent grads",  # Fabricated
        "batch_quote": "",
        "has_experience_contradiction": False,
        "supporting_evidence": ["Software Development Engineer role"],
        "contradictory_evidence": [],
        "decision": "ACCEPT",
        "rejection_reasons": [],
    }
    source_text = "Software Development Engineer role at Amazon Bangalore. Technical development."
    status, ok, reason, rejections = adapter._process_schema(data, source_text=source_text)
    assert status == LLMStatus.REJECTED
    assert ok is False
    assert any("fabricated experience quote" in r.lower() for r in [reason] + rejections)


def test_llm_adapter_rejects_fabricated_batch_quote():
    """LLM verifier rejects responses with fabricated batch quotes."""
    adapter = LLMVerifierAdapter()
    data = {
        "opportunity_type": "INDIVIDUAL_FRESHER_JOB",
        "is_fresher_eligible": True,
        "confidence": 0.95,
        "eligible_batches": ["2027"],
        "experience_assessment": "FRESHER_ELIGIBLE",
        "experience_quote": "",
        "batch_quote": "Eligible Batches: 2027 only",  # Fabricated
        "has_experience_contradiction": False,
        "supporting_evidence": ["Software role"],
        "contradictory_evidence": [],
        "decision": "ACCEPT",
        "rejection_reasons": [],
    }
    source_text = "Software role at Qualcomm Bangalore. Good C++ and Python skills."
    status, ok, reason, rejections = adapter._process_schema(data, source_text=source_text)
    assert status == LLMStatus.REJECTED
    assert ok is False
    assert any("fabricated batch quote" in r.lower() for r in [reason] + rejections)


def test_llm_adapter_routes_not_specified_experience_to_manual_review():
    """When experience is NOT_SPECIFIED, LLM cannot ACCEPT -> routes to MANUAL_REVIEW."""
    adapter = LLMVerifierAdapter()
    data = {
        "opportunity_type": "INDIVIDUAL_FRESHER_JOB",
        "is_fresher_eligible": True,
        "confidence": 0.8,
        "eligible_batches": [],
        "experience_assessment": "NOT_SPECIFIED",
        "experience_quote": "",
        "batch_quote": "",
        "has_experience_contradiction": False,
        "supporting_evidence": ["Role: Software Engineer"],
        "contradictory_evidence": [],
        "decision": "ACCEPT",
        "rejection_reasons": [],
    }
    source_text = "Role: Software Engineer at CGI India. Artificial intelligence practice."
    status, ok, reason, rejections = adapter._process_schema(data, source_text=source_text)
    assert status == LLMStatus.MANUAL_REVIEW
    assert ok is False


# ==============================================================================
# 4. APPLICATION VERIFIER HARDENING TESTS
# ==============================================================================

def test_application_verifier_ignores_generic_search_form(monkeypatch):
    """Page with only a search form and generic 'apply' word is UNKNOWN, not OPEN."""
    html_search_only = """
    <html>
      <head><title>Company Careers</title></head>
      <body>
        <h1>Explore Careers</h1>
        <form role="search" id="job-search" action="/search">
          <input type="search" name="q" placeholder="Search and apply for jobs...">
          <button type="submit">Search</button>
        </form>
      </body>
    </html>
    """
    import extraction.apply_link_resolver as alr_module
    monkeypatch.setattr(alr_module.ApplyLinkResolver, "_fetch_page_content", lambda url, timeout: (html_search_only, 200, url, [url], None))

    res = ApplyLinkResolver.verify_application_live("https://careers.example.com/search")
    assert res.status == "UNKNOWN"
    assert res.status != "OPEN"


def test_application_verifier_requires_matching_expected_company(monkeypatch):
    """Expected company must match the page content or domain; else UNKNOWN."""
    html_asian_paints = """
    <html>
      <head><title>Asian Paints Careers - Paint Technologist</title></head>
      <body>
        <h1>Executive - Paint Technologist</h1>
        <button id="apply-button">Apply Now</button>
      </body>
    </html>
    """
    import extraction.apply_link_resolver as alr_module
    monkeypatch.setattr(alr_module.ApplyLinkResolver, "_fetch_page_content", lambda url, timeout: (html_asian_paints, 200, "https://careers.asianpaints.com/job/101", ["https://careers.asianpaints.com/job/101"], None))

    res = ApplyLinkResolver.verify_application_live(
        "https://careers.asianpaints.com/job/101",
        expected_company="Amazon",
    )
    assert res.status == "UNKNOWN"
    assert "does not confirm expected employer 'Amazon'" in res.evidence_text


def test_application_verifier_finds_requisition_in_query_param(monkeypatch):
    """CGI style query parameter jobid=J0926-1187 must be recognized."""
    html_cgi = """
    <html>
      <head><title>CGI Careers</title></head>
      <body>
        <h1>Java AI Apprentice</h1>
        <p>Requisition: J0926-1187</p>
        <button id="apply-button">Apply Online</button>
      </body>
    </html>
    """
    import extraction.apply_link_resolver as alr_module
    monkeypatch.setattr(alr_module.ApplyLinkResolver, "_fetch_page_content", lambda url, timeout: (html_cgi, 200, "https://cgi.njoyn.com/corp/xweb/xweb.asp?jobid=J0926-1187", ["https://cgi.njoyn.com/corp/xweb/xweb.asp?jobid=J0926-1187"], None))

    res = ApplyLinkResolver.verify_application_live(
        "https://cgi.njoyn.com/corp/xweb/xweb.asp?jobid=J0926-1187",
        expected_requisition_id="J0926-1187",
        expected_company="CGI",
    )
    assert res.requisition_id_found is True
    assert res.status == "OPEN"


# ==============================================================================
# 5. INVARIANT ASSERTION MULTI-PILLAR ENFORCEMENT
# ==============================================================================

def test_assert_approval_invariants_fails_closed():
    """All 11 invariant conditions must fail closed if any is unmet."""
    base_approved = Opportunity(
        opportunity_id="inv_test_001",
        title="Software Engineer",
        company="NatWest Group",
        role_family="SOFTWARE_ENGINEERING",
        final_status=FinalApprovalStatus.APPROVED,
        llm_status=LLMStatus.APPROVED,
        llm_approved=True,
        company_verification_status=CompanyVerificationStatus.VERIFIED_EMPLOYER_POSTING,
        application_status=ApplicationStatus.OPEN,
        application_verification_result=ApplicationVerificationResult(
            original_url="https://jobs.natwest.com/1",
            resolved_url="https://jobs.natwest.com/1",
            http_status=200,
            status="OPEN",
            evidence_text="Active requisition verified on employer portal",
            checked_at="2026-11-17T12:00:00Z",
        ),
        experience_status="FRESHER_ELIGIBLE",
        experience_max_years=1.0,
        rejection_reasons=[],
    )

    # Clean approved passes
    assert_approval_invariants(base_approved)

    # 1. Missing application result
    bad_1 = base_approved.model_copy(update={"application_verification_result": None})
    with pytest.raises(ValueError, match="application_verification_result is None"):
        assert_approval_invariants(bad_1)

    # 2. Application result not OPEN
    bad_2 = base_approved.model_copy(update={"application_status": ApplicationStatus.UNKNOWN})
    with pytest.raises(ValueError, match="application is not OPEN"):
        assert_approval_invariants(bad_2)

    # 3. Unverified employer
    bad_3 = base_approved.model_copy(update={"company_verification_status": CompanyVerificationStatus.UNVERIFIED})
    with pytest.raises(ValueError, match="employer is not verified corporate posting"):
        assert_approval_invariants(bad_3)

    # 4. Commercial experience > 1.0 years
    bad_4 = base_approved.model_copy(update={"experience_max_years": 2.0})
    with pytest.raises(ValueError, match="exceeds fresher ceiling"):
        assert_approval_invariants(bad_4)
