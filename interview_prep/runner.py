"""Orchestration and execution runner for interview prep documents.

Processes verified fresher jobs (from JSON or Google Sheet) into clean,
subtle, student-friendly interview prep PDFs.

Features:
- Cache keying by job URL + skills + version (skips regeneration if already up-to-date)
- Fail-closed error handling (never outputs corrupt/broken PDFs or crashes the batch)
- Question context gathering via polite public web search
- LLM curation into 12-18 validated questions
- Minimal A4 PDF rendering
- Google Drive upload integration placeholders
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from interview_prep.curator import (
    PACK_VERSION,
    CuratorError,
    build_interview_pack,
)
from interview_prep.drive import sheet_doc_cell, upload_pdf
from interview_prep.pdf_renderer import output_dir_for, render_interview_pdf, _slug
from interview_prep.sources import gather_question_context

logger = logging.getLogger("interview_prep.runner")


def compute_job_cache_key(job: Dict[str, Any]) -> str:
    """Computes a SHA-256 cache hash from job identity, skills, and curation version."""
    url = str(job.get("apply_url") or job.get("job_url_direct") or job.get("job_url") or "").strip().lower()
    skills = str(job.get("skills_requirements") or job.get("required_skills") or job.get("skills") or "").strip().lower()
    company = str(job.get("company") or "").strip().lower()
    title = str(job.get("title") or "").strip().lower()
    payload = f"{url}|{skills}|{company}|{title}|{PACK_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_jobs_from_json(json_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Loads a list of job dicts from a local JSON file."""
    path = Path(json_path)
    if not path.exists():
        logger.warning("Jobs JSON file not found: %s", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning("Expected list of jobs in %s, got %s", path, type(data))
        return []
    except Exception as exc:
        logger.error("Error reading jobs from %s: %s", path, exc)
        return []


def load_jobs_from_sheet(
    spreadsheet_id: Optional[str] = None,
    credentials_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Loads verified fresher jobs directly from the Google Sheet."""
    sid = spreadsheet_id or os.getenv("GOOGLE_SPREADSHEET_ID")
    if not sid:
        logger.error("No Google Spreadsheet ID configured (GOOGLE_SPREADSHEET_ID).")
        return []

    cred_path = credentials_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "credentials.json"
    if not os.path.isabs(cred_path):
        cred_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), cred_path)

    if not os.path.exists(cred_path):
        logger.error("Google credentials file not found: %s", cred_path)
        return []

    try:
        import gspread
        from google.oauth2.service_account import Credentials
        from google_sheets_sync import _get_jobs_worksheet, _find_jobs_header_row

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sid)
        ws = _get_jobs_worksheet(spreadsheet)
        header_row = _find_jobs_header_row(ws) or 3
        data_start_row = header_row + 1

        all_values = ws.get(f"A{data_start_row}:M")
        jobs: List[Dict[str, Any]] = []
        for row in all_values:
            if not row or len(row) < 9:
                continue
            title = str(row[0] or "").strip()
            company = str(row[1] or "").strip()
            location = str(row[2] or "").strip()
            category = str(row[3] or "").strip() if len(row) > 3 else ""
            date_p = str(row[4] or "").strip() if len(row) > 4 else ""
            exp = str(row[5] or "").strip() if len(row) > 5 else ""
            min_sal = row[6] if len(row) > 6 else ""
            max_sal = row[7] if len(row) > 7 else ""
            apply_url = str(row[8] or "").strip() if len(row) > 8 else ""
            source = str(row[9] or "").strip() if len(row) > 9 else ""
            skills = str(row[11] or "").strip() if len(row) > 11 else ""
            doc_url = str(row[12] or "").strip() if len(row) > 12 else ""

            if not title or not company:
                continue

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "tech_category": category,
                "date_posted": date_p,
                "experience_range": exp,
                "min_amount": min_sal,
                "max_amount": max_sal,
                "apply_url": apply_url,
                "site": source.lower(),
                "skills_requirements": skills,
                "interview_doc_url": doc_url,
            })

        logger.info("Loaded %d rows from Google Sheet tab '%s'", len(jobs), ws.title)
        return jobs
    except Exception as exc:
        logger.error("Failed loading jobs from Google Sheet: %s", exc)
        return []


def run_interview_docs(
    jobs: Optional[List[Dict[str, Any]]] = None,
    output_base_dir: Optional[Union[str, Path]] = None,
    from_sheet: bool = False,
    company_filter: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
    sync_sheet: bool = False,
    llm: Optional[Any] = None,
) -> Dict[str, Any]:
    """Runs the interview prep document generator for verified fresher jobs.

    Args:
        jobs: List of job dicts. If None and not from_sheet, loads from output/fresher_jobs_latest.json.
        output_base_dir: Root directory for output documents (defaults to output/interview_docs).
        from_sheet: If True, pulls verified jobs from the configured Google Sheet.
        company_filter: Optional substring to filter jobs by company name.
        limit: Max number of jobs to process.
        force: If True, regenerates docs even if cache matches.
        sync_sheet: If True and Drive links are produced, syncs to Google Sheet.
        llm: Optional pre-configured LLM instance. Defaults to llm_verifier.get_llm().

    Returns:
        Summary dict containing counts and generated document metadata.
    """
    root_dir = Path(__file__).resolve().parent.parent
    if output_base_dir is None:
        base_dir = root_dir / "output" / "interview_docs"
    else:
        base_dir = Path(output_base_dir)
        if not base_dir.is_absolute():
            base_dir = root_dir / base_dir
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Acquire target jobs
    if from_sheet:
        job_list = load_jobs_from_sheet()
    elif jobs is not None:
        job_list = list(jobs)
    else:
        default_json = root_dir / "output" / "fresher_jobs_latest.json"
        job_list = load_jobs_from_json(default_json)

    # 2. Filter by company if requested
    if company_filter:
        c_filter = company_filter.strip().casefold()
        job_list = [
            j for j in job_list
            if c_filter in str(j.get("company", "")).casefold()
        ]

    # 3. Apply limit
    if limit and limit > 0:
        job_list = job_list[:limit]

    stats: Dict[str, Any] = {
        "total_jobs": len(job_list),
        "processed": 0,
        "generated": 0,
        "cached": 0,
        "failed": 0,
        "docs": [],
    }

    if not job_list:
        logger.info("No jobs to process for interview preparation documents.")
        return stats

    # 4. Resolve LLM client
    active_llm = llm
    if active_llm is None:
        try:
            from llm_verifier import get_llm
            active_llm = get_llm()
        except Exception as exc:
            logger.warning("Could not initialize LLM from llm_verifier: %s", exc)

    logger.info(
        "Starting Interview Prep Generation for %d job(s). Output: %s (force=%s)",
        len(job_list), base_dir, force,
    )

    # 5. Process each job
    for idx, job in enumerate(job_list, 1):
        company = str(job.get("company") or "").strip()
        role = str(job.get("tech_category") or job.get("title") or "").strip()
        title = str(job.get("title") or "").strip()
        skills = str(
            job.get("skills_requirements")
            or job.get("required_skills")
            or job.get("skills")
            or ""
        ).strip()

        if not company or not title:
            logger.warning("[%d/%d] Skipping job with missing title or company: %s", idx, len(job_list), job)
            stats["failed"] += 1
            continue

        if not skills or len(skills) < 3:
            logger.warning("[%d/%d] Skipping %s @ %s: No skills captured for question prep.", idx, len(job_list), title, company)
            stats["failed"] += 1
            continue

        job_dir = output_dir_for(base_dir, company, role)
        job_dir.mkdir(parents=True, exist_ok=True)

        pdf_filename = f"{_slug(company)}_{_slug(role)}_Interview_Prep.pdf"
        pdf_path = job_dir / pdf_filename
        meta_path = job_dir / "meta.json"
        questions_path = job_dir / "questions.json"

        cache_key = compute_job_cache_key(job)

        # Check Cache
        if not force and pdf_path.exists() and meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    saved_meta = json.load(f)
                if saved_meta.get("cache_key") == cache_key:
                    logger.info(
                        "[%d/%d] Using cached interview prep for %s @ %s",
                        idx, len(job_list), role, company,
                    )
                    stats["cached"] += 1
                    stats["docs"].append({
                        "company": company,
                        "role": role,
                        "title": title,
                        "pdf_path": str(pdf_path),
                        "status": "cached",
                        "drive_url": saved_meta.get("drive_url"),
                    })
                    continue
            except Exception as e:
                logger.debug("Failed reading cache metadata for %s: %s", company, e)

        # Generate fresh interview pack
        logger.info("[%d/%d] Generating interview prep for %s @ %s...", idx, len(job_list), role, company)
        stats["processed"] += 1

        # A. Sourcing question context from web
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]
        try:
            context = gather_question_context(company, role, skill_list)
        except Exception as exc:
            logger.warning("Context gathering failed for %s @ %s: %s", role, company, exc)
            context = {"company_excerpts": [], "role_excerpts": [], "skill_excerpts": [], "sources": []}

        # B. LLM Curation (fail-closed)
        if active_llm is None:
            logger.error("No LLM available for interview prep curation; skipping %s @ %s.", role, company)
            stats["failed"] += 1
            continue

        try:
            pack = build_interview_pack(job, context, active_llm)
        except CuratorError as ce:
            logger.warning("Curator validation failed for %s @ %s (fail-closed): %s", role, company, ce)
            stats["failed"] += 1
            continue
        except Exception as exc:
            logger.error("Unexpected curation error for %s @ %s: %s", role, company, exc)
            stats["failed"] += 1
            continue

        # C. Save questions.json
        try:
            full_pack_data = {
                "job": {
                    "title": title,
                    "company": company,
                    "role": role,
                    "location": job.get("location"),
                    "site": job.get("site"),
                    "apply_url": job.get("apply_url") or job.get("job_url_direct") or job.get("job_url"),
                    "skills": skills,
                },
                "pack": pack,
                "sources": context.get("sources", []),
            }
            with open(questions_path, "w", encoding="utf-8") as f:
                json.dump(full_pack_data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed saving questions.json for %s: %s", company, exc)

        # D. Render A4 PDF
        prepared_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            render_interview_pdf(job, pack, pdf_path, prepared_at)
        except Exception as exc:
            logger.error("PDF rendering failed for %s @ %s: %s", role, company, exc)
            stats["failed"] += 1
            continue

        # E. Google Drive upload (placeholder)
        drive_res = upload_pdf(pdf_path)
        drive_url = drive_res.get("drive_url")
        if drive_url:
            job["interview_doc_url"] = drive_url

        # F. Save meta.json
        meta = {
            "cache_key": cache_key,
            "company": company,
            "role": role,
            "title": title,
            "apply_url": str(job.get("apply_url") or job.get("job_url_direct") or job.get("job_url") or ""),
            "skills": skills,
            "prepared_at": prepared_at,
            "pdf_path": str(pdf_path),
            "questions_count": len(pack.get("questions") or []),
            "more_coding_count": len(pack.get("more_coding_questions") or []),
            "drive_status": drive_res.get("drive_status"),
            "drive_url": drive_url,
        }
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as exc:
            logger.warning("Failed saving meta.json for %s: %s", company, exc)

        stats["generated"] += 1
        stats["docs"].append({
            "company": company,
            "role": role,
            "title": title,
            "pdf_path": str(pdf_path),
            "status": "generated",
            "drive_url": drive_url,
            "questions_count": len(pack.get("questions") or []),
        })

    logger.info(
        "Interview Prep Run Complete: %d generated, %d cached, %d failed out of %d jobs.",
        stats["generated"], stats["cached"], stats["failed"], stats["total_jobs"],
    )
    return stats
