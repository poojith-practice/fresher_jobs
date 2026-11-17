"""
Partitioned Local Dataset Storage Engine
========================================
Persists opportunity datasets into isolated partition folders:
data/raw/, data/normalised/, data/approved/, data/rejected/, and data/manual_review/.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from core.models import (
    Opportunity,
    FinalApprovalStatus,
)

logger = logging.getLogger("storage.local_store")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALISED_DIR = DATA_DIR / "normalised"
APPROVED_DIR = DATA_DIR / "approved"
REJECTED_DIR = DATA_DIR / "rejected"
MANUAL_REVIEW_DIR = DATA_DIR / "manual_review"


class LocalDatasetStore:
    """Manages filesystem partition persistence for experimental opportunities."""

    def __init__(self):
        for directory in [DATA_DIR, RAW_DIR, NORMALISED_DIR, APPROVED_DIR, REJECTED_DIR, MANUAL_REVIEW_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

    def save_raw_listings(self, listings: List[Dict], source_name: str) -> Path:
        """Saves raw scraped listings JSON for traceability."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"raw_{source_name}_{timestamp}.json"
        target_path = RAW_DIR / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(listings, f, indent=2, ensure_ascii=False)
        return target_path

    def save_normalised(self, opportunities: List[Opportunity], run_id: Optional[str] = None) -> Path:
        """Saves normalised Opportunity objects prior to verification."""
        run_tag = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        target_path = NORMALISED_DIR / f"normalised_{run_tag}.json"
        data = [opp.model_dump() for opp in opportunities]
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return target_path

    def save_partitioned_results(self, verified_opportunities: List[Opportunity], run_id: Optional[str] = None) -> Dict[str, int]:
        """Partitions verified opportunities into approved, rejected, and manual_review buckets."""
        run_tag = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        approved: List[Dict] = []
        rejected: List[Dict] = []
        manual_review: List[Dict] = []

        for opp in verified_opportunities:
            dumped = opp.model_dump()
            if opp.final_status == FinalApprovalStatus.APPROVED:
                approved.append(dumped)
            elif opp.final_status == FinalApprovalStatus.MANUAL_REVIEW:
                manual_review.append(dumped)
            else:
                rejected.append(dumped)

        # Write to respective folders
        with open(APPROVED_DIR / f"approved_{run_tag}.json", "w", encoding="utf-8") as f:
            json.dump(approved, f, indent=2, ensure_ascii=False)

        with open(REJECTED_DIR / f"rejected_{run_tag}.json", "w", encoding="utf-8") as f:
            json.dump(rejected, f, indent=2, ensure_ascii=False)

        with open(MANUAL_REVIEW_DIR / f"manual_review_{run_tag}.json", "w", encoding="utf-8") as f:
            json.dump(manual_review, f, indent=2, ensure_ascii=False)

        logger.info(
            "[local_store] Partitioned run '%s': %d approved, %d rejected, %d manual review",
            run_tag, len(approved), len(rejected), len(manual_review),
        )

        return {
            "approved": len(approved),
            "rejected": len(rejected),
            "manual_review": len(manual_review),
            "total": len(verified_opportunities),
        }
