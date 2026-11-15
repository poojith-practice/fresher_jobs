"""
Unit Tests for Foundit (Monster India) Scraper and Hydration Adapter
===================================================================
Tests mock HTTP responses to verify parsing, error isolation, schema conformity,
and integration with filter_engine and llm_verifier.
"""

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
import pandas as pd
import pytest

from foundit_scraper import scrape_foundit_jobs, fetch_foundit_job_description
from filter_engine import evaluate_job


SAMPLE_FOUNDIT_SEARCH_RESPONSE = {
    "jobSearchResponse": {
        "data": [
            {
                "jobId": 69809614,
                "title": "Junior Data Analyst",
                "companyName": "Acme Technologies India",
                "locations": "Mumbai",
                "minimumExperience": {"years": 0},
                "maximumExperience": {"years": 0},
                "createdAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                "redirectUrl": "https://careers.acmetech.com/job/123",
                "jdUrl": "/job/junior-data-analyst-acme-technologies-69809614",
                "skills": "Python, SQL, Excel, Tableau",
                "minimumSalaryINRFilter": 350000,
                "maximumSalaryINRFilter": 550000,
                "hideCompanyName": False,
            },
            {
                "jobId": 69809615,
                "title": "Software Engineer Trainee",
                "companyName": "*Confidential Agency",
                "locations": "Hyderabad",
                "minimumExperience": {"years": 0},
                "maximumExperience": {"years": 1},
                "createdAt": int(datetime.now(timezone.utc).timestamp() * 1000),
                "hideCompanyName": True,
            },
        ]
    }
}

SAMPLE_FOUNDIT_DETAIL_RESPONSE = {
    "jobDetailResponse": {
        "jobId": 69809614,
        "description": "<div><p><b>About Role:</b> Looking for fresh graduate Junior Data Analyst.</p><p>Requirements: Python, SQL.</p></div>",
    }
}


def test_scrape_foundit_jobs_success():
    """Verifies that Foundit jobs are parsed, formatted to schema, and anonymous agencies filtered."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_FOUNDIT_SEARCH_RESPONSE

    with patch("foundit_scraper._get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_get_session.return_value = mock_session

        df = scrape_foundit_jobs("data analyst", "Mumbai", results_wanted=10)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1  # The confidential agency should be filtered out
        job = df.iloc[0]
        assert job["id"] == "fi-69809614"
        assert job["site"] == "monsterindia"
        assert job["title"] == "Junior Data Analyst"
        assert job["company"] == "Acme Technologies India"
        assert job["location"] == "Mumbai"
        assert job["experience_range"] == "0-0 Yrs"
        assert job["min_amount"] == 350000
        assert job["max_amount"] == 550000
        assert job["currency"] == "INR"
        assert "Python" in job["skills"]
        assert job["job_url"].startswith("https://www.foundit.in/job/")
        assert job["job_url_direct"] == "https://careers.acmetech.com/job/123"


def test_scrape_foundit_jobs_error_isolation():
    """Verifies that network or HTTP errors return an empty DataFrame without raising."""
    with patch("foundit_scraper._get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session.get.side_effect = ConnectionError("Network unreachable")
        mock_get_session.return_value = mock_session

        df = scrape_foundit_jobs("data analyst", "Mumbai")
        assert isinstance(df, pd.DataFrame)
        assert df.empty


def test_scrape_foundit_jobs_http_error():
    """Verifies that non-200 responses return empty DataFrame."""
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"

    with patch("foundit_scraper._get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_get_session.return_value = mock_session

        df = scrape_foundit_jobs("data analyst", "Mumbai")
        assert isinstance(df, pd.DataFrame)
        assert df.empty


def test_fetch_foundit_job_description_success():
    """Verifies that description is fetched and HTML tags are stripped."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_FOUNDIT_DETAIL_RESPONSE

    with patch("foundit_scraper._get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_get_session.return_value = mock_session

        desc = fetch_foundit_job_description("69809614")
        assert desc is not None
        assert "Looking for fresh graduate" in desc
        assert "About Role:" in desc
        assert "<div>" not in desc  # HTML properly stripped


def test_fetch_foundit_job_description_failure():
    """Verifies that detail failure returns None without raising."""
    with patch("foundit_scraper._get_http_session") as mock_get_session:
        mock_session = MagicMock()
        mock_session.get.side_effect = TimeoutError("Detail timeout")
        mock_get_session.return_value = mock_session

        desc = fetch_foundit_job_description("69809614")
        assert desc is None


def test_foundit_job_passes_filter_engine():
    """Verifies that a valid parsed Foundit job passes filter_engine.evaluate_job."""
    job_record = {
        "id": "fi-69809614",
        "site": "monsterindia",
        "job_url": "https://www.foundit.in/job/69809614",
        "job_url_direct": None,
        "title": "Junior Data Analyst",
        "company": "TCS",
        "location": "Mumbai",
        "date_posted": datetime.now(timezone.utc).isoformat(),
        "is_remote": False,
        "skills": "Python, SQL, Excel",
        "experience_range": "0-0 Yrs",
        "min_amount": 300000,
        "max_amount": 500000,
        "currency": "INR",
        "interval": "yearly",
        "description": "Role: Junior Data Analyst\nCompany: TCS\nSkills: Python, SQL",
    }
    evaluated = evaluate_job(job_record)
    assert evaluated["is_valid_fresher_job"] is True
    assert evaluated["tech_category"] == "Data Analyst"


def test_llm_verifier_hydrates_foundit():
    """Verifies that hydrate_job_description in llm_verifier calls Foundit adapter."""
    from llm_verifier import hydrate_job_description

    with patch("foundit_scraper.fetch_foundit_job_description") as mock_fetch:
        mock_fetch.return_value = "Detailed Foundit Job Description with full requirements."

        job = {
            "site": "monsterindia",
            "id": "fi-69809614",
            "apply_url": "https://www.foundit.in/job/test-69809614",
            "description": "short",
        }
        res_desc = hydrate_job_description(job)
        assert res_desc == "Detailed Foundit Job Description with full requirements."
        assert job["description"] == "Detailed Foundit Job Description with full requirements."
        mock_fetch.assert_called_once()


def test_scraper_site_dispatch_monsterindia():
    """Verifies that run_scraping_query dispatches to Foundit adapter for monsterindia."""
    from scraper import run_scraping_query
    with patch("foundit_scraper.scrape_foundit_jobs") as mock_scrape:
        mock_df = pd.DataFrame([{
            "id": "fi-123",
            "site": "monsterindia",
            "title": "Data Analyst",
            "company": "Infosys",
            "location": "Mumbai",
            "date_posted": datetime.now(timezone.utc).isoformat(),
            "skills": "Python",
            "experience_range": "0-0 Yrs",
            "min_amount": 300000,
            "max_amount": 450000,
            "currency": "INR",
            "description": "test",
        }])
        mock_scrape.return_value = mock_df

        res_df = run_scraping_query("data analyst", "Mumbai", sites=["monsterindia"])
        assert len(res_df) == 1
        assert res_df.iloc[0]["company"] == "Infosys"
        mock_scrape.assert_called_once()
