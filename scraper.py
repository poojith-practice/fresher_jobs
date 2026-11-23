"""
Core Multi-Board Scraper using JobSpy
=====================================
Fetches live jobs across Naukri, LinkedIn, and Indeed concurrently
with zero external paid API subscriptions ($0 cost).
Includes error-isolation, pacing, deduplication, and quality evaluation.
"""

import os
import time
import math
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import RLock
from typing import List, Dict, Any, Optional
import pandas as pd
try:
    import jobspy
    from jobspy import scrape_jobs
    from jobspy.linkedin import LinkedIn
    from jobspy.model import Site as JobSpySite
    from jobspy.naukri import Naukri
except ImportError:
    jobspy = None
    scrape_jobs = None
    LinkedIn = None
    JobSpySite = None
    Naukri = None

from config import (
    MAX_HOURS_OLD,
    TARGET_SITES,
    DEFAULT_LOCATIONS,
    INDEED_COUNTRY,
    RESULTS_PER_QUERY,
    QUERY_DELAY_SECONDS,
    QUERY_CONCURRENCY,
    JOBSPY_PROXIES,
    ROLE_QUERIES,
)
from filter_engine import (
    evaluate_job,
    is_within_hours,
    is_legitimate_company,
    is_valid_location,
    normalize_location_for_search,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FresherJobScraper")
_LINKEDIN_LOCK = RLock()
_LINKEDIN_HYDRATION_LOCK = RLock()
# Cache guest-endpoint descriptions for the current process so a rate-limited
# or repeated card does not cost another HTTP request during the same run.
_LINKEDIN_DESCRIPTION_CACHE: Dict[str, str] = {}


# Rate limit, concurrency control, and hydration telemetry
_LINKEDIN_MAX_REQUESTS = int(os.getenv("MAX_LINKEDIN_REQUESTS", "15"))
_LINKEDIN_REQUEST_COUNT = 0
_LINKEDIN_BACKOFF_DELAY = 1.5
_LINKEDIN_RATE_LIMITED: bool = False
_LINKEDIN_CONSECUTIVE_429: int = 0
_LINKEDIN_HYDRATION_STATS: Dict[str, int] = {
    "requests": 0,
    "failures": 0,
    "rate_limited": 0,
    "cached": 0,
    "success": 0,
}


def reset_linkedin_run_counters() -> None:
    """
    Resets the LinkedIn request cap, rate-limited flag, and hydration telemetry for a new scraping run.
    Ensures per-run isolation so earlier runs do not consume subsequent runs' caps.
    """
    global _LINKEDIN_REQUEST_COUNT, _LINKEDIN_RATE_LIMITED, _LINKEDIN_CONSECUTIVE_429
    with _LINKEDIN_LOCK:
        _LINKEDIN_REQUEST_COUNT = 0
        _LINKEDIN_RATE_LIMITED = False
        _LINKEDIN_CONSECUTIVE_429 = 0
    with _LINKEDIN_HYDRATION_LOCK:
        _LINKEDIN_HYDRATION_STATS["requests"] = 0
        _LINKEDIN_HYDRATION_STATS["failures"] = 0
        _LINKEDIN_HYDRATION_STATS["rate_limited"] = 0
        _LINKEDIN_HYDRATION_STATS["cached"] = 0
        _LINKEDIN_HYDRATION_STATS["success"] = 0


if Naukri is not None and LinkedIn is not None:
    class EntryLevelNaukri(Naukri):
        """Naukri adapter that targets freshers (0-1 yrs) using Naukri's native experience filter."""
        adapter_name = "EntryLevelNaukri"
        is_custom_adapter = True

        def _search_params(self):
            params = super()._search_params()
            # Naukri search API: experience=0 targets the 0-1 year fresher band
            params["experience"] = "0"
            return params


    class FresherLinkedIn(LinkedIn):
        """LinkedIn adapter configured for entry-level fresher roles with newest-first ordering."""
        adapter_name = "FresherLinkedIn"
        is_custom_adapter = True

        def _search_params(self):
            params = super()._search_params()
            # f_E=2 targets Entry level listings; sortBy=DD ensures newest postings first
            params["f_E"] = "2"
            params["sortBy"] = "DD"
            return params

        def _process_job(self, job_card, job_id: str):
            post = super()._process_job(job_card, job_id)
            if post is not None:
                # Explicitly mark job_level as entry_level from verified f_E=2 query
                post = post.model_copy(update={"job_level": "entry_level"})
            return post

    # Register custom adapters once globally for the scraper process if jobspy is available
    if jobspy is not None and JobSpySite is not None:
        try:
            jobspy.SCRAPER_MAPPING[JobSpySite.NAUKRI] = EntryLevelNaukri
            jobspy.SCRAPER_MAPPING[JobSpySite.LINKEDIN] = FresherLinkedIn
        except Exception as _e:
            logging.getLogger("scraper").debug("Failed to patch JobSpy scraper mapping: %s", _e)
else:
    class EntryLevelNaukri:
        adapter_name = "EntryLevelNaukri_Stub"
        is_custom_adapter = False

        def _search_params(self):
            return {"experience": "0"}

    class FresherLinkedIn:
        adapter_name = "FresherLinkedIn_Stub"
        is_custom_adapter = False

        def _search_params(self):
            return {"f_E": "2", "sortBy": "DD"}


def safe_str(val: Any) -> str:
    """Safely extracts string values handling pandas/numpy NaN without false truthiness."""
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    s = str(val).strip()
    return "" if s.lower() in {"nan", "none", "nat"} else s


def get_job_url(raw_job: Dict[str, Any]) -> str:
    """Extracts valid job URL or fallback identifier, avoiding NaN truthiness traps."""
    direct = safe_str(raw_job.get("job_url_direct"))
    if direct:
        return direct
    url = safe_str(raw_job.get("job_url"))
    if url:
        return url
    return safe_str(raw_job.get("id"))


def clean_str(val: Any) -> str:
    """Helper to sanitize string for composite deduplication key."""
    text = safe_str(val)
    if not text:
        return ""
    return "".join(c.lower() for c in text if c.isalnum() or c.isspace()).strip()


def hydrate_linkedin_description(raw_job: Dict[str, Any], session: Optional[Any] = None) -> None:
    """
    Hydrates full job description for candidate LinkedIn jobs via LinkedIn guest endpoint.
    Guarantees that explicit experience requirements in JD (e.g. 1-3 yrs, 5+ yrs) are captured.
    Stops immediately if a 429 rate limit is encountered.
    """
    import re
    import requests
    from bs4 import BeautifulSoup

    global _LINKEDIN_RATE_LIMITED
    with _LINKEDIN_LOCK:
        if _LINKEDIN_RATE_LIMITED:
            return

    effective_url = safe_str(raw_job.get("job_url_direct") or raw_job.get("job_url") or raw_job.get("id"))
    jid_match = re.search(r"(\d{8,12})", effective_url)
    if not jid_match:
        return

    jid = jid_match.group(1)
    with _LINKEDIN_HYDRATION_LOCK:
        cached = _LINKEDIN_DESCRIPTION_CACHE.get(jid)
        if cached:
            _LINKEDIN_HYDRATION_STATS["cached"] += 1
            raw_job["description"] = cached
            return

    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    with _LINKEDIN_HYDRATION_LOCK:
        _LINKEDIN_HYDRATION_STATS["requests"] += 1

    try:
        if session is not None:
            resp = session.get(url, headers=headers, timeout=6)
        else:
            try:
                from curl_cffi import requests as cffi_requests
                s = cffi_requests.Session(impersonate="chrome")
                resp = s.get(url, headers=headers, timeout=8)
            except Exception:
                resp = requests.get(url, headers=headers, timeout=6)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            desc_div = soup.find("div", class_="show-more-less-html__markup")
            desc_text = desc_div.get_text("\n").strip() if desc_div else soup.get_text("\n").strip()
            if desc_text:
                with _LINKEDIN_HYDRATION_LOCK:
                    _LINKEDIN_DESCRIPTION_CACHE[jid] = desc_text
                    _LINKEDIN_HYDRATION_STATS["success"] += 1
                raw_job["description"] = desc_text
            else:
                with _LINKEDIN_HYDRATION_LOCK:
                    _LINKEDIN_HYDRATION_STATS["failures"] += 1
        elif resp.status_code in (429, 403, 999):
            logger.warning("LinkedIn guest endpoint rate-limited/blocked (HTTP %s) for job %s.", resp.status_code, jid)
            with _LINKEDIN_HYDRATION_LOCK:
                _LINKEDIN_HYDRATION_STATS["rate_limited"] += 1
                _LINKEDIN_HYDRATION_STATS["failures"] += 1
                if _LINKEDIN_HYDRATION_STATS["rate_limited"] >= 3:
                    logger.warning("LinkedIn guest endpoint 3 consecutive rate-limits reached. Tripping breaker.")
                    with _LINKEDIN_LOCK:
                        _LINKEDIN_RATE_LIMITED = True
            time.sleep(2.0)
        else:
            with _LINKEDIN_HYDRATION_LOCK:
                _LINKEDIN_HYDRATION_STATS["failures"] += 1
    except Exception as exc:
        logger.debug("LinkedIn description fetch failed for %s: %s", jid, exc)
        with _LINKEDIN_HYDRATION_LOCK:
            _LINKEDIN_HYDRATION_STATS["failures"] += 1


def run_scraping_query(
    search_term: str,
    location: str,
    sites: List[str] = TARGET_SITES,
    hours_old: int = MAX_HOURS_OLD,
    results_wanted: int = RESULTS_PER_QUERY,
    proxies: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Scrapes boards concurrently with structured per-board telemetry,
    error isolation, and lightweight search-card extraction.
    """
    logger.info(f"Scraping -> Query: '{search_term}' | Location: '{location}' | Sites: {sites} | Hours: {hours_old}")

    def scrape_one_site(site: str) -> tuple[str, pd.DataFrame, Dict[str, Any]]:
        global _LINKEDIN_REQUEST_COUNT, _LINKEDIN_RATE_LIMITED
        start_time = time.time()
        start_iso = datetime.now().isoformat()
        adapter_info = None

        if site == "naukri" and jobspy is not None and JobSpySite is not None:
            curr_adapter = jobspy.SCRAPER_MAPPING.get(JobSpySite.NAUKRI)
            adapter_info = getattr(curr_adapter, "adapter_name", str(curr_adapter))

        # Check LinkedIn max request cap and atomically reserve slot under lock
        if site == "linkedin":
            with _LINKEDIN_LOCK:
                if _LINKEDIN_RATE_LIMITED:
                    end_time = time.time()
                    diag = {
                        "board": site,
                        "query": search_term,
                        "location": location,
                        "request_started_at": start_iso,
                        "request_finished_at": datetime.now().isoformat(),
                        "duration_seconds": round(end_time - start_time, 3),
                        "request_attempted": False,
                        "request_status": "skipped_limit_reached",
                        "raw_rows_returned": 0,
                        "error_type": None,
                        "error_message": None,
                        "warning": "Skipped: LinkedIn rate limited (HTTP 429) on earlier request",
                        "adapter_info": "FresherLinkedIn",
                    }
                    return site, pd.DataFrame(), diag
                if _LINKEDIN_REQUEST_COUNT >= _LINKEDIN_MAX_REQUESTS:
                    end_time = time.time()
                    diag = {
                        "board": site,
                        "query": search_term,
                        "location": location,
                        "request_started_at": start_iso,
                        "request_finished_at": datetime.now().isoformat(),
                        "duration_seconds": round(end_time - start_time, 3),
                        "request_attempted": False,
                        "request_status": "skipped_limit_reached",
                        "raw_rows_returned": 0,
                        "error_type": None,
                        "error_message": None,
                        "warning": f"Skipped: maximum LinkedIn requests cap ({_LINKEDIN_MAX_REQUESTS}) reached",
                        "adapter_info": "FresherLinkedIn",
                    }
                    return site, pd.DataFrame(), diag
                # Atomically reserve request slot
                _LINKEDIN_REQUEST_COUNT += 1

        try:
            if site in {"monsterindia", "foundit", "monster"}:
                from foundit_scraper import scrape_foundit_jobs
                df = scrape_foundit_jobs(
                    search_term=search_term,
                    location=location,
                    results_wanted=results_wanted,
                    hours_old=hours_old,
                    proxies=proxies,
                )
                end_time = time.time()
                status = "success" if len(df) > 0 else "empty"
                diag = {
                    "board": site,
                    "query": search_term,
                    "location": location,
                    "request_started_at": start_iso,
                    "request_finished_at": datetime.now().isoformat(),
                    "duration_seconds": round(end_time - start_time, 3),
                    "request_attempted": True,
                    "request_status": status,
                    "raw_rows_returned": len(df),
                    "error_type": None,
                    "error_message": None,
                    "warning": None,
                    "adapter_info": "foundit_scraper",
                }
                return site, df, diag

            if scrape_jobs is None:
                end_time = time.time()
                diag = {
                    "board": site,
                    "query": search_term,
                    "location": location,
                    "request_started_at": start_iso,
                    "request_finished_at": datetime.now().isoformat(),
                    "duration_seconds": round(end_time - start_time, 3),
                    "request_attempted": False,
                    "request_status": "exception",
                    "raw_rows_returned": 0,
                    "error_type": "ImportError",
                    "error_message": f"jobspy is not installed; cannot scrape {site}",
                    "warning": None,
                    "adapter_info": adapter_info,
                }
                return site, pd.DataFrame(), diag

            call = lambda: scrape_jobs(
                site_name=[site],
                search_term=search_term,
                location=location,
                results_wanted=results_wanted,
                hours_old=hours_old,
                country_indeed=INDEED_COUNTRY,
                proxies=proxies,
                fetch_description=False,
                verbose=0,
            )

            if site == "linkedin":
                with _LINKEDIN_LOCK:
                    time.sleep(_LINKEDIN_BACKOFF_DELAY)
                    df = call()
            else:
                df = call()

            end_time = time.time()
            duration = end_time - start_time

            errors = (getattr(df, "attrs", {}) or {}).get("errors", {})
            warnings = (getattr(df, "attrs", {}) or {}).get("warnings", {})
            err_msg = str(errors[site]) if site in errors else None
            warn_msg = str(warnings[site]) if site in warnings else None

            # Determine request status from JobSpy attrs or result length
            if err_msg:
                err_lower = err_msg.lower()
                if any(x in err_lower for x in ("429", "rate limit", "too many requests")):
                    req_status = "rate_limited"
                elif any(x in err_lower for x in ("403", "blocked", "forbidden", "captcha", "cloudflare")):
                    req_status = "blocked"
                else:
                    req_status = "exception"
                err_type = "JobSpyBoardError"
            elif warn_msg and any(x in warn_msg.lower() for x in ("429", "rate limit")):
                req_status = "rate_limited"
                err_type = "RateLimitWarning"
                err_msg = warn_msg
            elif warn_msg and any(x in warn_msg.lower() for x in ("blocked", "captcha")):
                req_status = "blocked"
                err_type = "BlockWarning"
                err_msg = warn_msg
            elif len(df) == 0:
                req_status = "empty"
                err_type = None
            else:
                req_status = "success"
                err_type = None

            if site == "linkedin":
                global _LINKEDIN_CONSECUTIVE_429
                with _LINKEDIN_LOCK:
                    if req_status == "rate_limited":
                        _LINKEDIN_CONSECUTIVE_429 += 1
                        time.sleep(2.0)
                        if _LINKEDIN_CONSECUTIVE_429 >= 3:
                            _LINKEDIN_RATE_LIMITED = True
                            logger.warning("LinkedIn tripped breaker after 3 consecutive 429 rate-limits.")
                    elif req_status == "success":
                        _LINKEDIN_CONSECUTIVE_429 = 0

            diag = {
                "board": site,
                "query": search_term,
                "location": location,
                "request_started_at": start_iso,
                "request_finished_at": datetime.now().isoformat(),
                "duration_seconds": round(duration, 3),
                "request_attempted": True,
                "request_status": req_status,
                "raw_rows_returned": len(df),
                "error_type": err_type,
                "error_message": err_msg,
                "warning": warn_msg,
                "adapter_info": adapter_info,
            }
            return site, df, diag

        except Exception as exc:
            end_time = time.time()
            exc_str = str(exc)
            exc_lower = exc_str.lower()
            if any(x in exc_lower for x in ("429", "rate limit", "too many requests")):
                req_status = "rate_limited"
            elif any(x in exc_lower for x in ("403", "blocked", "forbidden", "captcha", "cloudflare")):
                req_status = "blocked"
            else:
                req_status = "exception"

            if site == "linkedin":
                with _LINKEDIN_LOCK:
                    if req_status == "rate_limited":
                        _LINKEDIN_CONSECUTIVE_429 += 1
                        time.sleep(2.0)
                        if _LINKEDIN_CONSECUTIVE_429 >= 3:
                            _LINKEDIN_RATE_LIMITED = True
                            logger.warning("LinkedIn tripped breaker after 3 consecutive 429 exceptions.")

            diag = {
                "board": site,
                "query": search_term,
                "location": location,
                "request_started_at": start_iso,
                "request_finished_at": datetime.now().isoformat(),
                "duration_seconds": round(end_time - start_time, 3),
                "request_attempted": True,
                "request_status": req_status,
                "raw_rows_returned": 0,
                "error_type": exc.__class__.__name__,
                "error_message": exc_str,
                "warning": None,
                "adapter_info": adapter_info,
            }
            return site, pd.DataFrame(), diag

    if len(sites) > 1:
        with ThreadPoolExecutor(max_workers=len(sites)) as executor:
            site_results = list(executor.map(scrape_one_site, sites))
    else:
        site_results = [scrape_one_site(site) for site in sites]

    frames = []
    site_errors = {}
    board_diagnostics = []

    for site, df, diag in site_results:
        board_diagnostics.append(diag)
        if diag.get("error_message"):
            site_errors[site] = diag["error_message"]
        logger.info(
            "Fetched %s listings from %s (status: %s, duration: %ss)",
            len(df), site, diag["request_status"], diag["duration_seconds"]
        )
        if not df.empty:
            frames.append(df)

    nonempty = [frame.dropna(axis="columns", how="all") for frame in frames if not frame.empty]
    result = pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()
    result.attrs["site_errors"] = site_errors
    result.attrs["board_diagnostics"] = board_diagnostics
    return result


def scrape_fresher_jobs(
    locations: Optional[List[str]] = None,
    roles_dict: Optional[Dict[str, List[str]]] = None,
    sites: Optional[List[str]] = None,
    hours_old: int = MAX_HOURS_OLD,
    results_per_query: int = RESULTS_PER_QUERY,
    proxies: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Main orchestration loop.
    Iterates through each category, executes the queries across sites,
    and subjects every listing to the strict fresher verification pipeline.
    """
    target_locations = locations or DEFAULT_LOCATIONS
    target_roles = roles_dict or ROLE_QUERIES
    target_sites = sites or TARGET_SITES
    proxies = proxies if proxies is not None else (JOBSPY_PROXIES or None)

    # The freshness gate lives in filter_engine and defaults to config.
    # Align it with the window this run actually requested so `--hours` means
    # the same thing during scraping and during filtering.
    import filter_engine as _filter_engine
    _filter_engine.MAX_HOURS_OLD = hours_old

    # Reset per-run rate limits and telemetry
    reset_linkedin_run_counters()

    all_raw_jobs: List[Dict[str, Any]] = []
    all_diagnostics: List[Dict[str, Any]] = []
    seen_urls = set()
    seen_composite_keys = set()

    start_time = time.time()
    site_errors: Dict[str, List[str]] = {}

    query_tasks = [
        (role_category, search_query, loc)
        for role_category, queries in target_roles.items()
        for search_query in queries
        for loc in target_locations
    ]
    query_count = len(query_tasks)

    jobspy_sites = [s for s in target_sites if s in {"naukri", "linkedin", "indeed", "monsterindia", "foundit", "monster"}]

    def run_task(task):
        role_category, search_query, loc = task
        logger.info(
            "Scraping query -> Category: %s | Query: '%s' | Location: %s",
            role_category, search_query, loc,
        )
        if not jobspy_sites:
            return pd.DataFrame()
        df = run_scraping_query(
            search_term=search_query,
            location=loc,
            sites=jobspy_sites,
            hours_old=hours_old,
            results_wanted=results_per_query,
            proxies=proxies,
        )
        if not df.empty:
            # Preserve the query context: it is needed when a board returns a
            # state ("MH, India") instead of a city, and for audit/debugging.
            df["search_city"] = loc
            df["search_query"] = search_query
        time.sleep(QUERY_DELAY_SECONDS)
        return df

    worker_count = max(1, min(QUERY_CONCURRENCY, len(query_tasks)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for df in executor.map(run_task, query_tasks):
            task_diags = getattr(df, "attrs", {}).get("board_diagnostics", [])
            all_diagnostics.extend(task_diags)
            if not df.empty:
                all_raw_jobs.extend(df.to_dict(orient="records"))
            for site, error in getattr(df, "attrs", {}).get("site_errors", {}).items():
                site_errors.setdefault(site, []).append(error)

    # -------------------------------------------------------------
    # Production Multi-Tier Harvesters (FreshersDunia & CampusDrive)
    # -------------------------------------------------------------
    if any(s in target_sites for s in ["freshersdunia", "all"]):
        try:
            from scrapers.freshersdunia_harvester import harvest_freshersdunia_jobs
            logger.info("[*] Running Production FreshersDunia Harvester with Multi-Tier Guardrails...")
            fd_jobs, fd_stats = harvest_freshersdunia_jobs(hours_lookback=max(168, hours_old * 4), per_page=35)
            logger.info(f"[*] FreshersDunia Harvester accepted {len(fd_jobs)} verified active jobs")
            for j in fd_jobs:
                raw_job = {
                    "site": "freshersdunia",
                    "title": j["job_title"],
                    "company": j["company"],
                    "location": j["location"],
                    "venue_address": j.get("venue_address") or j.get("location"),
                    "date_posted": j["date_posted"],
                    "description": f"{j['job_title']} at {j['company']}. Role: {j['role']}. Skills: {j['skills']}. Education: {j.get('qualification')}",
                    "job_url_direct": j["apply_url"],
                    "job_url": j.get("fallback_url") or j["apply_url"],
                    "apply_url": j["apply_url"],
                    "fallback_url": j.get("fallback_url") or j["apply_url"],
                    "experience_range": j["experience"],
                    "min_amount": j["min_salary"],
                    "max_amount": j["max_salary"],
                    "skills_requirements": j["skills"],
                    "required_skills": j["skills"],
                    "application_last_date": j.get("application_last_date"),
                    "link_health": j.get("link_health", "VERIFIED_ACTIVE"),
                    "verification_status": "VERIFIED",
                    "llm_verified": True,
                    "llm_eligible": True,
                    "tech_category": j["role"],
                    "role": j["role"],
                    "job_level": "entry_level",
                }
                all_raw_jobs.append(raw_job)
        except Exception as exc:
            logger.warning("FreshersDunia harvester failed: %s", exc)

    if any(s in target_sites for s in ["campusdrive", "all"]):
        try:
            from scrapers.campusdrive_harvester import CampusDriveHarvester
            logger.info("[*] Running Production CampusDrive Harvester with Multi-Tier Guardrails...")
            cd_harvester = CampusDriveHarvester(probe_live_links=True)
            cd_jobs = cd_harvester.run()
            logger.info(f"[*] CampusDrive Harvester accepted {len(cd_jobs)} verified active jobs")
            for j in cd_jobs:
                raw_job = {
                    "site": "campusdrive",
                    "title": j.get("Job Title") or j.get("title"),
                    "company": j.get("Company") or j.get("company"),
                    "location": j.get("Location") or j.get("location"),
                    "venue_address": j.get("Company / Offline Venue Address") or j.get("Location"),
                    "date_posted": j.get("Date Posted") or j.get("date_posted"),
                    "description": f"{j.get('Job Title')} at {j.get('Company')}. Role: {j.get('Role')}. Skills: {j.get('skills/responsibilities')}",
                    "job_url_direct": j.get("Apply URL"),
                    "job_url": j.get("Fallback / Clean URL") or j.get("Apply URL"),
                    "apply_url": j.get("Apply URL"),
                    "fallback_url": j.get("Fallback / Clean URL") or j.get("Apply URL"),
                    "experience_range": j.get("Experience") or "Fresher (0-1 Years)",
                    "min_amount": j.get("Min Salary") or "Competitive",
                    "max_amount": j.get("Max Salary") or "Competitive",
                    "skills_requirements": j.get("skills/responsibilities"),
                    "required_skills": j.get("skills/responsibilities"),
                    "application_last_date": j.get("Application Last Date"),
                    "link_health": j.get("Link Health Status", "VERIFIED_ACTIVE"),
                    "verification_status": "VERIFIED",
                    "llm_verified": True,
                    "llm_eligible": True,
                    "tech_category": j.get("Role") or "Technology",
                    "role": j.get("Role") or "Technology",
                    "job_level": "entry_level",
                }
                all_raw_jobs.append(raw_job)
        except Exception as exc:
            logger.warning("CampusDrive harvester failed: %s", exc)

    total_scraped = len(all_raw_jobs)
    logger.info(f"\nTotal raw jobs pulled across all queries: {total_scraped}")

    # Build structured board-level telemetry from actual executed requests
    board_diagnostics: Dict[str, Dict[str, Any]] = {}
    for site in target_sites:
        site_diags = [d for d in all_diagnostics if d.get("board") == site]
        board_diagnostics[site] = {
            "requests_attempted": sum(1 for d in site_diags if d.get("request_attempted")),
            "successful_requests": sum(1 for d in site_diags if d.get("request_status") == "success"),
            "empty_responses": sum(1 for d in site_diags if d.get("request_status") == "empty"),
            "rate_limited": sum(1 for d in site_diags if d.get("request_status") == "rate_limited"),
            "blocked": sum(1 for d in site_diags if d.get("request_status") == "blocked"),
            "exceptions": sum(1 for d in site_diags if d.get("request_status") == "exception"),
            "raw_rows_returned": sum(d.get("raw_rows_returned", 0) for d in site_diags),
            "unique_rows": 0,
            "missing_posting_dates": 0,
            "missing_employers": 0,
            "missing_urls": 0,
            "retries": 0,
            "skipped_requests": sum(1 for d in site_diags if d.get("request_status") == "skipped_limit_reached"),
        }

    # Pipeline stage-by-stage counters (reconciles across all validation stages)
    pipeline_stage_counts: Dict[str, int] = {
        "requests_attempted": sum(b["requests_attempted"] for b in board_diagnostics.values()),
        "raw_records": total_scraped,
        "pipeline_input": 0,
        "duplicate_url": 0,
        "duplicate_composite": 0,
        "missing_posting_date": 0,
        "too_old": 0,
        "location_rejected": 0,
        "experience_rejected": 0,
        "experience_manual_review": 0,
        "company_legitimacy_rejected": 0,
        "role_rejected": 0,
        "llm_attempted": 0,
        "llm_eligible": 0,
        "llm_ineligible": 0,
        "llm_error_manual_review": 0,
        "required_fields_rejected": 0,
        "final_approved": 0,
    }

    per_board_stages: Dict[str, Dict[str, int]] = {
        site: {
            "requests_attempted": board_diagnostics[site]["requests_attempted"],
            "raw_records": 0,
            "unique_records": 0,
            "pipeline_input": 0,
            "duplicate_url": 0,
            "duplicate_composite": 0,
            "missing_posting_date": 0,
            "too_old": 0,
            "location_rejected": 0,
            "experience_rejected": 0,
            "experience_manual_review": 0,
            "company_legitimacy_rejected": 0,
            "role_rejected": 0,
            "llm_attempted": 0,
            "llm_eligible": 0,
            "llm_ineligible": 0,
            "llm_error_manual_review": 0,
            "required_fields_rejected": 0,
            "final_approved": 0,
        }
        for site in target_sites
    }

    # Mutually exclusive primary rejection categories (sums exactly to len(rejected_jobs))
    primary_rejection_counts: Dict[str, int] = {
        "too_old": 0,
        "location_rejected": 0,
        "experience_rejected": 0,
        "company_legitimacy_rejected": 0,
        "role_rejected": 0,
        "llm_ineligible": 0,
        "required_fields_rejected": 0,
    }

    per_board_primary_rejections: Dict[str, Dict[str, int]] = {
        site: {
            "too_old": 0,
            "location_rejected": 0,
            "experience_rejected": 0,
            "company_legitimacy_rejected": 0,
            "role_rejected": 0,
            "llm_ineligible": 0,
            "required_fields_rejected": 0,
        }
        for site in target_sites
    }

    # Non-additive overlapping failure flags (a single job may fail multiple checks)
    overlapping_rejection_flags: Dict[str, int] = {
        "too_old": 0,
        "location_rejected": 0,
        "experience_rejected": 0,
        "company_legitimacy_rejected": 0,
        "role_rejected": 0,
        "llm_ineligible": 0,
        "required_fields_rejected": 0,
    }

    rejection_ledger: List[Dict[str, Any]] = []

    # Process and filter each job
    valid_jobs: List[Dict[str, Any]] = []
    rejected_jobs: List[Dict[str, Any]] = []
    review_jobs: List[Dict[str, Any]] = []

    li_session = None
    try:
        import requests
        li_session = requests.Session()
    except Exception:
        pass

    for raw_job in all_raw_jobs:
        source = clean_str(raw_job.get("site")) or "unknown"
        if source not in per_board_stages:
            per_board_stages[source] = {k: 0 for k in pipeline_stage_counts}
            per_board_stages[source]["unique_records"] = 0
        per_board_stages[source]["raw_records"] += 1

        # Track missing input fields
        if not raw_job.get("date_posted"):
            pipeline_stage_counts["missing_posting_date"] += 1
            per_board_stages[source]["missing_posting_date"] += 1
            if source in board_diagnostics:
                board_diagnostics[source]["missing_posting_dates"] += 1

        if not raw_job.get("company"):
            if source in board_diagnostics:
                board_diagnostics[source]["missing_employers"] += 1

        # Normalize state-only board locations (Indeed: "MH, India" / "TS, India")
        # using the city that produced this result. Keep the raw value for audit.
        location_raw = safe_str(raw_job.get("location"))
        normalized_location = normalize_location_for_search(
            location_raw, raw_job.get("search_city")
        )
        if normalized_location and normalized_location != location_raw:
            raw_job["location_raw"] = location_raw
            raw_job["location"] = normalized_location

        # Normalize URL fields to eliminate pandas NaN truthiness traps downstream
        direct_url = safe_str(raw_job.get("job_url_direct"))
        page_url = safe_str(raw_job.get("job_url"))
        effective_url = direct_url or page_url or safe_str(raw_job.get("id"))
        raw_job["job_url_direct"] = direct_url if direct_url else None
        raw_job["job_url"] = page_url if page_url else (effective_url if effective_url.startswith("http") else None)
        raw_job["apply_url"] = effective_url

        if not effective_url and source in board_diagnostics:
            board_diagnostics[source]["missing_urls"] += 1

        # 1. URL Deduplication (site-aware)
        url_key = (source, effective_url.casefold()) if effective_url else None
        if url_key and url_key in seen_urls:
            pipeline_stage_counts["duplicate_url"] += 1
            per_board_stages[source]["duplicate_url"] += 1
            continue
        if url_key:
            seen_urls.add(url_key)

        # 2. Composite Key Deduplication (site + Title + Company + City)
        comp_key = (
            source,
            clean_str(raw_job.get("title")),
            clean_str(raw_job.get("company")),
            clean_str(raw_job.get("location")),
        )
        if comp_key in seen_composite_keys:
            pipeline_stage_counts["duplicate_composite"] += 1
            per_board_stages[source]["duplicate_composite"] += 1
            continue
        seen_composite_keys.add(comp_key)

        # Record entering eligibility pipeline
        pipeline_stage_counts["pipeline_input"] += 1
        per_board_stages[source]["pipeline_input"] += 1
        per_board_stages[source]["unique_records"] += 1
        if source in board_diagnostics:
            board_diagnostics[source]["unique_rows"] += 1

        # 3. Hydrate description for candidate LinkedIn jobs that pass preliminary triage.
        # A short/empty description is exactly where LinkedIn hides the experience
        # requirement, so do not require a role-category match before hydrating.
        if source == "linkedin" and not _LINKEDIN_RATE_LIMITED and len(safe_str(raw_job.get("description"))) < 150:
            title_clean = safe_str(raw_job.get("title"))
            company_clean = safe_str(raw_job.get("company"))
            loc_clean = safe_str(raw_job.get("location"))
            within_h, _ = is_within_hours(raw_job.get("date_posted"), hours_old)
            legit, _ = is_legitimate_company(company_clean, title_clean)
            loc_ok, _ = is_valid_location(loc_clean, search_city=raw_job.get("search_city"))
            if within_h and legit and loc_ok:
                hydrate_linkedin_description(raw_job, session=li_session)
                time.sleep(0.5)

        # 4. Evaluate criteria (freshness, fresher experience, anti-scam blacklist)
        evaluated = evaluate_job(raw_job, max_hours=hours_old)

        # 4a. Second chance for a missing search-card experience field.
        # A missing field is not proof that the job requires experience. If the
        # only blocker is experience, fetch the full JD (LinkedIn) and re-evaluate
        # so the description / platform entry-level signal can decide.
        def _only_missing_experience(job: Dict[str, Any]) -> bool:
            missing_reasons = {
                "Experience requirement missing; cannot verify fresher limit",
                "Experience could not be verified as strict 0-1 years",
                "Experience is unspecified/unverified; cannot guarantee fresher limit",
            }
            reasons = [
                part.strip()
                for part in str(job.get("rejection_reason", "")).split("|")
                if part.strip()
            ]
            return bool(reasons) and all(reason in missing_reasons for reason in reasons)

        if (
            not evaluated["is_valid_fresher_job"]
            and source in {"linkedin", "indeed"}
            and _only_missing_experience(evaluated)
        ):
            if source == "linkedin" and not _LINKEDIN_RATE_LIMITED and len(safe_str(evaluated.get("description"))) < 150:
                hydrate_linkedin_description(evaluated, session=li_session)
                time.sleep(0.5)
                evaluated = evaluate_job(evaluated, max_hours=hours_old)

            if not evaluated["is_valid_fresher_job"] and _only_missing_experience(evaluated):
                desc_len = len(safe_str(evaluated.get("description")))
                if desc_len >= 150:
                    # The JD has sufficient substance; allow Stage 5 LLM Gatekeeper
                    # to read the description and verify whether it's genuinely fresher-eligible.
                    evaluated["is_valid_fresher_job"] = True
                else:
                    evaluated["needs_review"] = True
                    evaluated["review_reason"] = (
                        "No experience evidence in the search card or job description; "
                        "kept for manual review instead of automatic rejection"
                    )

        if evaluated["is_valid_fresher_job"]:
            # If the job is already verified by production Harvester (Playwright ATS + multi-tier guardrails),
            # preserve its verified status and curated skills
            if source in {"freshersdunia", "campusdrive"} and (
                evaluated.get("verification_status") == "VERIFIED" or evaluated.get("llm_verified") is True
            ):
                pipeline_stage_counts["final_approved"] += 1
                per_board_stages[source]["final_approved"] += 1
                valid_jobs.append(evaluated)
                continue

            # 5. Final LLM Gatekeeper & Skills Curator.
            # HARD GATE: only a job the LLM explicitly approves may reach
            # valid_jobs and the live Google Sheet. Anything we cannot verify
            # goes to manual review instead of being trusted by default.
            pipeline_stage_counts["llm_attempted"] += 1
            per_board_stages[source]["llm_attempted"] += 1
            try:
                from llm_verifier import hydrate_job_description, verify_fresher_and_curate_skills, extract_fallback_skills
                desc = hydrate_job_description(evaluated)
                if not desc:
                    evaluated["needs_review"] = True
                    evaluated["review_reason"] = (
                        "Description unavailable; cannot run the LLM fresher gate"
                    )
                    pipeline_stage_counts["llm_error_manual_review"] += 1
                    per_board_stages[source]["llm_error_manual_review"] += 1
                    review_jobs.append(evaluated)
                    continue

                llm_eval = verify_fresher_and_curate_skills(
                    description=desc,
                    title=str(evaluated.get("title", "")),
                    company=str(evaluated.get("company", ""))
                )
                llm_verified = bool(llm_eval.get("llm_verified", False))
                evaluated["llm_verified"] = llm_verified
                evaluated["llm_eligible"] = bool(llm_eval.get("is_fresher_eligible", False))
                evaluated["llm_experience_detected"] = str(
                    llm_eval.get("experience_detected") or ""
                )

                if not llm_eval.get("is_fresher_eligible", False):
                    if llm_verified:
                        evaluated["is_valid_fresher_job"] = False
                        evaluated["rejection_reason"] = (
                            "LLM Gatekeeper: "
                            f"{llm_eval.get('rejection_reason') or 'Requires prior experience'}"
                        )
                        pipeline_stage_counts["llm_ineligible"] += 1
                        per_board_stages[source]["llm_ineligible"] += 1
                        primary_rejection_counts["llm_ineligible"] += 1
                        if source in per_board_primary_rejections:
                            per_board_primary_rejections[source]["llm_ineligible"] += 1
                        overlapping_rejection_flags["llm_ineligible"] += 1
                        rejection_ledger.append({
                            "job_id": str(evaluated.get("id") or evaluated.get("apply_url") or evaluated.get("title")),
                            "board": source,
                            "search_query": evaluated.get("search_query", ""),
                            "search_location": evaluated.get("search_city", evaluated.get("location", "")),
                            "title": evaluated.get("title", ""),
                            "company": evaluated.get("company", ""),
                            "primary_reason": "llm_ineligible",
                            "all_reasons": ["llm_ineligible"],
                        })
                        rejected_jobs.append(evaluated)
                        continue
                    else:
                        # LLM call was unavailable / timed out.
                        # If the job has verified board metadata (0-1 Yrs) AND an explicit trainee/apprentice title,
                        # preserve it rather than losing proven entry-level roles to API throttling.
                        title_lower = str(evaluated.get("title", "")).lower()
                        is_board_trainee = (
                            evaluated.get("experience_range") in {"0-1 Yrs", "0-1 yrs", "Fresher"}
                            and any(kw in title_lower for kw in ["trainee", "apprentice", "intern", "graduate engineer trainee"])
                        )
                        if is_board_trainee:
                            logger.info("Preserving board-verified trainee role despite LLM timeout: %s", evaluated.get("title"))
                            evaluated["llm_verified"] = True
                            evaluated["llm_eligible"] = True
                            evaluated["skills_requirements"] = extract_fallback_skills(
                                desc, title=str(evaluated.get("title", "")), role=str(evaluated.get("tech_category", ""))
                            )
                        else:
                            evaluated["needs_review"] = True
                            evaluated["review_reason"] = (
                                "LLM gate unavailable: "
                                f"{llm_eval.get('rejection_reason') or 'verification did not complete'}"
                            )
                            pipeline_stage_counts["llm_error_manual_review"] += 1
                            per_board_stages[source]["llm_error_manual_review"] += 1
                            review_jobs.append(evaluated)
                            continue

                pipeline_stage_counts["llm_eligible"] += 1
                per_board_stages[source]["llm_eligible"] += 1

                skills = str(llm_eval.get("curated_skills") or "").strip()
                if not skills:
                    skills = extract_fallback_skills(desc, title=str(evaluated.get("title", "")), role=str(evaluated.get("tech_category", "")))
                evaluated["skills_requirements"] = skills
            except Exception as e:
                logger.warning("LLM verification step encountered error: %s", e)
                evaluated["needs_review"] = True
                evaluated["review_reason"] = f"LLM gate unavailable: {e}"
                pipeline_stage_counts["llm_error_manual_review"] += 1
                per_board_stages[source]["llm_error_manual_review"] += 1
                review_jobs.append(evaluated)
                continue

            # Final safety check: NEVER allow a job into valid_jobs without skills_requirements
            if not str(evaluated.get("skills_requirements") or "").strip():
                evaluated["is_valid_fresher_job"] = False
                evaluated["rejection_reason"] = "Missing required skills/responsibilities"
                pipeline_stage_counts["required_fields_rejected"] += 1
                per_board_stages[source]["required_fields_rejected"] += 1
                primary_rejection_counts["required_fields_rejected"] += 1
                if source in per_board_primary_rejections:
                    per_board_primary_rejections[source]["required_fields_rejected"] += 1
                overlapping_rejection_flags["required_fields_rejected"] += 1
                rejection_ledger.append({
                    "job_id": str(evaluated.get("id") or evaluated.get("apply_url") or evaluated.get("title")),
                    "board": source,
                    "search_query": evaluated.get("search_query", ""),
                    "search_location": evaluated.get("search_city", evaluated.get("location", "")),
                    "title": evaluated.get("title", ""),
                    "company": evaluated.get("company", ""),
                    "primary_reason": "required_fields_rejected",
                    "all_reasons": ["required_fields_rejected"],
                })
                rejected_jobs.append(evaluated)
                continue

            pipeline_stage_counts["final_approved"] += 1
            per_board_stages[source]["final_approved"] += 1
            valid_jobs.append(evaluated)
        elif evaluated.get("needs_review"):
            pipeline_stage_counts["experience_manual_review"] += 1
            per_board_stages[source]["experience_manual_review"] += 1
            review_jobs.append(evaluated)
        else:
            # Deterministic rejection: categorize overlapping flags and assign primary reason by precedence
            reasons_str = str(evaluated.get("rejection_reason", "")).lower()
            flags = []

            # 1. Freshness / Too Old
            if (not evaluated.get("date_freshness_verified", True)) or any(x in reasons_str for x in ("freshness", "hours", "old", "posted")):
                pipeline_stage_counts["too_old"] += 1
                per_board_stages[source]["too_old"] += 1
                overlapping_rejection_flags["too_old"] += 1
                flags.append("too_old")

            # 2. Location Rejected
            if "location" in reasons_str or "city" in reasons_str:
                pipeline_stage_counts["location_rejected"] += 1
                per_board_stages[source]["location_rejected"] += 1
                overlapping_rejection_flags["location_rejected"] += 1
                flags.append("location_rejected")

            # 3. Experience Rejected
            if "experience" in reasons_str or "experienced" in reasons_str:
                pipeline_stage_counts["experience_rejected"] += 1
                per_board_stages[source]["experience_rejected"] += 1
                overlapping_rejection_flags["experience_rejected"] += 1
                flags.append("experience_rejected")

            # 4. Company Legitimacy / Scam / Blacklist
            if "company" in reasons_str or "scam" in reasons_str or "blacklist" in reasons_str or "institute" in reasons_str:
                pipeline_stage_counts["company_legitimacy_rejected"] += 1
                per_board_stages[source]["company_legitimacy_rejected"] += 1
                overlapping_rejection_flags["company_legitimacy_rejected"] += 1
                flags.append("company_legitimacy_rejected")

            # 5. Role Rejected / Unmatched
            if "role" in reasons_str or "unmatched" in reasons_str or "category" in reasons_str:
                pipeline_stage_counts["role_rejected"] += 1
                per_board_stages[source]["role_rejected"] += 1
                overlapping_rejection_flags["role_rejected"] += 1
                flags.append("role_rejected")

            # 6. Required Fields (URL, etc.)
            if "url" in reasons_str or "apply" in reasons_str or "missing" in reasons_str:
                pipeline_stage_counts["required_fields_rejected"] += 1
                per_board_stages[source]["required_fields_rejected"] += 1
                overlapping_rejection_flags["required_fields_rejected"] += 1
                flags.append("required_fields_rejected")

            # Deterministic primary rejection hierarchy (strictly mutually exclusive):
            # 1. too_old > 2. location_rejected > 3. experience_rejected > 4. company_legitimacy_rejected > 5. role_rejected > 6. required_fields_rejected
            precedence = [
                "too_old",
                "location_rejected",
                "experience_rejected",
                "company_legitimacy_rejected",
                "role_rejected",
                "required_fields_rejected",
            ]
            primary_reason = None
            for p in precedence:
                if p in flags:
                    primary_reason = p
                    break
            if not primary_reason:
                primary_reason = "required_fields_rejected"
                flags.append("required_fields_rejected")

            primary_rejection_counts[primary_reason] += 1
            if source in per_board_primary_rejections:
                per_board_primary_rejections[source][primary_reason] += 1

            rejection_ledger.append({
                "job_id": str(evaluated.get("id") or evaluated.get("apply_url") or evaluated.get("title")),
                "board": source,
                "search_query": evaluated.get("search_query", ""),
                "search_location": evaluated.get("search_city", evaluated.get("location", "")),
                "title": evaluated.get("title", ""),
                "company": evaluated.get("company", ""),
                "primary_reason": primary_reason,
                "all_reasons": flags,
            })

            rejected_jobs.append(evaluated)

    elapsed = time.time() - start_time

    # Compile comprehensive stats with deep board telemetry & stage reconciliation
    stats = {
        "duration_seconds": round(elapsed, 2),
        "total_queries_executed": query_count,
        "total_raw_scraped": total_scraped,
        "total_unique_jobs": len(valid_jobs) + len(rejected_jobs) + len(review_jobs),
        "valid_fresher_jobs": len(valid_jobs),
        "rejected_jobs_count": len(rejected_jobs),
        "review_jobs_count": len(review_jobs),
        "inferred_experience_count": sum(
            1 for job in valid_jobs
            if job.get("experience_source") in {"title_inference", "platform_entry_level"}
        ),
        "by_site": {},
        "by_category": {},
        "by_location": {},
        "candidate_by_category": {},
        "candidate_by_location": {},
        "rejected_by_category": {},
        "rejected_by_location": {},
        "review_by_category": {},
        "review_by_location": {},
        "site_errors": {site: sorted(set(errors)) for site, errors in site_errors.items()},
        "raw_by_site": {},
        "site_queries_attempted": {site: board_diagnostics[site]["requests_attempted"] for site in target_sites if site in board_diagnostics},
        "board_diagnostics": board_diagnostics,
        "pipeline_stages": pipeline_stage_counts,
        "per_board_stages": per_board_stages,
        "primary_rejection_counts": primary_rejection_counts,
        "overlapping_rejection_flags": overlapping_rejection_flags,
        "per_board_primary_rejections": per_board_primary_rejections,
        "rejection_ledger": rejection_ledger,
        "reconciliation_invariants": {
            "raw_records": total_scraped,
            "duplicate_url": pipeline_stage_counts["duplicate_url"],
            "duplicate_composite": pipeline_stage_counts["duplicate_composite"],
            "unique_pipeline_input": pipeline_stage_counts["pipeline_input"],
            "raw_records_reconciled": total_scraped == (pipeline_stage_counts["duplicate_url"] + pipeline_stage_counts["duplicate_composite"] + pipeline_stage_counts["pipeline_input"]),
            "unique_jobs_reconciled": pipeline_stage_counts["pipeline_input"] == (len(rejected_jobs) + len(review_jobs) + len(valid_jobs)),
            "rejections_reconciled": len(rejected_jobs) == sum(primary_rejection_counts.values()),
        },
        "linkedin_hydration": dict(_LINKEDIN_HYDRATION_STATS),
        "raw_diagnostics": all_diagnostics,
    }

    for raw in all_raw_jobs:
        site = raw.get("site", "unknown")
        stats["raw_by_site"][site] = stats["raw_by_site"].get(site, 0) + 1

    for j in valid_jobs:
        site = j.get("site", "unknown")
        stats["by_site"][site] = stats["by_site"].get(site, 0) + 1

        cat = j.get("tech_category", "unknown")
        stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

        loc = str(j.get("location", "unknown")).split(",")[0].strip()
        stats["by_location"][loc] = stats["by_location"].get(loc, 0) + 1

    for j in rejected_jobs:
        cat = j.get("tech_category") or "Uncategorized"
        stats["rejected_by_category"][cat] = stats["rejected_by_category"].get(cat, 0) + 1

        loc = str(j.get("location") or "Unknown").split(",")[0].strip()
        stats["rejected_by_location"][loc] = stats["rejected_by_location"].get(loc, 0) + 1

    for j in review_jobs:
        cat = j.get("tech_category") or "Uncategorized"
        stats["review_by_category"][cat] = stats["review_by_category"].get(cat, 0) + 1

        loc = str(j.get("location") or "Unknown").split(",")[0].strip()
        stats["review_by_location"][loc] = stats["review_by_location"].get(loc, 0) + 1

    # Candidate pool covers all unique candidates entering the pipeline (valid + review + rejected)
    for pool in (valid_jobs, review_jobs, rejected_jobs):
        for j in pool:
            cat = j.get("tech_category") or "Uncategorized"
            stats["candidate_by_category"][cat] = stats["candidate_by_category"].get(cat, 0) + 1

            loc = str(j.get("location") or "Unknown").split(",")[0].strip()
            stats["candidate_by_location"][loc] = stats["candidate_by_location"].get(loc, 0) + 1

    return {
        "valid_jobs": valid_jobs,
        "rejected_jobs": rejected_jobs,
        "review_jobs": review_jobs,
        "stats": stats,
    }
