"""Source Comparison & Empirical Performance Evaluator.

Compares yield, acceptance rate, and rejection patterns across all scraped sources.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from typing import Dict, List
from config.settings import VERIFIED_DATA_DIR, REJECTED_DATA_DIR, REPORTS_DATA_DIR


def generate_source_comparison_report() -> Dict[str, object]:
    """Generates comparative statistical analysis across sources."""
    verified_file = VERIFIED_DATA_DIR / "verified_opportunities.json"
    rejected_file = REJECTED_DATA_DIR / "rejected_opportunities.json"

    verified = []
    if verified_file.exists():
        with open(verified_file, "r", encoding="utf-8") as f:
            verified = json.load(f)

    rejected = []
    if rejected_file.exists():
        with open(rejected_file, "r", encoding="utf-8") as f:
            rejected = json.load(f)

    source_stats: Dict[str, Dict[str, int]] = {}

    for item in verified:
        opp = item.get("opportunity", {})
        src = opp.get("source_id", "unknown")
        if src not in source_stats:
            source_stats[src] = {"verified": 0, "rejected": 0, "total": 0}
        source_stats[src]["verified"] += 1
        source_stats[src]["total"] += 1

    for item in rejected:
        opp = item.get("opportunity", {})
        src = opp.get("source_id", "unknown")
        if src not in source_stats:
            source_stats[src] = {"verified": 0, "rejected": 0, "total": 0}
        source_stats[src]["rejected"] += 1
        source_stats[src]["total"] += 1

    summary = {}
    for src, counts in source_stats.items():
        total = counts["total"]
        rate = round((counts["verified"] / total) * 100, 2) if total > 0 else 0.0
        summary[src] = {
            "total_discovered": total,
            "verified_count": counts["verified"],
            "rejected_count": counts["rejected"],
            "acceptance_yield_pct": rate,
        }

    report = {
        "sources": summary,
        "overall": {
            "total_opportunities": len(verified) + len(rejected),
            "total_verified": len(verified),
            "total_rejected": len(rejected),
        }
    }

    out_file = REPORTS_DATA_DIR / "source_comparison_report.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    rep = generate_source_comparison_report()
    print("Source comparison report generated:", json.dumps(rep, indent=2))
