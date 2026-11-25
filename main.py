"""
Fresher Job Scraper - Master CLI Automation
============================================
Command-Line Interface for executing the multi-board scraper.
Exports verified fresh (<48h) fresher jobs to CSV and JSON formats.

Usage:
  python main.py
  python main.py --quick
  python main.py --hours 48 --locations Mumbai Hyderabad
  python main.py --roles "Data Analytics" "MIS Executive"
"""

import os
import sys
import json
import shutil
import argparse
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

# Ensure UTF-8 output in Windows cmd / powershell
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

from config import (
    MAX_HOURS_OLD,
    TARGET_SITES,
    DEFAULT_LOCATIONS,
    ROLE_QUERIES,
    RESULTS_PER_QUERY,
)
from scraper import scrape_fresher_jobs
from hr_enricher import process_hr_enrichment
from history_store import HistoryStore
from google_sheets_sync import sync_configured_google_sheet, get_existing_sheet_job_urls
from excel_exporter import export_to_excel
from core.run_status import RunReport, build_report_from_stats, OUTCOME_SUCCESS, OUTCOME_NO_JOBS
from normalization.canonical_job import deduplicate, to_canonical


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape verified fresher jobs (<48h) from Naukri, LinkedIn, and Indeed (100% Free)."
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=MAX_HOURS_OLD,
        help=f"Max job age in hours (default: {MAX_HOURS_OLD})",
    )
    parser.add_argument(
        "--locations",
        nargs="+",
        default=DEFAULT_LOCATIONS,
        help="List of target cities (e.g., --locations Mumbai Hyderabad Bangalore)",
    )
    parser.add_argument(
        "--sites",
        nargs="+",
        default=TARGET_SITES,
        help="Target job sites (e.g., --sites naukri linkedin indeed freshersdunia campusdrive)",
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        default=None,
        help="Specific role categories to scrape (e.g., --roles 'Data Analytics' 'Web Development & Full Stack')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=RESULTS_PER_QUERY,
        help=f"Results per search query (default: {RESULTS_PER_QUERY})",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory to save output CSV and JSON files (default: output)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick run mode: scrapes 1 query per role with small limit for testing",
    )
    parser.add_argument(
        "--with-interview-docs",
        dest="with_interview_docs",
        action="store_true",
        default=True,
        help="Generate student-friendly interview prep PDFs and upload to Google Drive (default: True)",
    )
    parser.add_argument(
        "--no-interview-docs",
        dest="with_interview_docs",
        action="store_false",
        help="Disable interview prep generation and Drive upload",
    )
    parser.add_argument(
        "--diagnostic-only",
        action="store_true",
        help="Diagnostic-only mode: runs scraping, filtering, and telemetry persistence, but skips Google Sheets sync and Drive upload.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Resolve output directory relative to script location if relative path given
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = args.output_dir if os.path.isabs(args.output_dir) else os.path.join(script_dir, args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Determine role queries to use
    selected_roles = {}
    if args.roles:
        for r in args.roles:
            matched_key = next((k for k in ROLE_QUERIES if k.lower() == r.lower()), None)
            if matched_key:
                selected_roles[matched_key] = ROLE_QUERIES[matched_key]
            else:
                selected_roles[r] = [r]
    else:
        selected_roles = ROLE_QUERIES

    # Quick test mode adjustments
    results_limit = args.limit
    if args.quick:
        print("[*] Running in QUICK test mode (1 query per role, limit=5)")
        selected_roles = {k: [v[0]] for k, v in selected_roles.items()}
        results_limit = 5

    print("\n" + "=" * 70)
    print("FRESHER JOB INTELLIGENCE SCRAPER (NAUKRI + LINKEDIN + INDEED)")
    print("=" * 70)
    print(f" • Max Job Age:       Last {args.hours} hours strictly")
    print(f" • Target Cities:      {', '.join(args.locations)}")
    print(f" • Target Sites:       {', '.join(args.sites)}")
    print(f" • Role Categories:    {', '.join(selected_roles.keys())}")
    print(f" • Results per query:  {results_limit}")
    print("=" * 70 + "\n")

    # Pre-load existing Sheet1 URLs so already-synced jobs skip redundant hydration & LLM calls
    known_synced_urls = set()
    if not getattr(args, "diagnostic_only", False):
        known_synced_urls = get_existing_sheet_job_urls()
        if known_synced_urls:
            print(f"[*] Pre-loaded {len(known_synced_urls)} existing Sheet1 URLs for early deduplication.")

    # Run scraper
    results = scrape_fresher_jobs(
        locations=args.locations,
        roles_dict=selected_roles,
        sites=args.sites,
        hours_old=args.hours,
        results_per_query=results_limit,
        known_synced_urls=known_synced_urls or None,
    )

    valid_jobs = results["valid_jobs"]
    rejected_jobs = results["rejected_jobs"]
    review_jobs = results.get("review_jobs", [])
    stats = results["stats"]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Track History and Identify Brand New Jobs (Zero Duplicate Broadcasts)
    history = HistoryStore(os.path.join(output_dir, "pipeline_history.db"))
    new_jobs, already_seen_count = history.filter_new_jobs(valid_jobs)

    # Save only the newly discovered jobs for Student Notifications
    new_jobs_json = os.path.join(output_dir, "new_fresher_jobs_latest.json")
    with open(new_jobs_json, "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, indent=2, default=str)

    print(f"\n[*] History Cache: {len(new_jobs)} brand new jobs, {already_seen_count} already seen in prior runs.")

    # Jobs with no usable experience evidence are kept for manual review,
    # not silently thrown away as if they were experienced roles.
    review_jobs_json = os.path.join(output_dir, "review_jobs_latest.json")
    with open(review_jobs_json, "w", encoding="utf-8") as f:
        json.dump(review_jobs, f, indent=2, default=str)
    if review_jobs:
        print(f"[*] {len(review_jobs)} jobs need manual review (missing experience evidence) -> {review_jobs_json}")

    hr_leads = []

    # 2. Save Valid Fresher Jobs to CSV and JSON
    if valid_jobs:
        df_valid = pd.DataFrame(valid_jobs)

        # Reorder columns for clean reading
        priority_cols = [
            "site", "tech_category", "title", "company", "location", "venue_address",
            "date_posted", "experience_range", "experience_source", "verification_status",
            "llm_verified", "llm_eligible", "llm_experience_detected",
            "min_amount", "max_amount",
            "eligible_passout_years", "required_skills", "prior_experience_required", "job_requirement",
            "job_url_direct", "job_url", "apply_url", "fallback_url", "link_health", "application_last_date", "emails", "quality_score"
        ]
        existing_priority = [c for c in priority_cols if c in df_valid.columns]
        other_cols = [c for c in df_valid.columns if c not in priority_cols]
        df_valid = df_valid[existing_priority + other_cols]

        csv_path = os.path.join(output_dir, f"fresher_jobs_{timestamp}.csv")
        json_path = os.path.join(output_dir, f"fresher_jobs_{timestamp}.json")
        xlsx_path = os.path.join(output_dir, f"fresher_jobs_{timestamp}.xlsx")
        latest_csv = os.path.join(output_dir, "fresher_jobs_latest.csv")
        latest_json = os.path.join(output_dir, "fresher_jobs_latest.json")
        latest_xlsx = os.path.join(output_dir, "fresher_jobs_latest.xlsx")

        # Export CSV
        df_valid.to_csv(csv_path, index=False, encoding="utf-8-sig")
        shutil.copy2(csv_path, latest_csv)

        # Export JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(valid_jobs, f, indent=2, default=str)
        shutil.copy2(json_path, latest_json)

        # 2. Enrich Hiring Companies with HR Contacts for Telecalling Team
        hr_leads = process_hr_enrichment(valid_jobs)
        hr_json_path = os.path.join(output_dir, f"hr_leads_{timestamp}.json")
        latest_hr_json = os.path.join(output_dir, "hr_leads_latest.json")
        new_hr_json = os.path.join(output_dir, "new_hr_contacts_latest.json")
        
        # Canonical schema for n8n and Postgres sync
        canonical_hr = []
        for h in hr_leads:
            canonical_hr.append({
                "company": h.get("company", ""),
                "job_title": h.get("job_title", ""),
                "hr_name": "Talent Acquisition Lead",
                "hr_email": h.get("hr_email", ""),
                "email_source": h.get("hr_source", "domain_pattern"),
                "hunter_status": "VALID" if h.get("hr_email") else "UNVERIFIED",
                "mx_record_valid": True if h.get("hr_email") else False,
                "linkedin_search_url": h.get("linkedin_hr_search", ""),
                "google_call_search_url": h.get("phone_search", "")
            })

        with open(hr_json_path, "w", encoding="utf-8") as f:
            json.dump(hr_leads, f, indent=2, default=str)
        with open(latest_hr_json, "w", encoding="utf-8") as f:
            json.dump(hr_leads, f, indent=2, default=str)
        with open(new_hr_json, "w", encoding="utf-8") as f:
            json.dump(canonical_hr, f, indent=2, default=str)

        # 3. Export Formatted Multi-Sheet Excel Workbook (Jobs + HR Leads + Summary + Rejected)
        export_to_excel(df_valid, rejected_jobs, stats, xlsx_path, hr_leads=hr_leads)
        shutil.copy2(xlsx_path, latest_xlsx)

        print(f"\n[+] Saved {len(valid_jobs)} verified fresher jobs to:")
        print(f"    - Excel: {xlsx_path}")
        print(f"    - Excel (latest): {latest_xlsx}")
        print(f"    - CSV:   {csv_path}")
        print(f"    - JSON:  {json_path}")
        print(f"    - HR Leads JSON: {latest_hr_json} ({len(hr_leads)} companies)")
    else:
        # Always refresh latest artifacts so a zero-result run cannot leave
        # yesterday's jobs appearing current.
        empty = pd.DataFrame(columns=[
            "site", "tech_category", "title", "company", "location", "date_posted",
            "experience_range", "eligible_passout_years", "required_skills",
            "prior_experience_required", "job_requirement", "job_url_direct", "job_url",
        ])
        empty.to_csv(os.path.join(output_dir, "fresher_jobs_latest.csv"), index=False, encoding="utf-8-sig")
        with open(os.path.join(output_dir, "fresher_jobs_latest.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        export_to_excel(empty, rejected_jobs, stats, os.path.join(output_dir, "fresher_jobs_latest.xlsx"), hr_leads=[])
        with open(os.path.join(output_dir, "hr_leads_latest.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        with open(os.path.join(output_dir, "new_hr_contacts_latest.json"), "w", encoding="utf-8") as f:
            json.dump([], f)
        print("\n[!] No jobs passed the strict fresher/freshness criteria in this cycle.")

    # 2a. Write run report + canonical job dedup evidence
    report = build_report_from_stats(
        stats,
        started_at=stats.get("started_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    report_dir = Path(output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report.write(report_dir, stem="run_report")
    # Export canonical deduped jobs for downstream pipelines (n8n, Postgres)
    if valid_jobs:
        canonical_unique, dup_count = deduplicate(valid_jobs)
        canonical_path = report_dir / "canonical_jobs_latest.json"
        canonical_path.write_text(
            json.dumps(canonical_unique, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        canonical_path = report_dir / "canonical_jobs_latest.json"
        canonical_path.write_text("[]", encoding="utf-8")

    # Replace the "no jobs passed" console message with the headline from the
    # report so the UI is consistent with the machine-readable evidence.
    if not valid_jobs and report.outcome == OUTCOME_NO_JOBS:
        print(f"\n[!] {report.headline().split('—')[1].strip()}")

    # 2a. Upsert this run's jobs into the live sheet FIRST so verified jobs are never lost to timeouts.
    newly_synced_jobs = []
    if getattr(args, "diagnostic_only", False):
        print("\n[✓] Diagnostic-only mode active: Google Sheets sync was completely skipped.")
        synced = None
        sync_failed = False
    else:
        synced = sync_configured_google_sheet(
            valid_jobs,
            hr_leads=hr_leads,
            newly_added_out=newly_synced_jobs,
        )
        sync_failed = synced is False
        if sync_failed:
            print("[!] Google Sheets sync did not complete; local exports are still available.")

    # 2b. Generate Interview Preparation PDFs & Google Drive links, then patch Column M in Sheet1
    if getattr(args, "with_interview_docs", True) and not getattr(args, "diagnostic_only", False):
        try:
            from interview_prep.runner import run_interview_docs
            interview_dir = os.path.join(output_dir, "interview_docs")
            prep_stats = None
            if valid_jobs:
                print("\n[*] Generating Interview Prep Documents & Google Drive links for verified fresher jobs...")
                prep_stats = run_interview_docs(valid_jobs, output_base_dir=interview_dir, sync_sheet=True)
                print(
                    f"[✓] Interview Prep: {prep_stats['generated']} generated, "
                    f"{prep_stats['cached']} cached, {prep_stats['failed']} failed."
                )
            # Skip redundant backfill retry when Pass 1 failed 100% (e.g., LLM outage)
            llm_totally_failing = (
                prep_stats is not None
                and prep_stats.get("generated", 0) == 0
                and prep_stats.get("cached", 0) == 0
                and prep_stats.get("failed", 0) > 0
            )
            if llm_totally_failing:
                print("[*] Skipping Pending Backfill: Pass 1 failed on all jobs (avoiding duplicate LLM retries).")
            else:
                print("[*] Checking Google Sheet for any remaining 'Pending Generation' rows to backfill...")
                backfill_stats = run_interview_docs(
                    from_sheet=True,
                    pending_only=True,
                    limit=20,
                    output_base_dir=interview_dir,
                    sync_sheet=True,
                )
                if backfill_stats["total_jobs"] > 0:
                    print(
                        f"[✓] Pending Backfill: {backfill_stats['generated']} generated, "
                        f"{backfill_stats['cached']} cached, {backfill_stats['failed']} failed."
                    )
        except Exception as exc:
            print(f"[!] Interview prep generation encountered an error: {exc}")

    # 2c. Send Brevo Dynamic Job Alert Digest for genuinely newly added Sheet1 rows
    if synced is True and newly_synced_jobs and not getattr(args, "diagnostic_only", False):
        try:
            from brevo_notifier import send_job_alert_digest
            brevo_res = send_job_alert_digest(newly_synced_jobs)
            if brevo_res.get("sent"):
                print(
                    f"[✓] Brevo Alert: Sent {brevo_res.get('jobs_count')} new job(s) "
                    f"to {brevo_res.get('recipients')} student(s) ({brevo_res.get('batches')} batch(es))."
                )
            else:
                print(
                    f"[*] Brevo Alert status: {brevo_res.get('reason')} "
                    f"({brevo_res.get('errors') or brevo_res.get('error') or 'skipped'})"
                )
        except Exception as exc:
            print(f"[!] Brevo alert notification encountered an error: {exc}")
    elif synced is True and not newly_synced_jobs:
        print("[*] Brevo Alert skipped: 0 brand-new jobs added to Google Sheets in this run.")

    # 2. Save Rejected Jobs Log (for transparency and audit)
    if rejected_jobs:
        rejected_json = os.path.join(output_dir, "rejected_jobs_latest.json")
        with open(rejected_json, "w", encoding="utf-8") as f:
            json.dump(rejected_jobs, f, indent=2, default=str)
        print(f"[*] Saved {len(rejected_jobs)} rejected jobs log to: {rejected_json}")

    # 3. Print Summary Stats
    print("\n" + "=" * 70)
    print(" SCRAPING RUN SUMMARY")
    print("=" * 70)
    print(f" Total Duration:          {stats['duration_seconds']} seconds")
    print(f" Total Raw Listings:      {stats['total_raw_scraped']}")
    print(f" Unique Jobs Deduplicated: {stats['total_unique_jobs']}")
    print(f" ✅ Verified Fresher Jobs: {stats['valid_fresher_jobs']}")
    print(f" ⚠️  Needs Manual Review:  {stats.get('review_jobs_count', 0)}")
    print(f" ❌ Rejected (Filtered):  {stats['rejected_jobs_count']}")
    if stats.get("inferred_experience_count"):
        print(f" ℹ️  Experience inferred from platform/JD context: {stats['inferred_experience_count']}")

    print("\n Breakdown by Platform:")
    for site in sorted(
        set(stats.get("raw_by_site", {}))
        | set(stats["by_site"])
        | set(stats.get("site_errors", {}))
        | set(stats.get("site_queries_attempted", {}))
    ):
        fetched = stats.get("raw_by_site", {}).get(site, 0)
        kept = stats["by_site"].get(site, 0)
        attempts = stats.get("site_queries_attempted", {}).get(site, 0)
        print(f"   • {site.capitalize()}: {attempts} query/location calls; fetched {fetched}, verified {kept}")
        for error in stats.get("site_errors", {}).get(site, []):
            print(f"       scraper error: {error}")

    print("\n Breakdown by Role Category:")
    for cat, count in stats["by_category"].items():
        print(f"   • {cat}: {count}")

    print("\n Breakdown by Location:")
    for loc, count in stats["by_location"].items():
        print(f"   • {loc}: {count}")

    print("=" * 70)

    # Print top 5 sample matches
    if valid_jobs:
        print("\n ⭐ SAMPLE VERIFIED FRESHER JOBS:")
        for idx, j in enumerate(valid_jobs[:5], 1):
            url = j.get("apply_url") or j.get("job_url_direct") or j.get("job_url")
            print(f"\n [{idx}] {j.get('title')} @ {j.get('company')}")
            print(f"     Source: {j.get('site')} | Role: {j.get('tech_category')} | City: {j.get('location')}")
            print(f"     Posted: {j.get('date_posted')} | Experience: {j.get('experience_range') or 'Fresher'}")
            print(f"     Apply URL: {url}")
        print("\n" + "=" * 70)

    # Surface non-zero exit code only for genuine infrastructure failures.
    if report and report.has_infrastructure_failure:
        raise SystemExit(report.exit_code)


if __name__ == "__main__":
    main()