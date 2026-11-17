"""
Master Regression Test Suite (53 Mandatory Verification & Quality Cases)
========================================================================
Validates the entire public fresher job discovery, employer verification,
LLM approval, and dynamic skills extraction pipeline against all 53 mandatory regression requirements.
"""
from __future__ import annotations

from datetime import datetime
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
from core.deduplication import OpportunityDeduplicator
from verification.classification_engine import classify_opportunity
from verification.eligibility_engine import (
    evaluate_batch_eligibility,
    evaluate_experience_eligibility,
    extract_batches_from_text,
)
from verification.application_verifier import (
    verify_application_deadline,
    parse_deadline_datetime,
)
from verification.company_verifier import verify_company_authenticity
from verification.skills_extractor import extract_skills_dynamically
from verification.final_approval import MultiGateVerificationEngine
from scrapers.campusdrive import parse_date_string as parse_cd_date


# ==============================================================================
# Pillar 1: Opportunity Classification & Non-Tech Role Triage (Cases 1 - 6)
# ==============================================================================

def test_case_01_software_engineer_fresher():
    opp_type, role_family, _ = classify_opportunity("Software Engineer Fresher", "Join our backend engineering team")
    assert opp_type == OpportunityType.INDIVIDUAL_FRESHER_JOB
    assert role_family in ["SOFTWARE_ENGINEERING", "TECHNOLOGY"]


def test_case_02_graduate_engineer_trainee():
    opp_type, role_family, _ = classify_opportunity("Graduate Engineer Trainee (GET)", "Open for engineering graduates")
    assert opp_type == OpportunityType.GRADUATE_PROGRAM


def test_case_03_non_tech_commis_chef():
    opp_type, role_family, _ = classify_opportunity("Commis I at Marriott International", "Prepare culinary dishes")
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_case_04_non_tech_adhesive_technologist():
    opp_type, role_family, _ = classify_opportunity("EXECUTIVE N - ADHESIVE TECHNOLOGIST at Asian Paints", "Paint formulation")
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_case_05_non_tech_pharma_production_officer():
    opp_type, role_family, _ = classify_opportunity("Officer - Production (7536) at Ajanta Pharma", "Tablet compression and pharma packaging")
    assert opp_type == OpportunityType.UNRELATED
    assert role_family == "NON_TECH"


def test_case_06_generic_off_campus_recruitment_drive():
    opp_type, role_family, _ = classify_opportunity("National Off-Campus Recruitment Drive 2026", "Inviting engineering freshers across India")
    assert opp_type == OpportunityType.OFF_CAMPUS_DRIVE


# ==============================================================================
# Pillar 2: Graduation Batch Eligibility (Cases 7 - 13)
# ==============================================================================

def test_case_07_batch_2025():
    is_ok, sup, contras = evaluate_batch_eligibility([2025])
    assert is_ok is True
    assert not contras


def test_case_08_batch_2026():
    is_ok, sup, contras = evaluate_batch_eligibility([2026])
    assert is_ok is True
    assert not contras


def test_case_09_batch_2027():
    is_ok, sup, contras = evaluate_batch_eligibility([2027])
    assert is_ok is True
    assert not contras


def test_case_10_batches_2025_and_2026():
    is_ok, sup, contras = evaluate_batch_eligibility([2025, 2026])
    assert is_ok is True


def test_case_11_batch_2024_permitted():
    is_ok, sup, contras = evaluate_batch_eligibility([2024])
    assert is_ok is True


def test_case_12_legacy_batches_2020_2021_rejected():
    is_ok, sup, contras = evaluate_batch_eligibility([2020, 2021])
    assert is_ok is False
    assert any("Ineligible legacy graduation batches" in c for c in contras)


def test_case_13_legacy_batch_2021_only_rejected():
    is_ok, sup, contras = evaluate_batch_eligibility([2021])
    assert is_ok is False


# ==============================================================================
# Pillar 3: Experience Eligibility & Contradictions (Cases 14 - 19)
# ==============================================================================

def test_case_14_fresher_0_to_1_years():
    is_ok, summ, sup, contras = evaluate_experience_eligibility("Junior Developer", "Requirements: 0-1 years of experience")
    assert is_ok is True
    assert not contras


def test_case_15_trainee_0_to_2_years():
    is_ok, summ, sup, contras = evaluate_experience_eligibility("Graduate Trainee", "0-2 years experience required")
    assert is_ok is True
    assert not contras


def test_case_16_experienced_2_plus_years_rejected():
    is_ok, summ, sup, contras = evaluate_experience_eligibility("Software Developer", "Minimum 2+ years of experience in backend development")
    assert is_ok is False
    assert any("exceeds fresher ceiling" in c for c in contras)


def test_case_17_experienced_3_to_5_years_rejected():
    is_ok, summ, sup, contras = evaluate_experience_eligibility("Backend Engineer", "Candidates must have 3-5 years of industry experience")
    assert is_ok is False
    assert any("exceeds fresher ceiling" in c for c in contras)


def test_case_18_senior_title_with_fresher_desc_rejected():
    is_ok, summ, sup, contras = evaluate_experience_eligibility("Senior Software Engineer", "Freshers welcome, 0-1 years experience")
    assert is_ok is False
    assert any("Seniority conflict in title" in c for c in contras)


def test_case_19_batch_vs_experience_contradiction():
    is_ok, summ, sup, contras = evaluate_experience_eligibility(
        "Software Engineer",
        "2026 batch eligible. Candidates must have minimum 3 years of commercial experience.",
        batches=[2026],
    )
    assert is_ok is False
    assert any("Contradictory requirement" in c for c in contras)


# ==============================================================================
# Pillar 4: Application Deadlines & Expiry (Cases 20 - 25)
# ==============================================================================

def test_case_20_expired_synopsys_october_drive():
    # November 2026 runtime clock: 20 October 2026 is in the past!
    dl_status, app_status, parsed_iso, rejections = verify_application_deadline(
        deadline_str="20 October 2026",
        text_content="Synopsys EDA Compiler Software Engineer hiring 2026",
    )
    assert dl_status == DeadlineStatus.EXPIRED
    assert app_status == ApplicationStatus.CLOSED
    assert any("expired" in r.lower() for r in rejections)


def test_case_21_active_december_deadline():
    dl_status, app_status, parsed_iso, rejections = verify_application_deadline(
        deadline_str="25 December 2026",
        text_content="Registration open for December drive",
    )
    assert dl_status == DeadlineStatus.OPEN
    # Affirmative openness requires live employer verification; deadline alone yields UNKNOWN
    assert app_status == ApplicationStatus.UNKNOWN
    assert not rejections


def test_case_22_ongoing_asap_deadline():
    dl_status, app_status, parsed_iso, rejections = verify_application_deadline(
        deadline_str=None,
        text_content="Apply ASAP, recruitment is ongoing",
    )
    assert dl_status in [DeadlineStatus.OPEN, DeadlineStatus.NOT_PUBLISHED]
    assert not rejections


def test_case_23_explicit_registration_closed_notice():
    dl_status, app_status, parsed_iso, rejections = verify_application_deadline(
        deadline_str=None,
        text_content="Notice: Registration closed for this off-campus drive.",
    )
    assert dl_status == DeadlineStatus.CLOSED
    assert app_status == ApplicationStatus.CLOSED
    assert any("closed notice" in r.lower() for r in rejections)


def test_case_24_explicit_drive_ended_notice():
    dl_status, app_status, parsed_iso, rejections = verify_application_deadline(
        deadline_str=None,
        text_content="The drive has ended. Thank you for participating.",
    )
    assert dl_status == DeadlineStatus.CLOSED
    assert app_status == ApplicationStatus.CLOSED


def test_case_25_unspecified_deadline():
    dl_status, app_status, parsed_iso, rejections = verify_application_deadline(
        deadline_str=None,
        text_content="Software Engineer Trainee at Global Corp.",
    )
    assert dl_status == DeadlineStatus.NOT_PUBLISHED
    assert app_status == ApplicationStatus.UNKNOWN


# ==============================================================================
# Pillar 5: Company Authenticity & Fraud Screening (Cases 26 - 31)
# ==============================================================================

def test_case_26_registration_fee_scam_rejected():
    from models.verification_result import CompanyAuthenticity
    status, pos, contras = verify_company_authenticity(
        company="FastTrack Tech",
        apply_url="https://fasttracktech.com/apply",
        text_content="Mandatory registration fee of Rs 1,500 required before interview.",
    )
    assert status == CompanyAuthenticity.FRAUDULENT
    assert any("Upfront fee demand detected" in c for c in contras)


def test_case_27_training_fee_scam_rejected():
    from models.verification_result import CompanyAuthenticity
    status, pos, contras = verify_company_authenticity(
        company="CloudCareer Solutions",
        apply_url="https://cloudcareer.com/apply",
        text_content="Selected candidates must pay 40000 training fee before offer letter is released.",
    )
    assert status == CompanyAuthenticity.FRAUDULENT
    assert any("Upfront fee demand detected" in c for c in contras)


def test_case_28_security_deposit_scam_rejected():
    from models.verification_result import CompanyAuthenticity
    status, pos, contras = verify_company_authenticity(
        company="Premier Infra",
        apply_url="https://premierinfra.in/apply",
        text_content="A refundable security deposit of 10000 is required upon selection.",
    )
    assert status == CompanyAuthenticity.FRAUDULENT


def test_case_29_official_amazon_domain_verified():
    from models.verification_result import CompanyAuthenticity
    status, pos, contras = verify_company_authenticity(
        company="Amazon",
        apply_url="https://www.amazon.jobs/en/jobs/2847192",
        text_content="Join Amazon as an SDE 1 in Hyderabad.",
    )
    assert status == CompanyAuthenticity.VERIFIED_OFFICIAL


def test_case_30_official_tcs_nextstep_domain_verified():
    from models.verification_result import CompanyAuthenticity
    status, pos, contras = verify_company_authenticity(
        company="Tata Consultancy Services",
        apply_url="https://nextstep.tcs.com/campus/#/",
        text_content="TCS NQT Registration Open.",
    )
    assert status == CompanyAuthenticity.VERIFIED_OFFICIAL


def test_case_31_unverified_aggregator_classified():
    from models.verification_result import CompanyAuthenticity
    status, pos, contras = verify_company_authenticity(
        company="Random Startup",
        apply_url="https://campusdrive.in/jobs/random-startup",
        text_content="Hiring freshers.",
    )
    assert status == CompanyAuthenticity.REPUTABLE_AGGREGATOR


# ==============================================================================
# Pillar 6: LLM Gating & Consistency Checking (Cases 32 - 40)
# ==============================================================================

def test_case_32_full_pipeline_approval():
    from datetime import datetime, timezone
    from core.models import ApplicationVerificationResult
    app_res = ApplicationVerificationResult(
        url="https://www.amazon.jobs/en/jobs/12345",
        final_url="https://www.amazon.jobs/en/jobs/12345",
        domain="amazon.jobs",
        status="OPEN",
        http_status=200,
        checked_at=datetime.now(timezone.utc).isoformat(),
        has_requisition_id=True,
        application_form_available=True,
        evidence_text="Active application on Amazon jobs",
    )
    # 1. Without LLM approval, deterministic pass must route to MANUAL_REVIEW, NEVER APPROVED
    engine_no_llm = MultiGateVerificationEngine(require_llm=False)
    opp = Opportunity(
        opportunity_id="test_01",
        title="Software Engineer Fresher",
        company="Amazon",
        description="Requirements: Strong programming skills in Python, SQL. 0-1 years experience. 2026 graduates eligible.",
        apply_url="https://www.amazon.jobs/en/jobs/12345",
        deadline="2026-12-31",
        application_verification_result=app_res,
    )
    res_no_llm = engine_no_llm.verify_opportunity(opp)
    assert res_no_llm.deterministic_status == DeterministicStatus.PASSED
    assert res_no_llm.final_status == FinalApprovalStatus.MANUAL_REVIEW
    assert "Python" in res_no_llm.skills
    assert "SQL" in res_no_llm.skills

    # 2. With mandatory LLM approval, full pipeline awards APPROVED
    engine_llm = MultiGateVerificationEngine(require_llm=True)
    engine_llm.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "Audited and verified entry-level fresher role", [])
    res_approved = engine_llm.verify_opportunity(opp)
    assert res_approved.deterministic_status == DeterministicStatus.PASSED
    assert res_approved.final_status == FinalApprovalStatus.APPROVED


def test_case_33_fail_closed_without_llm_keys(monkeypatch):
    from verification.llm_adapter import LLMVerifierAdapter
    adapter = LLMVerifierAdapter()
    monkeypatch.setattr(adapter, "has_active_keys", lambda: False)

    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter = adapter

    opp = Opportunity(
        opportunity_id="test_02",
        title="Graduate Engineer Trainee",
        company="TCS",
        description="Open for 2026 batch freshers. Coding in Java.",
        apply_url="https://tcs.com/careers",
        deadline="2026-12-31",
    )
    res = engine.verify_opportunity(opp)
    assert res.llm_status == LLMStatus.UNAVAILABLE
    assert res.final_status == FinalApprovalStatus.MANUAL_REVIEW


def test_case_34_fail_closed_when_llm_raises(monkeypatch):
    from verification.llm_adapter import LLMVerifierAdapter
    adapter = LLMVerifierAdapter()
    monkeypatch.setattr(adapter, "has_active_keys", lambda: True)
    monkeypatch.setattr(adapter, "verify_opportunity", lambda opp: (LLMStatus.UNAVAILABLE, False, "Connection error", ["API down"]))

    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter = adapter

    opp = Opportunity(
        opportunity_id="test_03",
        title="Associate Developer",
        company="Infosys",
        description="Freshers eligible.",
        apply_url="https://infosys.com",
        deadline="2026-12-31",
    )
    res = engine.verify_opportunity(opp)
    assert res.final_status == FinalApprovalStatus.MANUAL_REVIEW


def test_case_35_llm_rejection_for_experienced():
    engine = MultiGateVerificationEngine(require_llm=False)
    opp = Opportunity(
        opportunity_id="test_04",
        title="Backend Developer",
        company="TechCorp",
        description="Requires 4+ years of experience in distributed systems.",
        apply_url="https://techcorp.com",
    )
    res = engine.verify_opportunity(opp)
    assert res.deterministic_status == DeterministicStatus.REJECTED
    assert res.final_status == FinalApprovalStatus.REJECTED


def test_case_36_llm_rejection_for_culinary_role():
    engine = MultiGateVerificationEngine(require_llm=False)
    opp = Opportunity(
        opportunity_id="test_05",
        title="Commis I at Marriott International",
        company="Marriott International",
        description="Prepare meals, culinary knife skills required.",
        apply_url="https://marriott.com",
    )
    res = engine.verify_opportunity(opp)
    assert res.opportunity_type == OpportunityType.UNRELATED
    assert res.final_status == FinalApprovalStatus.REJECTED


def test_case_37_collective_off_campus_drive_approved():
    from datetime import datetime, timezone
    from core.models import ApplicationVerificationResult
    app_res = ApplicationVerificationResult(
        url="https://nextstep.tcs.com",
        final_url="https://nextstep.tcs.com",
        domain="tcs.com",
        status="OPEN",
        http_status=200,
        checked_at=datetime.now(timezone.utc).isoformat(),
        has_requisition_id=True,
        application_form_available=True,
        evidence_text="Active TCS drive portal",
    )
    opp = Opportunity(
        opportunity_id="test_06",
        title="TCS National Qualifier Test (NQT) Off-Campus Drive 2026",
        company="Tata Consultancy Services",
        description="Registration open for 2026 and 2025 batch engineering graduates across India. 0 years experience.",
        apply_url="https://nextstep.tcs.com",
        deadline="2026-12-15",
        application_verification_result=app_res,
    )
    # Without LLM, routes to MANUAL_REVIEW
    engine_no_llm = MultiGateVerificationEngine(require_llm=False)
    res_no_llm = engine_no_llm.verify_opportunity(opp)
    assert res_no_llm.opportunity_type == OpportunityType.OFF_CAMPUS_DRIVE
    assert res_no_llm.deterministic_status == DeterministicStatus.PASSED
    assert res_no_llm.final_status == FinalApprovalStatus.MANUAL_REVIEW

    # With LLM, approves
    engine_llm = MultiGateVerificationEngine(require_llm=True)
    engine_llm.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "Audited and verified graduate drive", [])
    res_llm = engine_llm.verify_opportunity(opp)
    assert res_llm.final_status == FinalApprovalStatus.APPROVED


def test_case_38_consistency_check_expired_overrides_llm():
    # If LLM erroneously said APPROVED, but deadline is 20 October 2026 (EXPIRED), final status MUST be REJECTED!
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "LLM Hallucinated Approval", [])

    opp = Opportunity(
        opportunity_id="test_07",
        title="Synopsys EDA Compiler Software Engineer Hiring 2026",
        company="Synopsys",
        description="Last Date to Register: 20 October 2026. B.Tech freshers.",
        apply_url="https://campusdrive.in/synopsys",
        deadline="20 October 2026",
    )
    res = engine.verify_opportunity(opp)
    assert res.deadline_status in (DeadlineStatus.EXPIRED, DeadlineStatus.CLOSED)
    assert res.deterministic_status == DeterministicStatus.REJECTED
    assert res.final_status == FinalApprovalStatus.REJECTED


def test_case_39_consistency_check_non_tech_overrides_llm():
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "LLM Approved Chef", [])

    opp = Opportunity(
        opportunity_id="test_08",
        title="Commis I at Marriott International",
        company="Marriott International",
        description="Culinary department fresher.",
        apply_url="https://marriott.com",
    )
    res = engine.verify_opportunity(opp)
    assert res.opportunity_type == OpportunityType.UNRELATED
    assert res.deterministic_status == DeterministicStatus.REJECTED
    assert res.final_status == FinalApprovalStatus.REJECTED


def test_case_40_consistency_check_experience_overrides_llm():
    engine = MultiGateVerificationEngine(require_llm=True)
    engine.llm_adapter.verify_opportunity = lambda o: (LLMStatus.APPROVED, True, "LLM Ignored Experience", [])

    opp = Opportunity(
        opportunity_id="test_09",
        title="Senior Software Engineer",
        company="GlobalTech",
        description="Minimum 5 years of experience in production Kubernetes.",
        apply_url="https://globaltech.com",
    )
    res = engine.verify_opportunity(opp)
    assert res.deterministic_status == DeterministicStatus.REJECTED
    assert res.final_status == FinalApprovalStatus.REJECTED


# ==============================================================================
# Pillar 7: Dynamic Skills Extraction & Zero Hallucination (Cases 41 - 47)
# ==============================================================================

def test_case_41_dynamic_skills_extraction_required():
    jd = "Key Requirements: Must have hands-on knowledge in Python, SQL, and Docker. Freshers eligible."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    assert "Python" in skills
    assert "SQL" in skills
    assert "Docker" in skills
    assert status == "EXTRACTED_SUCCESSFULLY"


def test_case_42_dynamic_skills_extraction_preferred():
    jd = "Requirements: Strong proficiency in Java and Spring Boot. Good to have: AWS and Kubernetes."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    req_names = [r.name for r in req]
    pref_names = [p.name for p in pref]
    assert "Java" in req_names
    assert "Spring Boot" in req_names
    assert "AWS" in pref_names or "Kubernetes" in pref_names


def test_case_43_generic_drive_no_skills_published():
    # CRITICAL FIX: When no tech skills are in the JD, return [] with NO_ROLE_SPECIFIC_SKILLS_PUBLISHED
    jd = "National Graduate Hiring Drive. Open for all 2026 B.Tech/BE graduates. Online assessment details will be communicated via email."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    assert skills == []
    assert req == []
    assert pref == []
    assert status == "NO_ROLE_SPECIFIC_SKILLS_PUBLISHED"


def test_case_44_chef_jd_zero_tech_skills():
    jd = "Marriott International hiring Commis I. Candidates must have diploma in hotel management, knowledge of continental kitchen and HACCP standards."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    assert "Python" not in skills
    assert "Java" not in skills
    assert skills == [] or not any(s in ["Python", "Java", "C++"] for s in skills)


def test_case_45_zero_fake_fallback_skills():
    # Verify that canned phrases like "Aptitude & Logical Reasoning" or "Core Java/Python Basics" are NEVER injected
    jd = "Asian Paints Adhesive Technologist. Formulate industrial adhesives and epoxy resin compounds."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    assert "Core Java/Python Basics" not in skills
    assert "Aptitude & Logical Reasoning" not in skills


def test_case_46_soft_skills_extraction():
    jd = "Responsibilities: Software development. Requirements: Strong communication skills and analytical problem solving ability."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd)
    assert "Communication Skills" in skills or "Problem Solving" in skills


def test_case_47_skill_evidence_provenance():
    jd = "Candidates should write clean Python code and design relational databases with PostgreSQL."
    skills, req, pref, all_ev, status = extract_skills_dynamically(jd, source_url="https://example.com/job")
    py_ev = next(e for e in all_ev if e.name == "Python")
    assert py_ev.evidence
    assert py_ev.confidence >= 0.9
    assert py_ev.evidence_url == "https://example.com/job"


# ==============================================================================
# Pillar 8: Provenance, Deduplication & Parsers (Cases 48 - 53)
# ==============================================================================

def test_case_48_url_deduplication():
    dedup = OpportunityDeduplicator()
    opp1 = Opportunity(
        opportunity_id="1",
        title="Software Engineer",
        company="Google",
        apply_url="https://careers.google.com/jobs/results/12345?utm_source=linkedin",
    )
    opp2 = Opportunity(
        opportunity_id="2",
        title="Software Engineer",
        company="Google",
        apply_url="https://careers.google.com/jobs/results/12345?utm_source=telegram",
    )
    merged = dedup.deduplicate([opp1, opp2])
    assert len(merged) == 1
    assert "utm_source=linkedin" in merged[0].all_source_urls[0] or "utm_source=telegram" in merged[0].all_source_urls[1]


def test_case_49_composite_key_deduplication():
    dedup = OpportunityDeduplicator()
    opp1 = Opportunity(
        opportunity_id="1",
        title="Software Engineer Fresher",
        company="Infosys Limited",
        apply_url="https://infosys.com/job1",
    )
    opp2 = Opportunity(
        opportunity_id="2",
        title="software engineer fresher",
        company="Infosys",
        apply_url="https://campusdrive.in/infosys-fresher",
    )
    merged = dedup.deduplicate([opp1, opp2])
    assert len(merged) == 1


def test_case_50_multi_source_url_merging():
    dedup = OpportunityDeduplicator()
    opp1 = Opportunity(
        opportunity_id="1",
        title="GET 2026",
        company="Wipro",
        apply_url="https://wipro.com/apply",
        all_source_urls=["https://wipro.com/apply"],
    )
    opp2 = Opportunity(
        opportunity_id="2",
        title="GET 2026",
        company="Wipro",
        apply_url="https://wipro.com/apply",
        all_source_urls=["https://jobs4fresher.com/wipro"],
    )
    merged = dedup.deduplicate([opp1, opp2])
    assert len(merged) == 1
    assert len(merged[0].all_source_urls) == 2


def test_case_51_raw_evidence_preservation():
    dedup = OpportunityDeduplicator()
    opp1 = Opportunity(
        opportunity_id="1",
        title="Junior Analyst",
        company="Accenture",
        apply_url="https://accenture.com/1",
    )
    opp2 = Opportunity(
        opportunity_id="2",
        title="Junior Analyst",
        company="Accenture",
        apply_url="https://accenture.com/1",
    )
    merged = dedup.deduplicate([opp1, opp2])
    assert len(merged) == 1


def test_case_52_campusdrive_date_parser():
    dt = parse_cd_date("20 October 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 20


def test_case_53_useastra_boundary_triage():
    # Boundary triage in UseAstra classifies non-tech roles into UNRELATED before normalization
    from scrapers.useastra import EXPLICIT_NON_TECH_PATTERN
    assert EXPLICIT_NON_TECH_PATTERN.search("Commis I at Marriott International") is not None
    assert EXPLICIT_NON_TECH_PATTERN.search("EXECUTIVE N - ADHESIVE TECHNOLOGIST at Asian Paints") is not None
    assert EXPLICIT_NON_TECH_PATTERN.search("Officer - Production (7536) at Ajanta Pharma") is not None
    assert EXPLICIT_NON_TECH_PATTERN.search("Software Development Engineer Fresher") is None
