"""JoinSaarthi Off-Campus Drives Scraper.

Extracts structured recruitment drive payloads directly from Next.js __NEXT_DATA__.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.saarthi")


class SaarthiScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="saarthi_drives",
            name="JoinSaarthi Off-Campus",
            base_url="https://joinsaarthi.com/drives/off-campus",
            rate_limit_seconds=2.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        html = self.fetch_html(self.base_url)
        if not html:
            logger.warning("[saarthi_drives] Failed to load listing page HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            logger.warning("[saarthi_drives] Missing __NEXT_DATA__ script in HTML")
            return []

        try:
            data = json.loads(script.string)
        except Exception as exc:
            logger.error("[saarthi_drives] JSON parse error in __NEXT_DATA__: %s", exc)
            return []

        drives = data.get("props", {}).get("pageProps", {}).get("initialDrives", [])
        logger.info("[saarthi_drives] Discovered %d drives in pageProps", len(drives))

        results: List[Dict[str, Any]] = []
        for d in drives[:max_items]:
            drive_id = str(d.get("id") or "")
            name = str(d.get("drive_name") or "").strip()
            if not name:
                continue

            company_info = d.get("company") or {}
            company_name = (
                str(company_info.get("name") or "")
                or str(d.get("college_controlled_drive_company_name") or "")
                or "Unknown Company"
            ).strip()

            locations = d.get("locations") or []
            if isinstance(locations, list):
                location_str = ", ".join(str(loc) for loc in locations) if locations else "Pan India"
            else:
                location_str = str(locations)

            # Batches extraction from eligibility or title
            eligibility = str(d.get("eligibility_criteria") or "")
            desc = str(d.get("description") or "")
            full_text = f"{name} {eligibility} {desc}"

            batches = [b for b in ["2024", "2025", "2026", "2027", "2028"] if b in full_text]

            # Deadlines & Status
            start_date = d.get("start_date")
            end_date = d.get("end_date")
            is_ended = bool(d.get("isDriveEnded") or False)
            drive_status = "CLOSED" if is_ended else "OPEN"

            apply_url = f"https://joinsaarthi.com/drives/{drive_id}" if drive_id else self.base_url

            results.append({
                "source_id": self.source_id,
                "raw_id": drive_id,
                "title": name,
                "company": company_name,
                "location": location_str,
                "description": desc,
                "eligibility_criteria": eligibility,
                "batches": batches,
                "min_salary": d.get("ctc_min"),
                "max_salary": d.get("ctc_max"),
                "listing_url": self.base_url,
                "apply_url": apply_url,
                "deadline": end_date,
                "deadline_status": drive_status,
                "date_posted": str(d.get("created_at") or ""),
                "raw_metadata": d,
            })

        return results
