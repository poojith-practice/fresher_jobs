"""Unit and integration tests for the interview_prep package.

Covers:
- Approved public-host matching and robots/sanitization in sources
- LLM pack normalization, schema validation, and fail-closed handling in curator
- A4 PDF rendering structure and non-empty output
- Cache key stability and file caching in runner
- Drive upload placeholders and Google Sheets cell formatting
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from interview_prep.curator import (
    CuratorError,
    escape_for_pdf,
    normalize_pack,
)
from interview_prep.drive import drive_configured, sheet_doc_cell, upload_pdf
from interview_prep.pdf_renderer import _slug, output_dir_for, render_interview_pdf
from interview_prep.runner import compute_job_cache_key, run_interview_docs
from interview_prep.sources import extract_question_lines, is_approved_host


def test_approved_host_filtering():
    assert is_approved_host("https://www.geeksforgeeks.org/sql-interview-questions/")
    assert is_approved_host("https://prepinsta.com/accenture/interview-questions/")
    assert is_approved_host("https://ambitionbox.com/interviews/tcs-questions")
    assert not is_approved_host("https://malicious-site.com/questions")
    assert not is_approved_host("https://youtube.com/watch?v=12345")
    assert not is_approved_host("https://twitter.com/jobs")


def test_extract_question_lines():
    sample_html = """
    <html>
      <body>
        <p>This is generic text that does not look like an interview question.</p>
        <p>What is the difference between WHERE and HAVING in SQL?</p>
        <li>Explain how polymorphism works in Java with an example.</li>
        <li>Write a program to reverse a linked list in Python?</li>
      </body>
    </html>
    """
    lines = extract_question_lines(sample_html)
    assert len(lines) >= 2
    assert any("where and having" in l.lower() for l in lines)
    assert any("polymorphism" in l.lower() for l in lines)


def test_normalize_pack_valid():
    raw_pack = {
        "role_summary": "Focuses on core SQL, data modeling, and basic Python.",
        "questions": [
            {
                "question": f"Technical question {i} regarding concepts?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": ["Bullet 1 explanation", "Bullet 2 explanation"],
                "example": "E.g. selecting customers with balance > 100",
            }
            for i in range(1, 13)
        ],
        "more_coding_questions": ["Reverse string", "Two sum"],
    }
    normalized = normalize_pack(raw_pack)
    assert len(normalized["questions"]) == 12
    assert normalized["role_summary"].startswith("Focuses on core")
    assert len(normalized["more_coding_questions"]) == 2


def test_normalize_pack_too_few_questions_fails_closed():
    raw_pack = {
        "role_summary": "Too short",
        "questions": [
            {
                "question": "What is Python?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": ["Interpreted language"],
            }
        ],
    }
    with pytest.raises(CuratorError):
        normalize_pack(raw_pack)


def test_normalize_pack_caps_coding_questions_at_two():
    raw_pack = {
        "role_summary": "Developer interview",
        "questions": [
            {
                "question": f"Coding challenge #{i}?",
                "kind": "coding",
                "origin": "role",
                "answer_bullets": ["Use hashing", "Time complexity O(N)"],
                "code": {"language": "python", "approach": "Plan", "code": "def solve(): pass"},
            }
            for i in range(1, 5)
        ] + [
            {
                "question": f"Technical concept #{i}?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": ["Concept details"],
            }
            for i in range(1, 10)
        ],
    }
    normalized = normalize_pack(raw_pack)
    coding_answered = [q for q in normalized["questions"] if q["kind"] == "coding"]
    assert len(coding_answered) <= 2
    # Overflow coding questions must be moved to more_coding_questions
    assert len(normalized["more_coding_questions"]) >= 2


def test_escape_for_pdf():
    assert escape_for_pdf("A & B < C > D") == "A &amp; B &lt; C &gt; D"
    assert escape_for_pdf(None) == ""


def test_slug_formatting():
    assert _slug("PwC India Pvt. Ltd.") == "PwC_India_Pvt_Ltd"
    assert _slug("Jr. Data Analyst / BI Developer") == "Jr_Data_Analyst_BI_Developer"


def test_pdf_rendering_creates_valid_pdf(tmp_path):
    job = {
        "company": "Acme Analytics",
        "title": "Junior Business Analyst",
        "tech_category": "Business Analyst",
        "location": "Mumbai, India",
        "site": "naukri",
        "date_posted": "2026-11-15",
        "skills_requirements": "SQL, Excel, Power BI, Python",
    }
    pack = {
        "role_summary": "Focuses on SQL queries, dashboarding in Power BI, and analytical problem solving.",
        "questions": [
            {
                "question": "What is the difference between VLOOKUP and XLOOKUP in Excel?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": [
                    "VLOOKUP searches left-to-right only, while XLOOKUP can search in any direction.",
                    "XLOOKUP handles missing matches gracefully with an optional if_not_found argument.",
                ],
                "example": "Using XLOOKUP to fetch employee department by ID without rearranging columns.",
            },
            {
                "question": "How do you calculate running totals in SQL?",
                "kind": "coding",
                "origin": "role",
                "answer_bullets": [
                    "Use the SUM() window function with an OVER clause and ORDER BY.",
                ],
                "code": {
                    "language": "sql",
                    "approach": "Partition by account and order by transaction date.",
                    "code": "SELECT trans_date, amount, SUM(amount) OVER (ORDER BY trans_date) AS running_total FROM transactions;",
                },
            },
        ] + [
            {
                "question": f"Question {i} about analytical thinking?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": ["Key bullet explanation"],
            }
            for i in range(3, 13)
        ],
        "more_coding_questions": ["Write SQL query to find second highest salary."],
    }
    pdf_path = tmp_path / "test_prep.pdf"
    rendered = render_interview_pdf(job, pack, pdf_path, prepared_at="2026-11-15 12:00")
    assert rendered.exists()
    assert rendered.stat().st_size > 1000  # non-empty PDF


def test_drive_placeholders(monkeypatch, tmp_path):
    monkeypatch.delenv("GDRIVE_UPLOAD_URL", raising=False)
    monkeypatch.delenv("GDRIVE_FOLDER_ID", raising=False)
    assert drive_configured() is False
    dummy_pdf = tmp_path / "doc.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")
    res = upload_pdf(dummy_pdf)
    assert res["drive_status"] == "not_configured"
    assert sheet_doc_cell(None) == ""
    assert sheet_doc_cell("https://drive.google.com/open?id=123") == "https://drive.google.com/open?id=123"


def test_cache_key_deterministic():
    job1 = {"title": "Data Analyst", "company": "Infosys", "skills_requirements": "SQL, Python", "apply_url": "https://naukri.com/1"}
    job2 = {"title": "Data Analyst", "company": "Infosys", "skills_requirements": "SQL, Python", "apply_url": "https://naukri.com/1"}
    job3 = {"title": "Data Analyst", "company": "Infosys", "skills_requirements": "SQL, Java", "apply_url": "https://naukri.com/1"}
    assert compute_job_cache_key(job1) == compute_job_cache_key(job2)
    assert compute_job_cache_key(job1) != compute_job_cache_key(job3)


def test_runner_skips_jobs_without_skills(tmp_path):
    jobs = [
        {"title": "Analyst", "company": "Company A", "skills_requirements": ""},
        {"title": "Developer", "company": "Company B", "skills_requirements": None},
    ]
    stats = run_interview_docs(jobs, output_base_dir=tmp_path)
    assert stats["failed"] == 2
    assert stats["generated"] == 0


def test_runner_with_mock_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "interview_prep.runner.gather_question_context",
        lambda *args, **kwargs: {
            "company_excerpts": ["Company asked about joins"],
            "role_excerpts": ["Role requires SQL knowledge"],
            "skill_excerpts": ["SQL window functions"],
            "sources": ["GeeksforGeeks (https://geeksforgeeks.org/sql)"],
        },
    )
    valid_pack_json = json.dumps({
        "role_summary": "Analyst interview prep",
        "questions": [
            {
                "question": f"Question #{i} about data?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": ["Point A", "Point B"],
                "example": "Sample example",
            }
            for i in range(1, 13)
        ],
        "more_coding_questions": ["Coding question 1"],
    })
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = valid_pack_json
    mock_llm.invoke.return_value = mock_response

    jobs = [
        {
            "title": "Jr Data Analyst",
            "company": "TestCorp",
            "tech_category": "Data Analyst",
            "location": "Mumbai",
            "site": "linkedin",
            "skills_requirements": "SQL, Python, Excel",
            "apply_url": "https://example.com/job1",
        }
    ]

    # First run: should generate
    stats1 = run_interview_docs(jobs, output_base_dir=tmp_path, llm=mock_llm)
    assert stats1["generated"] == 1
    assert stats1["cached"] == 0

    # Second run: should be cached
    stats2 = run_interview_docs(jobs, output_base_dir=tmp_path, llm=mock_llm)
    assert stats2["cached"] == 1
    assert stats2["generated"] == 0

    # Forced run: should regenerate
    stats3 = run_interview_docs(jobs, output_base_dir=tmp_path, force=True, llm=mock_llm)
    assert stats3["generated"] == 1


def test_runner_pending_only_and_sync_sheet(tmp_path, monkeypatch):
    valid_pack_json = json.dumps({
        "role_summary": "Backend fundamentals and SQL.",
        "questions": [
            {
                "question": f"Question #{i} about backend?",
                "kind": "technical",
                "origin": "role",
                "answer_bullets": ["Point A", "Point B"],
                "example": "Sample example",
            }
            for i in range(1, 13)
        ],
        "more_coding_questions": ["Two Sum"],
    })
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = valid_pack_json
    mock_llm.invoke.return_value = mock_response

    monkeypatch.setattr(
        "interview_prep.runner.gather_question_context",
        lambda company, role, skills: {"company_excerpts": [], "role_excerpts": [], "skill_excerpts": [], "sources": []},
    )
    monkeypatch.setattr(
        "interview_prep.runner.upload_pdf",
        lambda path: {"drive_file_id": "abc123", "drive_url": "https://drive.google.com/file/d/abc123/view", "drive_status": "uploaded"},
    )
    synced_calls = []
    monkeypatch.setattr(
        "interview_prep.runner.sync_interview_docs_to_sheet",
        lambda job_list: synced_calls.append(list(job_list)) or len(job_list),
    )

    jobs = [
        {
            "title": "Done Job",
            "company": "AlreadyDoneCorp",
            "tech_category": "Software Engineer",
            "skills_requirements": "Python, SQL",
            "apply_url": "https://example.com/done",
            "interview_doc_url": "https://drive.google.com/file/d/existing/view",
        },
        {
            "title": "Pending Job",
            "company": "PendingCorp",
            "tech_category": "Software Engineer",
            "skills_requirements": "Python, SQL",
            "apply_url": "https://example.com/pending",
            "interview_doc_url": "Pending Generation",
        },
    ]

    stats = run_interview_docs(
        jobs,
        output_base_dir=tmp_path,
        llm=mock_llm,
        pending_only=True,
        sync_sheet=True,
        max_workers=2,
    )
    assert stats["total_jobs"] == 1
    assert stats["generated"] == 1
    assert stats["sheet_rows_updated"] == 1
    assert len(synced_calls) == 1
    assert synced_calls[0][0]["interview_doc_url"] == "https://drive.google.com/file/d/abc123/view"


def test_merge_sheet_rows_preserves_existing_drive_url():
    from google_sheets_sync import merge_job_rows

    existing_url = "https://drive.google.com/file/d/keep_me/view?usp=drivesdk"
    base = [
        "Software Engineer", "TestCorp", "Bangalore", "Software Engineer",
        "2026-11-25", "0-1 Yrs", "Competitive", "Competitive",
        "https://example.com/job/99", "LINKEDIN", "2026-11-25 10:00", "Python, SQL",
        existing_url, "Not found from RocketReach",
    ]
    incoming_pending = list(base)
    incoming_pending[12] = "Pending Generation"

    merged = merge_job_rows([base], [incoming_pending])
    assert len(merged) == 1
    assert merged[0][12] == existing_url

    new_url = "https://drive.google.com/file/d/newer/view?usp=drivesdk"
    incoming_real = list(base)
    incoming_real[12] = new_url
    merged2 = merge_job_rows([base], [incoming_real])
    assert merged2[0][12] == new_url


def test_split_hr_columns_and_legacy_migration():
    from google_sheets_sync import parse_legacy_hr_details, merge_job_rows, format_jobs_rows

    assert parse_legacy_hr_details(
        "Reema Prasad (Talent Acquisition Lead) | Email: reema@hitachi.com | LinkedIn: https://linkedin.com/in/reema"
    ) == ["Reema Prasad", "Talent Acquisition Lead", "reema@hitachi.com", "not found", "https://linkedin.com/in/reema"]

    assert parse_legacy_hr_details("Not found from RocketReach") == ["not found"] * 5

    legacy_row = [
        "Software Engineer", "Hitachi", "Bangalore", "Software Engineer",
        "2026-11-25", "0-1 Yrs", "Competitive", "Competitive",
        "https://example.com/job/101", "LINKEDIN", "2026-11-25 10:00", "Python, SQL",
        "https://drive.google.com/file/d/doc/view",
        "Akhil Nair (Campus Recruiter) | Email: akhil@ey.com | LinkedIn: https://linkedin.com/in/akhil",
    ]
    migrated = merge_job_rows([legacy_row], [])
    assert len(migrated) == 1
    assert len(migrated[0]) == 18
    assert migrated[0][13:18] == ["Akhil Nair", "Campus Recruiter", "akhil@ey.com", "not found", "https://linkedin.com/in/akhil"]

    rows = format_jobs_rows([{
        "title": "Software Engineer",
        "company": "Acme",
        "location": "Bangalore",
        "tech_category": "Software Engineer",
        "date_posted": "2026-11-25",
        "experience_range": "0-1 Yrs",
        "apply_url": "https://example.com/job/102",
        "site": "linkedin",
        "skills_requirements": "Python",
        "llm_verified": True,
        "llm_eligible": True,
        "hr_name": "Jane Doe",
        "hr_role": "Technical Recruiter",
    }], require_salary=False, enrich_hr=False)
    assert len(rows[0]) == 18
    assert rows[0][13:18] == ["Jane Doe", "Technical Recruiter", "not found", "not found", "not found"]
