"""CLI tool for generating student-friendly interview prep PDFs.

Builds subtle, professional A4 interview-preparation PDF guides for verified
fresher jobs with concise, bullet-pointed answers and real-world examples.

Usage:
  # Generate prep docs for latest verified jobs (cached automatically)
  python generate_interview_docs.py

  # Generate prep docs directly from live Google Sheet verified jobs
  python generate_interview_docs.py --from-sheet

  # Generate for a specific company only
  python generate_interview_docs.py --company "Natraj Roadways"

  # Force re-generation (bypass cache)
  python generate_interview_docs.py --force --limit 3
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# Ensure UTF-8 console output in Windows cmd / powershell
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from interview_prep.runner import load_jobs_from_json, run_interview_docs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("generate_interview_docs")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate clean, subtle interview-preparation PDFs for verified fresher jobs."
    )
    parser.add_argument(
        "--from-sheet",
        action="store_true",
        help="Pull verified fresher jobs directly from the configured Google Sheet.",
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Path to custom jobs JSON file (default: output/fresher_jobs_latest.json).",
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Filter jobs by company name substring (case-insensitive).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to process.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate PDFs even if an up-to-date cached version exists.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/interview_docs",
        help="Output base directory for interview docs (default: output/interview_docs).",
    )
    parser.add_argument(
        "--sync-sheet",
        action="store_true",
        help="Sync generated doc links to Google Sheet (when Drive upload is configured).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    root_dir = Path(__file__).resolve().parent
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = root_dir / out_dir

    print("=" * 70)
    print(" 📄 INTERVIEW PREPARATION DOCUMENT GENERATOR")
    print("=" * 70)

    jobs = None
    if not args.from_sheet:
        json_path = Path(args.json) if args.json else (root_dir / "output" / "fresher_jobs_latest.json")
        if not json_path.exists():
            print(f"[!] Jobs file not found at: {json_path}")
            print("    Run 'python main.py' first or use '--from-sheet' to load from Google Sheets.")
            sys.exit(1)
        jobs = load_jobs_from_json(json_path)
        print(f"[*] Loaded {len(jobs)} job(s) from: {json_path.name}")
    else:
        print("[*] Loading verified jobs from live Google Sheet...")

    stats = run_interview_docs(
        jobs=jobs,
        output_base_dir=out_dir,
        from_sheet=args.from_sheet,
        company_filter=args.company,
        limit=args.limit,
        force=args.force,
        sync_sheet=args.sync_sheet,
    )

    print("\n" + "=" * 70)
    print(" 📊 INTERVIEW PREP GENERATION SUMMARY")
    print("=" * 70)
    print(f" Target Jobs Considered:   {stats['total_jobs']}")
    print(f" Freshly Generated:        {stats['generated']}")
    print(f" Skipped (Cached):         {stats['cached']}")
    print(f" Failed / Skipped:         {stats['failed']}")
    print(f" Output Directory:         {out_dir}")

    if stats["docs"]:
        print("\n Generated Document Catalog:")
        for doc in stats["docs"]:
            status_tag = "✅ NEW" if doc.get("status") == "generated" else "⚡ CACHED"
            q_info = f" ({doc['questions_count']} Qs)" if "questions_count" in doc else ""
            print(f"   • {status_tag} {doc.get('company')} — {doc.get('role')}{q_info}")
            print(f"     Path: {doc.get('pdf_path')}")
    print("=" * 70)


if __name__ == "__main__":
    main()
