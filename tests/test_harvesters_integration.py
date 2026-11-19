"""
Unit and Integration Tests for Production Harvesters (FreshersDunia & CampusDrive)
==================================================================================
Tests:
1. Multi-tier Guardrail 1: Experience parsing & fresher boundary enforcement.
2. Multi-tier Guardrail 2: Application Last Date check (< today's date rejection).
3. Multi-tier Guardrail 3: Link Health & safety unwrap validation.
4. Multi-tier Guardrail 4: ATS closed pattern detection.
5. Google Sheets Sync Parity: Complete 13-column formatting and row acceptance.
"""
from datetime import date, datetime
import pytest

from scrapers.freshersdunia_harvester import (
    parse_experience_info as fd_parse_exp,
    check_application_deadline as fd_check_deadline,
    CLOSED_PATTERNS as FD_CLOSED_PATTERNS,
)
from scrapers.campusdrive_harvester import (
    parse_experience_info as cd_parse_exp,
    check_application_deadline as cd_check_deadline,
    unwrap_and_clean_url as cd_unwrap_url,
    CLOSED_PATTERNS as CD_CLOSED_PATTERNS,
)
from filter_engine import evaluate_job
from google_sheets_sync import format_jobs_rows, is_valid_sheet_row


def test_guardrail_1_fresher_experience_parsing():
    # 0 years -> fresher
    fresher = fd_parse_exp("0 Years (Students / Recent Graduates)", "Intern")
    assert fresher["is_fresher"] is True
    assert fresher["min_years"] == 0.0

    # 3+ years -> experienced / rejected
    exp = fd_parse_exp("3 - 5 Years Experience", "Senior Analyst")
    assert exp["is_fresher"] is False
    assert exp["min_years"] >= 3.0

    cd_fresher = cd_parse_exp("Fresher / 0-1 Years", "Associate Engineer")
    assert cd_fresher["is_fresher"] is True


def test_guardrail_2_application_deadline_enforcement():
    ref_today = date(2026, 11, 19)

    # Past deadline -> must be rejected
    is_exp, norm, msg = fd_check_deadline("10 November 2026", reference_date=ref_today)
    assert is_exp is True
    assert "EXPIRED" in msg.upper()

    # Future deadline -> must be accepted
    is_exp, norm, msg = fd_check_deadline("30 November 2026", reference_date=ref_today)
    assert is_exp is False
    assert norm == "2026-11-30"

    # ASAP / Rolling -> must be accepted
    is_exp, norm, msg = fd_check_deadline("ASAP (Rolling / Open Until Filled)", reference_date=ref_today)
    assert is_exp is False


def test_guardrail_3_link_safety_unwrap():
    # Safety redirect unwrapping
    wrapped = "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fcareers.qualcomm.com%2Fcareers%2Fjob%2F446719784235"
    unwrapped = cd_unwrap_url(wrapped)
    assert unwrapped == "https://careers.qualcomm.com/careers/job/446719784235"


def test_guardrail_4_ats_closed_pattern_matching():
    sample_closed_texts = [
        "Thanks for your interest, but this position is closed.",
        "Thank you for your interest in HPE. This position has been closed.",
        "This job posting has expired and is no longer accepting applications.",
        "The position you are looking for is no longer available.",
        "No Longer Accepting Applications",
    ]
    import re
    for text in sample_closed_texts:
        matched = any(re.search(pat, text, re.IGNORECASE) for pat in FD_CLOSED_PATTERNS)
        assert matched is True, f"Failed to match closed pattern in: {text}"


def test_aggregator_location_acceptance_in_filter_engine():
    job = {
        "site": "freshersdunia",
        "title": "Software Engineer Trainee 2026",
        "company": "Hewlett Packard Enterprise",
        "location": "Bengaluru, Karnataka, India",
        "date_posted": "2026-11-19",
        "experience_range": "0 Years (Students / Recent Graduates)",
        "apply_url": "https://careers.hpe.com/job/123",
        "description": "Full stack developer opportunity in Bengaluru. Python, Java, C++ skills.",
        "job_level": "entry_level",
    }
    evaluated = evaluate_job(job)
    assert evaluated["is_valid_fresher_job"] is True


def test_google_sheets_format_and_row_validation_parity():
    freshersdunia_sample = {
        "Job Title": "HPE Off Campus 2026 Hiring Intern",
        "Company": "Hewlett Packard Enterprise (HPE)",
        "Location": "Bengaluru, Karnataka, India (560048)",
        "Role": "College Intern",
        "Date Posted": "2026-11-19",
        "Experience": "0 Years (Students / Recent Graduates)",
        "Min Salary": "Competitive",
        "Max Salary": "Competitive",
        "Apply URL": "https://careers.hpe.com/us/en/job/1211844/Intern",
        "Link Health Status": "VERIFIED_ACTIVE",
        "Source": "FRESHERSDUNIA",
        "skills/responsibilities": "Python, Java, C++, Technical Troubleshooting",
        "Application Last Date": "ASAP (Rolling / Open Until Filled)",
        "verification_status": "VERIFIED",
    }

    rows, diag = format_jobs_rows([freshersdunia_sample], return_diagnostics=True)
    assert len(rows) == 1
    assert rows[0][0] == "HPE Off Campus 2026 Hiring Intern"
    assert rows[0][1] == "Hewlett Packard Enterprise (HPE)"
    assert rows[0][8] == "https://careers.hpe.com/us/en/job/1211844/Intern"
    assert rows[0][9] == "FRESHERSDUNIA"

    # Must pass is_valid_sheet_row for Google Sheets sync
    assert is_valid_sheet_row(rows[0]) is True
