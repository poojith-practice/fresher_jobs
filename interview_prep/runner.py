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
import threading
from concurrent.futures import ThreadPoolExecutor
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


def sync_interview_docs_to_sheet(
    jobs_with_docs: List[Dict[str, Any]],
    spreadsheet_id: Optional[str] = None,
    credentials_path: Optional[str] = None,
) -> int:
    """Batch-updates Column M ('Interview QnA doc') in Sheet1 for jobs that now have Drive URLs."""
    updates_by_url: Dict[str, str] = {}
    updates_by_key: Dict[tuple, str] = {}
    for j in jobs_with_docs:
        doc_url = str(j.get("interview_doc_url") or "").strip()
        if not doc_url.startswith("http"):
            continue
        apply_url = str(j.get("apply_url") or j.get("job_url_direct") or j.get("job_url") or "").strip().casefold()
        if apply_url:
            updates_by_url[apply_url] = doc_url
        key = (
            str(j.get("title") or "").strip().casefold(),
            str(j.get("company") or "").strip().casefold(),
        )
        if all(key):
            updates_by_key[key] = doc_url

    if not updates_by_url and not updates_by_key:
        return 0

    if spreadsheet_id:
        sids = [spreadsheet_id]
    else:
        from google_sheets_sync import get_configured_spreadsheet_ids
        sids = get_configured_spreadsheet_ids()
    if not sids:
        logger.warning("Cannot sync interview docs to sheet: GOOGLE_SPREADSHEET_ID not set.")
        return 0

    cred_path = credentials_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "credentials.json"
    if not os.path.isabs(cred_path):
        cred_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), cred_path)
    if not os.path.exists(cred_path):
        logger.warning("Cannot sync interview docs to sheet: credentials not found at %s", cred_path)
        return 0

    total_updated = 0
    for sid in sids:
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
            batch_cells = []
            for offset, row in enumerate(all_values):
                row_num = data_start_row + offset
                title = str(row[0] or "").strip().casefold() if len(row) > 0 else ""
                company = str(row[1] or "").strip().casefold() if len(row) > 1 else ""
                apply_url = str(row[8] or "").strip().casefold() if len(row) > 8 else ""
                existing_doc = str(row[12] or "").strip() if len(row) > 12 else ""

                if existing_doc.startswith("http"):
                    continue

                new_url = updates_by_url.get(apply_url) or updates_by_key.get((title, company))
                if new_url:
                    batch_cells.append({"range": f"M{row_num}", "values": [[new_url]]})

            if batch_cells:
                ws.batch_update(batch_cells, value_input_option="USER_ENTERED")
                logger.info("[✓] Updated %d 'Interview QnA doc' link(s) in Google Sheet '%s' (%s).", len(batch_cells), ws.title, sid)
                total_updated += len(batch_cells)
        except Exception as exc:
            logger.error("Failed syncing interview doc links to Google Sheet %s: %s", sid, exc)
    return total_updated


def run_interview_docs(
    jobs: Optional[List[Dict[str, Any]]] = None,
    output_base_dir: Optional[Union[str, Path]] = None,
    from_sheet: bool = False,
    company_filter: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
    sync_sheet: bool = False,
    llm: Optional[Any] = None,
    pending_only: bool = False,
    max_workers: int = 3,
) -> Dict[str, Any]:
    """Runs the interview prep document generator for verified fresher jobs.

    Args:
        jobs: List of job dicts. If None and not from_sheet, loads from output/fresher_jobs_latest.json.
        output_base_dir: Root directory for output documents (defaults to output/interview_docs).
        from_sheet: If True, pulls verified jobs from the configured Google Sheet.
        company_filter: Optional substring to filter jobs by company name.
        limit: Max number of jobs to process.
        force: If True, regenerates docs even if cache matches.
        sync_sheet: If True and Drive links are produced, syncs Column M to Google Sheet.
        llm: Optional pre-configured LLM instance. Defaults to llm_verifier.get_llm().
        pending_only: If True, skips jobs that already have an http(s) interview_doc_url.
        max_workers: Concurrent worker threads for context gathering, curation, and upload.

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

    # 2. Filter by company or pending status if requested
    if company_filter:
        c_filter = company_filter.strip().casefold()
        job_list = [
            j for j in job_list
            if c_filter in str(j.get("company", "")).casefold()
        ]

    if pending_only:
        job_list = [
            j for j in job_list
            if not str(j.get("interview_doc_url") or "").strip().startswith("http")
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

    stats_lock = threading.Lock()
    total_jobs = len(job_list)

    # 5. Process each job (concurrently when max_workers > 1)
    def _process_one(item: tuple) -> None:
        idx, job = item
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
            logger.warning("[%d/%d] Skipping job with missing title or company: %s", idx, total_jobs, job)
            with stats_lock:
                stats["failed"] += 1
            return

        if not skills or len(skills) < 3:
            logger.warning("[%d/%d] Skipping %s @ %s: No skills captured for question prep.", idx, total_jobs, title, company)
            with stats_lock:
                stats["failed"] += 1
            return

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
                    existing_drive_url = saved_meta.get("drive_url")
                    if not existing_drive_url:
                        drive_res = upload_pdf(pdf_path)
                        existing_drive_url = drive_res.get("drive_url")
                        if existing_drive_url:
                            saved_meta["drive_url"] = existing_drive_url
                            saved_meta["drive_file_id"] = drive_res.get("drive_file_id")
                            with open(meta_path, "w", encoding="utf-8") as f:
                                json.dump(saved_meta, f, indent=2)
                    logger.info(
                        "[%d/%d] Using cached interview prep for %s @ %s (Drive: %s)",
                        idx, total_jobs, role, company, existing_drive_url or "none",
                    )
                    if existing_drive_url:
                        job["interview_doc_url"] = existing_drive_url
                    with stats_lock:
                        stats["cached"] += 1
                        stats["docs"].append({
                            "company": company,
                            "role": role,
                            "title": title,
                            "pdf_path": str(pdf_path),
                            "status": "cached",
                            "drive_url": existing_drive_url,
                        })
                    return
            except Exception as e:
                logger.debug("Failed reading cache metadata for %s: %s", company, e)

        if active_llm is None:
            logger.error("[%d/%d] No LLM available for interview prep curation; skipping %s @ %s.", idx, total_jobs, role, company)
            with stats_lock:
                stats["failed"] += 1
            return

        # Generate fresh interview pack
        logger.info("[%d/%d] Generating interview prep for %s @ %s...", idx, total_jobs, role, company)
        with stats_lock:
            stats["processed"] += 1

        # A. Sourcing question context from web
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]
        try:
            context = gather_question_context(company, role, skill_list)
        except Exception as exc:
            logger.warning("Context gathering failed for %s @ %s: %s", role, company, exc)
            context = {"company_excerpts": [], "role_excerpts": [], "skill_excerpts": [], "sources": []}

        # B. LLM Curation (fail-closed)
        try:
            pack = build_interview_pack(job, context, active_llm)
        except CuratorError as ce:
            logger.warning("Curator validation failed for %s @ %s (fail-closed): %s", role, company, ce)
            with stats_lock:
                stats["failed"] += 1
            return
        except Exception as exc:
            logger.error("Unexpected curation error for %s @ %s: %s", role, company, exc)
            with stats_lock:
                stats["failed"] += 1
            return

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
            with stats_lock:
                stats["failed"] += 1
            return

        # E. Google Drive upload
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

        with stats_lock:
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

    worker_count = max(1, min(max_workers, total_jobs))
    if worker_count == 1:
        for item in enumerate(job_list, 1):
            _process_one(item)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(_process_one, enumerate(job_list, 1)))

    if sync_sheet:
        updated_rows = sync_interview_docs_to_sheet(job_list)
        stats["sheet_rows_updated"] = updated_rows

    logger.info(
        "Interview Prep Run Complete: %d generated, %d cached, %d failed out of %d jobs.",
        stats["generated"], stats["cached"], stats["failed"], stats["total_jobs"],
    )
    return stats
