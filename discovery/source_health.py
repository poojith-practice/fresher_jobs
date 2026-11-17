"""Source Health & Availability Prober.

Continuously assesses network latency, HTTP status codes, and payload health
across all registered job and recruitment drive platforms.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent.parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from typing import Dict, List
try:
    from curl_cffi import requests
except ImportError:
    import requests
from config.sources import SOURCES_CONFIG


def check_all_source_health() -> List[Dict[str, object]]:
    """Probes all registered sources and returns latency and health metrics."""
    results = []
    for source_id, source in SOURCES_CONFIG.items():
        start_time = time.time()
        status_code = 0
        is_healthy = False
        error_msg = None
        listing_url = source.get("url", "")

        try:
            resp = requests.get(
                listing_url,
                timeout=8,
                impersonate="chrome120",
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            elapsed_ms = int((time.time() - start_time) * 1000)
            status_code = resp.status_code
            is_healthy = (status_code == 200 and len(resp.content) > 500)
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)

        results.append({
            "source_id": source_id,
            "name": source.get("name", source_id),
            "url": listing_url,
            "status_code": status_code,
            "latency_ms": elapsed_ms,
            "is_healthy": is_healthy,
            "category": source.get("category", "aggregator"),
            "error": error_msg,
        })

    return results


if __name__ == "__main__":
    health_data = check_all_source_health()
    print("=" * 70)
    print("SOURCE HEALTH & LATENCY AUDIT")
    print("=" * 70)
    for h in health_data:
        mark = "✅" if h["is_healthy"] else "❌"
        print(f"{mark} [{h['category']}] {h['name']:<25} | Status: {h['status_code']} | Latency: {h['latency_ms']}ms")
    print("=" * 70)
