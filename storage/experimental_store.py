"""Isolated Experimental Storage & Deduplication Engine.

Maintains SQLite tables exclusively in fresher_job_scraper_coverage_lab/data/
and manages JSON serialization for verified, rejected, and manual review outputs.
"""
from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from config.settings import (
    EXPERIMENTAL_DB_PATH,
    VERIFIED_DATA_DIR,
    REJECTED_DATA_DIR,
    MANUAL_REVIEW_DATA_DIR,
    NORMALIZED_DATA_DIR,
)
from models.opportunity import Opportunity
from models.verification_result import VerificationDecision, VerificationRecord

logger = logging.getLogger("coverage_lab.store")


class ExperimentalStore:
    def __init__(self, db_path: Path = EXPERIMENTAL_DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def close(self) -> None:
        """Explicit close hook for clean resource disposal."""
        pass

    def _init_db(self) -> None:
        """Initializes isolated tables for opportunities and audits."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS opportunities (
                    id TEXT PRIMARY KEY,
                    opportunity_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL,
                    description TEXT,
                    eligible_batches TEXT,
                    salary_raw TEXT,
                    min_salary REAL,
                    max_salary REAL,
                    source_id TEXT NOT NULL,
                    listing_url TEXT NOT NULL,
                    apply_url TEXT NOT NULL,
                    requisition_id TEXT,
                    provenance TEXT NOT NULL,
                    date_posted TEXT,
                    deadline TEXT,
                    deadline_status TEXT,
                    explicit_skills TEXT,
                    inferred_skills TEXT,
                    discovered_at TEXT NOT NULL,
                    raw_metadata TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS verification_records (
                    opportunity_id TEXT PRIMARY KEY,
                    decision TEXT NOT NULL,
                    company_authenticity TEXT,
                    opportunity_authenticity TEXT,
                    application_validity TEXT,
                    rejection_reasons TEXT,
                    manual_review_reasons TEXT,
                    verified_at TEXT,
                    auditor TEXT,
                    fresher_eligibility TEXT,
                    FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_opp_dedup 
                ON opportunities (company, normalized_title, apply_url)
            """)
            conn.commit()

    def save_opportunity(self, opp: Opportunity) -> Opportunity:
        """Saves opportunity or merges provenance if duplicate exists."""
        with self._get_connection() as conn:
            # Check for existing duplicate by requisition_id or (company + normalized_title)
            existing = None
            if opp.requisition_id:
                cur = conn.execute(
                    "SELECT * FROM opportunities WHERE company = ? AND requisition_id = ?",
                    (opp.company, opp.requisition_id),
                )
                existing = cur.fetchone()

            if not existing:
                cur = conn.execute(
                    "SELECT * FROM opportunities WHERE company = ? AND normalized_title = ? AND location = ?",
                    (opp.company, opp.normalized_title, opp.location),
                )
                existing = cur.fetchone()

            if existing:
                # Merge provenance
                prev_sources = json.loads(existing["provenance"] or "[]")
                merged_sources = list(dict.fromkeys(prev_sources + opp.provenance))
                conn.execute(
                    "UPDATE opportunities SET provenance = ? WHERE id = ?",
                    (json.dumps(merged_sources), existing["id"]),
                )
                conn.commit()
                opp.provenance = merged_sources
                opp.id = existing["id"]
                return opp

            # Insert new
            conn.execute(
                """
                INSERT OR REPLACE INTO opportunities (
                    id, opportunity_type, title, normalized_title, company, location,
                    description, eligible_batches, salary_raw, min_salary, max_salary,
                    source_id, listing_url, apply_url, requisition_id, provenance,
                    date_posted, deadline, deadline_status, explicit_skills,
                    inferred_skills, discovered_at, raw_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opp.id,
                    opp.opportunity_type.value,
                    opp.title,
                    opp.normalized_title,
                    opp.company,
                    opp.location,
                    opp.description,
                    json.dumps(opp.eligible_batches),
                    opp.salary_raw,
                    opp.min_salary,
                    opp.max_salary,
                    opp.source_id,
                    opp.listing_url,
                    opp.apply_url,
                    opp.requisition_id,
                    json.dumps(opp.provenance),
                    opp.date_posted,
                    opp.deadline,
                    opp.deadline_status,
                    json.dumps(opp.explicit_skills),
                    json.dumps(opp.inferred_skills),
                    opp.discovered_at,
                    json.dumps(opp.raw_metadata),
                ),
            )
            conn.commit()
            return opp

    def save_verification(self, record: VerificationRecord) -> None:
        """Saves a verification decision audit record."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO verification_records (
                    opportunity_id, decision, company_authenticity, opportunity_authenticity,
                    application_validity, rejection_reasons, manual_review_reasons,
                    verified_at, auditor, fresher_eligibility
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.opportunity_id,
                    record.decision.value,
                    record.company_authenticity.value if record.company_authenticity else None,
                    record.opportunity_authenticity,
                    record.application_validity,
                    json.dumps(record.rejection_reasons),
                    json.dumps(record.manual_review_reasons),
                    record.verified_at,
                    record.auditor,
                    record.fresher_eligibility.model_dump_json() if record.fresher_eligibility else None,
                ),
            )
            conn.commit()

    def export_partitioned_datasets(
        self,
        opportunities: List[Opportunity],
        verifications: Dict[str, VerificationRecord],
    ) -> Dict[str, int]:
        """Saves opportunities partitioned into normalized, verified, rejected, manual_review."""
        counts = {"normalized": len(opportunities), "verified": 0, "rejected": 0, "manual_review": 0}

        norm_list = [o.model_dump() for o in opportunities]
        with open(NORMALIZED_DATA_DIR / "opportunities_normalized.json", "w", encoding="utf-8") as f:
            json.dump(norm_list, f, indent=2, ensure_ascii=False)

        verified_list = []
        rejected_list = []
        review_list = []

        for opp in opportunities:
            v = verifications.get(opp.id)
            if not v:
                continue

            item = {
                "opportunity": opp.model_dump(),
                "verification": v.model_dump(),
            }

            if v.decision == VerificationDecision.ACCEPTED:
                verified_list.append(item)
            elif v.decision == VerificationDecision.REJECTED:
                rejected_list.append(item)
            else:
                review_list.append(item)

        counts["verified"] = len(verified_list)
        counts["rejected"] = len(rejected_list)
        counts["manual_review"] = len(review_list)

        with open(VERIFIED_DATA_DIR / "verified_opportunities.json", "w", encoding="utf-8") as f:
            json.dump(verified_list, f, indent=2, ensure_ascii=False)

        with open(REJECTED_DATA_DIR / "rejected_opportunities.json", "w", encoding="utf-8") as f:
            json.dump(rejected_list, f, indent=2, ensure_ascii=False)

        with open(MANUAL_REVIEW_DATA_DIR / "manual_review_opportunities.json", "w", encoding="utf-8") as f:
            json.dump(review_list, f, indent=2, ensure_ascii=False)

        return counts
