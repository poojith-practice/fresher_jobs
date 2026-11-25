from datetime import date, datetime, timezone

from google_sheets_sync import _normalize_date_display, format_jobs_rows, merge_job_rows


def test_normalize_date_display_formats_monsterindia_utc_to_ist_date():
    # 17:21 UTC -> 22:51 IST (same day)
    assert _normalize_date_display("2026-11-25T17:21:19+00:00") == "2026-11-25"
    # 19:25 UTC -> 00:55 IST next day
    assert _normalize_date_display("2026-11-25T19:25:59+00:00") == "2026-11-26"
    # Already YYYY-MM-DD
    assert _normalize_date_display("2026-11-25") == "2026-11-25"
    # Python date / datetime
    assert _normalize_date_display(date(2026, 11, 25)) == "2026-11-25"
    assert _normalize_date_display(datetime(2026, 11, 25, 19, 0, tzinfo=timezone.utc)) == "2026-11-26"


def test_format_and_merge_normalize_monsterindia_timestamps():
    jobs = [
        {
            "title": "Software Engineer",
            "company": "Acme",
            "location": "Hyderabad",
            "tech_category": "Software Engineer",
            "date_posted": "2026-11-25T17:21:19+00:00",
            "experience_range": "0-1 Yrs",
            "apply_url": "https://www.foundit.in/job/123",
            "site": "monsterindia",
            "skills_requirements": "Python, SQL, REST APIs",
            "llm_verified": True,
            "llm_eligible": True,
        }
    ]
    rows = format_jobs_rows(jobs, require_salary=False)
    assert len(rows) == 1
    assert rows[0][4] == "2026-11-25"

    existing = [
        [
            "Software Engineer", "OldCo", "Hyderabad", "Software Engineer",
            "2026-11-25T19:25:59+00:00", "0-1 Yrs", "Not Disclosed", "Not Disclosed",
            "https://www.foundit.in/job/999", "MONSTERINDIA", "2026-11-25T20:00:00",
            "Python, Java", "Pending Generation", "not found", "not found", "not found", "not found", "not found",
        ]
    ]
    merged = merge_job_rows(existing, rows)
    assert merged[0][4] == "2026-11-26"
    assert merged[1][4] == "2026-11-25"
