"""Unit Tests for Application Deadline and Live Status Engine."""
from verification.application_status import verify_application_status, parse_date_string


def test_parse_date_string():
    dt = parse_date_string("25 Nov 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.day == 25


def test_active_deadline_status_open():
    status, deadline, reason = verify_application_status(
        deadline_str="31 Dec 2026",
        text_content="Apply before 31 Dec 2026.",
    )
    assert status == "OPEN"
    assert "Active deadline" in reason


def test_passed_deadline_status_expired():
    status, deadline, reason = verify_application_status(
        deadline_str="01 Jan 2024",
        text_content="Applications closed on 01 Jan 2024.",
    )
    assert status == "EXPIRED"
    assert "has passed" in reason


def test_explicit_closed_notice():
    status, deadline, reason = verify_application_status(
        text_content="Registrations are now closed for this drive.",
    )
    assert status == "CLOSED"
    assert "Explicit closed notice" in reason


def test_missing_deadline_unknown():
    # Critical rule: Missing deadlines must remain UNKNOWN, never silently labeled OPEN
    status, deadline, reason = verify_application_status(
        text_content="Apply immediately for this entry level role.",
    )
    assert status == "UNKNOWN"
