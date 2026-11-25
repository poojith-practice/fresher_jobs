"""
Tests for LinkedIn Scraper Resilience, Breaker Decoupling, and Explicit Title Verification.
"""
import time
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import MagicMock, patch

import filter_engine
from filter_engine import evaluate_job
import scraper
from scraper import (
    reset_linkedin_run_counters,
    hydrate_linkedin_description,
    _LINKEDIN_HYDRATION_STATS,
    _LINKEDIN_HYDRATION_COOLDOWN_UNTIL,
    _LINKEDIN_SEARCH_COOLDOWN_UNTIL,
)


def test_explicit_junior_title_evaluated_as_title_inference():
    """Explicit fresher/junior titles from LinkedIn must have valid experience even if JD is short/unhydrated."""
    job = {
        "title": "Graduate Engineer Trainee - Software",
        "company": "Infosys",
        "location": "Bangalore, India",
        "date_posted": datetime.now() - timedelta(hours=2),
        "experience_range": "Not specified",
        "site": "linkedin",
        "job_level": "entry_level",
        "description": "Short summary",
        "job_url": "https://www.linkedin.com/jobs/view/9999888877",
    }
    evaluated = evaluate_job(dict(job))
    assert evaluated["is_valid_fresher_job"] is True
    assert evaluated["experience_source"] == "title_inference"
    assert "Junior / Trainee" in evaluated["experience_range"]


def test_generic_title_without_jd_still_rejected_or_unverified():
    """Generic titles like 'Business Analyst' with no JD text must NOT be falsely marked valid."""
    job = {
        "title": "Business Analyst",
        "company": "Acme Corp",
        "location": "Mumbai, India",
        "date_posted": datetime.now() - timedelta(hours=2),
        "experience_range": "Not specified",
        "site": "linkedin",
        "job_level": "entry_level",
        "description": None,
        "job_url": "https://www.linkedin.com/jobs/view/9999888877",
    }
    evaluated = evaluate_job(dict(job))
    assert evaluated["is_valid_fresher_job"] is False
    assert evaluated["experience_source"] == "unknown"


def test_linkedin_hydration_429_sets_cooldown_not_permanent_death():
    """When hydration receives 429, it must set a temporary cooldown and NOT flip _LINKEDIN_RATE_LIMITED permanently."""
    reset_linkedin_run_counters()
    
    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch("curl_cffi.requests.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        mock_session_cls.return_value = mock_session

        raw_job = {
            "title": "Junior Python Developer",
            "company": "Tech Corp",
            "job_url": "https://www.linkedin.com/jobs/view/4493974838",
            "description": None,
        }
        hydrate_linkedin_description(raw_job)

        # Rate limited counter incremented
        assert _LINKEDIN_HYDRATION_STATS["rate_limited"] == 1
        # Breaker is NOT tripped permanently for search scraping
        assert scraper._LINKEDIN_RATE_LIMITED is False
        # Hydration cooldown is active
        assert scraper._LINKEDIN_HYDRATION_COOLDOWN_UNTIL > time.time()


def test_direct_ats_link_bypasses_linkedin_guest_endpoint():
    """Jobs with direct ATS links (e.g. Workday/Greenhouse) fetch JD from ATS directly."""
    reset_linkedin_run_counters()
    
    html_jd = "<html><body><div>Responsibilities: Develop Python code. Requirements: 0-1 years experience.</div></body></html>"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = html_jd

    with patch("requests.get", return_value=mock_resp):
        raw_job = {
            "title": "Associate Software Engineer",
            "company": "Autodesk",
            "job_url": "https://www.linkedin.com/jobs/view/4493974838",
            "job_url_direct": "https://autodesk.wd1.myworkdayjobs.com/en-US/Careers/job/Associate-Software-Engineer",
            "description": None,
        }
        hydrate_linkedin_description(raw_job)
        assert raw_job["description"] is not None
        assert "Develop Python code" in raw_job["description"]
        assert _LINKEDIN_HYDRATION_STATS["success"] == 1


def test_explicit_fresher_title_synthesizes_context_for_llm_gatekeeper():
    """Explicit fresher roles without JD synthesize card context so LLM Gatekeeper can verify and curate skills."""
    raw_job = {
        "title": "Graduate Engineer Trainee",
        "company": "Tata Consultancy Services",
        "location": "Bangalore, India",
        "date_posted": datetime.now() - timedelta(hours=3),
        "experience_range": "Not specified",
        "site": "linkedin",
        "job_level": "entry_level",
        "description": None,
        "job_url": "https://www.linkedin.com/jobs/view/4493974838",
    }
    evaluated = evaluate_job(dict(raw_job))
    assert evaluated["is_valid_fresher_job"] is True
    assert evaluated["experience_source"] == "title_inference"


def test_scrape_fresher_jobs_end_to_end_pipeline_simulation():
    """Simulate a complete scrape_fresher_jobs execution with raw DataFrame to verify no NameError or runtime crash."""
    from scraper import scrape_fresher_jobs
    import pandas as pd
    from unittest.mock import patch, MagicMock

    sample_df = pd.DataFrame([
        {
            "title": "Graduate Engineer Trainee",
            "company": "TCS",
            "location": "Bangalore, India",
            "date_posted": datetime.now() - timedelta(hours=2),
            "site": "linkedin",
            "job_level": "entry_level",
            "description": None,
            "job_url": "https://www.linkedin.com/jobs/view/4493974838",
            "job_url_direct": None,
        },
        {
            "title": "Business Analyst",
            "company": "Capco",
            "location": "Bangalore, India",
            "date_posted": datetime.now() - timedelta(hours=2),
            "site": "linkedin",
            "job_level": "entry_level",
            "description": None,
            "job_url": "https://www.linkedin.com/jobs/view/4494037893",
            "job_url_direct": None,
        }
    ])

    with patch("scraper.run_scraping_query", return_value=sample_df), \
         patch("llm_verifier.get_llm", return_value=None):
        results = scrape_fresher_jobs(
            hours_old=24,
            locations=["Bangalore"],
            roles_dict={"Software Engineer": ["Software Engineer"]},
            sites=["linkedin"],
            results_per_query=2,
        )
        assert "valid_jobs" in results
        assert "review_jobs" in results
        assert "rejected_jobs" in results
        # Generic Business Analyst with no JD went to review
        review_titles = [j.get("title") for j in results["review_jobs"]]
        assert "Business Analyst" in review_titles


def test_known_synced_urls_skips_hydration_and_llm():
    """Verify already-synced Sheet1 URLs skip hydration and LLM while preserving reconciliation."""
    from scraper import scrape_fresher_jobs
    import pandas as pd
    from unittest.mock import patch

    synced_url = "https://www.linkedin.com/jobs/view/999000111"
    sample_df = pd.DataFrame([
        {
            "title": "Graduate Engineer Trainee",
            "company": "TCS",
            "location": "Bangalore, India",
            "date_posted": datetime.now() - timedelta(hours=2),
            "site": "linkedin",
            "job_level": "entry_level",
            "description": None,
            "job_url": synced_url,
            "job_url_direct": None,
        }
    ])

    with patch("scraper.run_scraping_query", return_value=sample_df), \
         patch("scraper.hydrate_linkedin_description") as mock_hydrate, \
         patch("llm_verifier.verify_fresher_and_curate_skills") as mock_llm:
        results = scrape_fresher_jobs(
            hours_old=24,
            locations=["Bangalore"],
            roles_dict={"Software Engineer": ["Software Engineer"]},
            sites=["linkedin"],
            results_per_query=1,
            known_synced_urls={synced_url.upper()},
        )
        assert mock_hydrate.call_count == 0
        assert mock_llm.call_count == 0
        assert results["stats"]["pipeline_stages"]["already_synced_skipped"] == 1
        assert results["stats"]["reconciliation_invariants"]["raw_records_reconciled"] is True
        assert results["stats"]["reconciliation_invariants"]["unique_jobs_reconciled"] is True


def test_rotating_llm_reuses_cached_clients():
    """Verify RotatingLLM caches ChatOpenAI client instances per provider/key/model/max_tokens."""
    from llm_verifier import RotatingLLM
    from unittest.mock import patch, MagicMock

    llm = RotatingLLM()
    with patch("langchain_openai.ChatOpenAI", side_effect=lambda **kwargs: MagicMock()) as mock_cls:
        c1 = llm._get_client("openrouter", "key1", "https://openrouter.ai/api/v1", "m1", 600, {"reasoning": {"enabled": False}})
        c2 = llm._get_client("openrouter", "key1", "https://openrouter.ai/api/v1", "m1", 600, {"reasoning": {"enabled": False}})
        c3 = llm._get_client("openrouter", "key2", "https://openrouter.ai/api/v1", "m1", 600, {"reasoning": {"enabled": False}})
        assert c1 is c2
        assert c1 is not c3
        assert mock_cls.call_count == 2
