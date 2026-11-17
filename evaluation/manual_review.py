"""Manual Review Triage Engine.

Provides utilities to inspect, audit, and adjudicate ambiguous opportunities
routed to manual review partitions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional
from config.settings import MANUAL_REVIEW_DATA_DIR, VERIFIED_DATA_DIR, REJECTED_DATA_DIR


class ManualReviewQueue:
    """Manages the manual review workflow for borderline fresher opportunities."""

    def __init__(self, review_file: Path = MANUAL_REVIEW_DATA_DIR / "manual_review_opportunities.json"):
        self.review_file = review_file

    def load_queue(self) -> List[Dict[str, object]]:
        if not self.review_file.exists():
            return []
        try:
            with open(self.review_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def adjudicate(
        self,
        opportunity_id: str,
        approve: bool,
        reviewer: str = "placement_officer",
        comment: str = "",
    ) -> bool:
        """Adjudicates a flagged item, moving it from manual review to verified or rejected."""
        queue = self.load_queue()
        target = None
        remaining = []

        for item in queue:
            if item.get("opportunity", {}).get("id") == opportunity_id:
                target = item
            else:
                remaining.append(item)

        if not target:
            return False

        # Update decision
        target["verification"]["decision"] = "ACCEPTED" if approve else "REJECTED"
        target["verification"]["auditor"] = reviewer
        target["verification"]["manual_review_reasons"].append(f"Adjudication by {reviewer}: {comment}")

        target_file = (VERIFIED_DATA_DIR / "verified_opportunities.json") if approve else (REJECTED_DATA_DIR / "rejected_opportunities.json")
        existing_targets = []
        if target_file.exists():
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    existing_targets = json.load(f)
            except Exception:
                existing_targets = []

        existing_targets.append(target)

        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(existing_targets, f, indent=2, ensure_ascii=False)

        with open(self.review_file, "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2, ensure_ascii=False)

        return True
