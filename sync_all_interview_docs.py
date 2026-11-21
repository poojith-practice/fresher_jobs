"""
Production Synchronizer: Generate and Sync Interview QnA Docs for All Google Sheet Rows
========================================================================================
Finds all rows in Google Sheet 'Sheet1' with an empty Column M ('Interview QnA doc'),
generates high-quality research-backed interview prep PDFs, uploads them to Google Drive
via the configured Apps Script Web App, and populates Column M with the shareable links.

Optimizations:
- Groups rows by unique (Company, Role) so identical postings (e.g. Delight HR) only
  generate once and update all corresponding rows immediately.
- Leverages local cache and existing PDFs whenever available.
- Incremental live Google Sheet cell updates so progress is saved as it runs.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import gspread
from dotenv import load_dotenv

# Ensure production root is on sys.path
PROD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROD_DIR))
load_dotenv(PROD_DIR / ".env")

from interview_prep.curator import build_interview_pack, CuratorError
from interview_prep.drive import drive_configured, upload_pdf
from interview_prep.pdf_renderer import output_dir_for, render_interview_pdf, _slug
from interview_prep.runner import compute_job_cache_key
from interview_prep.sources import gather_question_context
from llm_verifier import get_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("SyncAllInterviewDocs")

SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "1RikU9Gtm7Kx96-jARPj7xnnNTKoN5Y3GhFuT9nJudWs")
CREDENTIALS_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(PROD_DIR / "credentials.json"))
if not os.path.isabs(CREDENTIALS_PATH):
    CREDENTIALS_PATH = str(PROD_DIR / CREDENTIALS_PATH)

OUTPUT_BASE_DIR = PROD_DIR / "output" / "interview_docs"
OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)


def run():
    logger.info("=" * 75)
    logger.info(" 🚀 PRODUCTION INTERVIEW QnA DOC GENERATOR & GOOGLE DRIVE SYNC")
    logger.info("=" * 75)

    if not drive_configured():
        logger.error("Google Drive upload is not configured. Check GDRIVE_UPLOAD_URL.")
        return

    logger.info("Initializing LLM client pool (Groq / OpenRouter)...")
    llm = get_llm()
    if not llm:
        logger.error("No active LLM available. Check GROQ_API_KEY or OPENROUTER_API_KEY.")
        return

    logger.info("Connecting to Google Sheets...")
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    ss = gc.open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet("Sheet1")

    all_values = ws.get_all_values()
    headers = all_values[0]
    total_data_rows = len(all_values) - 1
    logger.info(f"Loaded {total_data_rows} total rows from Sheet1.")

    # Identify empty Column M rows
    pending_jobs = []
    for r_idx, row in enumerate(all_values[1:], start=2):
        col_m = row[12] if len(row) > 12 else ""
        if not col_m.strip():
            job = {
                "_row_num": r_idx,
                "title": row[0] if len(row) > 0 else "",
                "company": row[1] if len(row) > 1 else "",
                "location": row[2] if len(row) > 2 else "",
                "role": row[3] if len(row) > 3 else "",
                "tech_category": row[3] if len(row) > 3 else "",
                "date_posted": row[4] if len(row) > 4 else "",
                "experience": row[5] if len(row) > 5 else "",
                "min_salary": row[6] if len(row) > 6 else "",
                "max_salary": row[7] if len(row) > 7 else "",
                "apply_url": row[8] if len(row) > 8 else "",
                "source": row[9] if len(row) > 9 else "",
                "skills": row[11] if len(row) > 11 else "",
                "skills_requirements": row[11] if len(row) > 11 else "",
            }
            pending_jobs.append(job)

    logger.info(f"Found {len(pending_jobs)} rows with empty Column M ('Interview QnA doc').")
    if not pending_jobs:
        logger.info("[✓] All rows already have Interview QnA docs linked. Nothing to do!")
        return

    # Group by unique (company_clean, role_clean)
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for j in pending_jobs:
        c_clean = j["company"].strip().casefold()
        r_clean = j["role"].strip().casefold()
        key = (c_clean, r_clean)
        groups.setdefault(key, []).append(j)

    logger.info(f"Grouped into {len(groups)} unique (Company, Role) pairs to process.")

    processed_groups = 0
    updated_rows_count = 0
    failed_groups = 0

    # Also check fallback coverage_lab output for any existing PDFs we can harvest immediately
    fallback_lab_docs = PROD_DIR.parent / "fresher_job_scraper_coverage_lab" / "output" / "interview_docs_test"

    for (c_clean, r_clean), job_batch in groups.items():
        processed_groups += 1
        rep_job = job_batch[0]
        company = rep_job["company"]
        role = rep_job["role"]
        title = rep_job["title"]
        skills = rep_job["skills"] or "Python, Problem Solving, Data Structures"
        row_numbers = [j["_row_num"] for j in job_batch]

        logger.info("-" * 75)
        logger.info(
            f"[{processed_groups}/{len(groups)}] Processing: {company} | {role} "
            f"(Applies to {len(job_batch)} row(s): {row_numbers})"
        )

        job_dir = output_dir_for(OUTPUT_BASE_DIR, company, role)
        job_dir.mkdir(parents=True, exist_ok=True)
        pdf_filename = f"{_slug(company)}_{_slug(role)}_Interview_Prep.pdf"
        pdf_path = job_dir / pdf_filename
        meta_path = job_dir / "meta.json"
        questions_path = job_dir / "questions.json"
        cache_key = compute_job_cache_key(rep_job)

        drive_url = None

        # 1. Check existing output directory
        if pdf_path.exists() and meta_path.exists():
            try:
                import json
                with open(meta_path, "r", encoding="utf-8") as f:
                    saved_meta = json.load(f)
                if saved_meta.get("drive_url"):
                    drive_url = saved_meta.get("drive_url")
                    logger.info(f"  [CACHE HIT] Found existing Drive URL: {drive_url}")
                else:
                    logger.info("  [CACHE HIT] PDF exists locally, uploading to Drive...")
                    drive_res = upload_pdf(pdf_path)
                    drive_url = drive_res.get("drive_url")
                    if drive_url:
                        saved_meta["drive_url"] = drive_url
                        saved_meta["drive_file_id"] = drive_res.get("drive_file_id")
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump(saved_meta, f, indent=2)
            except Exception as e:
                logger.warning(f"  Failed reading cache meta: {e}")

        # 2. Check coverage lab test output if still needed
        if not drive_url and fallback_lab_docs.exists():
            for lab_dir in fallback_lab_docs.iterdir():
                if lab_dir.is_dir() and _slug(company).lower() in lab_dir.name.lower():
                    lab_pdf = next(lab_dir.glob("*.pdf"), None)
                    lab_meta = lab_dir / "meta.json"
                    if lab_pdf and lab_meta.exists():
                        try:
                            import json
                            with open(lab_meta, "r", encoding="utf-8") as f:
                                meta_data = json.load(f)
                            if meta_data.get("drive_url"):
                                drive_url = meta_data.get("drive_url")
                                logger.info(f"  [REUSED FROM LAB] Found Drive URL: {drive_url}")
                                break
                        except Exception:
                            pass

        # 3. Generate fresh document if not available
        if not drive_url:
            # Sourcing context
            skill_list = [s.strip() for s in skills.split(",") if s.strip()]
            try:
                context = gather_question_context(company, role, skill_list)
            except Exception as exc:
                logger.warning(f"  Context gathering failed for {company}: {exc}")
                context = {"company_excerpts": [], "role_excerpts": [], "skill_excerpts": [], "sources": []}

            # LLM curation
            try:
                pack = build_interview_pack(rep_job, context, llm)
            except CuratorError as ce:
                logger.warning(f"  Curator validation failed for {company} (fail-closed): {ce}")
                failed_groups += 1
                continue
            except Exception as exc:
                logger.error(f"  Unexpected curation error for {company}: {exc}")
                failed_groups += 1
                continue

            if not pack or not pack.get("questions"):
                logger.warning(f"  Curator returned empty questions for {company}; skipping.")
                failed_groups += 1
                continue

            # Save questions.json
            import json
            try:
                full_pack_data = {
                    "job": {
                        "title": title,
                        "company": company,
                        "role": role,
                        "location": rep_job.get("location"),
                        "apply_url": rep_job.get("apply_url"),
                        "skills": skills,
                    },
                    "pack": pack,
                    "sources": context.get("sources", []),
                }
                with open(questions_path, "w", encoding="utf-8") as f:
                    json.dump(full_pack_data, f, indent=2, ensure_ascii=False)
            except Exception as exc:
                logger.warning(f"  Failed saving questions.json: {exc}")

            # Render PDF
            prepared_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                render_interview_pdf(rep_job, pack, pdf_path, prepared_at)
                logger.info(f"  Rendered PDF: {pdf_path.name} ({len(pack.get('questions', []))} questions)")
            except Exception as exc:
                logger.error(f"  PDF rendering failed for {company}: {exc}")
                failed_groups += 1
                continue

            # Upload to Google Drive via Apps Script
            drive_res = upload_pdf(pdf_path)
            drive_url = drive_res.get("drive_url")
            if not drive_url:
                logger.error(f"  Drive upload failed for {company}; skipping sheet update.")
                failed_groups += 1
                continue

            # Save meta.json
            meta = {
                "cache_key": cache_key,
                "company": company,
                "role": role,
                "title": title,
                "apply_url": rep_job.get("apply_url"),
                "skills": skills,
                "prepared_at": prepared_at,
                "pdf_path": str(pdf_path),
                "questions_count": len(pack.get("questions") or []),
                "drive_url": drive_url,
                "drive_file_id": drive_res.get("drive_file_id"),
            }
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception:
                pass

        # 4. Live update Google Sheet with dynamic row verification (immune to row shifts/deletions)
        if drive_url:
            current_sheet_vals = ws.get_all_values()
            for r_num in row_numbers:
                target_idx = None
                if r_num <= len(current_sheet_vals):
                    actual_row = current_sheet_vals[r_num - 1]
                    actual_comp = actual_row[1] if len(actual_row) > 1 else ""
                    if actual_comp.strip().casefold() == c_clean:
                        target_idx = r_num

                # If row shifted due to row additions or deletions, scan dynamically
                if not target_idx:
                    for s_idx, s_row in enumerate(current_sheet_vals[1:], start=2):
                        s_comp = s_row[1] if len(s_row) > 1 else ""
                        s_role = s_row[3] if len(s_row) > 3 else ""
                        if s_comp.strip().casefold() == c_clean and s_role.strip().casefold() == r_clean:
                            target_idx = s_idx
                            break

                if target_idx:
                    cell_ref = f"M{target_idx}"
                    try:
                        ws.update_acell(cell_ref, drive_url)
                        updated_rows_count += 1
                        logger.info(f"  [✓] Updated Sheet1 {cell_ref} -> {drive_url}")
                    except Exception as g_err:
                        logger.error(f"  Failed updating Sheet1 {cell_ref}: {g_err}")
                else:
                    logger.warning(f"  Could not locate matching row in Sheet1 for {company} | {role}")

        # Polite throttle between unique company jobs
        time.sleep(1.0)

    logger.info("=" * 75)
    logger.info(" 🏁 BATCH SYNC COMPLETE")
    logger.info("=" * 75)
    logger.info(f" Unique Groups Processed: {processed_groups}")
    logger.info(f" Total Rows Updated:     {updated_rows_count} / {len(pending_jobs)}")
    logger.info(f" Failed Groups:          {failed_groups}")
    logger.info("=" * 75)


if __name__ == "__main__":
    run()
