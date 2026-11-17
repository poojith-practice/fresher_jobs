"""CampusDrive.in Off-Campus Recruitment Scraper."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urljoin, unquote
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

logger = logging.getLogger("coverage_lab.campusdrive")


class CampusDriveScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            source_id="campusdrive",
            name="CampusDrive.in",
            base_url="https://campusdrive.in/jobs",
            rate_limit_seconds=2.0,
        )

    def scrape(self, max_items: int = 25) -> List[Dict[str, Any]]:
        html = self.fetch_html(self.base_url)
        if not html:
            logger.warning("[campusdrive] Failed to load listing page HTML")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        seen_links = set()

        # Find all job links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # Match off-campus drive slugs
            if not any(x in href for x in ["off-campus", "recruitment", "hiring", "-drive"]) or href in seen_links:
                continue
            if href.startswith("https://api.whatsapp.com") or href.startswith("https://t.me"):
                continue

            title = a.get_text(strip=True)
            if len(title) < 8 or title.lower() in {"view details", "apply", "apply →", "read more"}:
                continue

            seen_links.add(href)
            full_detail_url = urljoin(self.base_url, href)

            # Look for adjacent WhatsApp share text which embeds structured data
            parent = a.find_parent(["div", "article", "li"])
            wa_text = ""
            if parent:
                wa_anchor = parent.find("a", href=re.compile(r"api\.whatsapp\.com"))
                if wa_anchor and "href" in wa_anchor.attrs:
                    wa_text = unquote(wa_anchor["href"])

            # Extract structured parameters from WhatsApp share snippet if present
            company = "Unknown"
            role = title
            batches: List[str] = []
            salary_raw = None
            location = "Pan India"

            if wa_text:
                batch_match = re.search(r"Batch[:\*]*\s*([^\n\r]+)", wa_text, re.IGNORECASE)
                if batch_match:
                    b_str = batch_match.group(1)
                    batches = re.findall(r"202\d", b_str)

                pkg_match = re.search(r"Package[:\*]*\s*([^\n\r]+)", wa_text, re.IGNORECASE)
                if pkg_match:
                    salary_raw = pkg_match.group(1).replace("*", "").strip()

                loc_match = re.search(r"Location[:\*]*\s*([^\n\r]+)", wa_text, re.IGNORECASE)
                if loc_match:
                    location = loc_match.group(1).replace("*", "").strip()

                role_match = re.search(r"Role[:\*]*\s*([^\n\r]+)", wa_text, re.IGNORECASE)
                if role_match:
                    role_str = role_match.group(1).replace("*", "").strip()
                    if ":" in role_str:
                        parts = role_str.split(":", 1)
                        company = parts[0].replace("Off Campus Drive", "").strip()
                        role = parts[1].strip()
                    else:
                        role = role_str

            if company == "Unknown":
                # Fallback parse from title: e.g. "Tata Communications Off Campus Drive 2026..."
                parts = title.split("Off Campus", 1)
                if len(parts) > 1:
                    company = parts[0].replace("—", "").strip()

            if not batches:
                batches = re.findall(r"202\d", f"{title} {wa_text}")

            results.append({
                "source_id": self.source_id,
                "raw_id": href.strip("/"),
                "title": role if role else title,
                "company": company if company else "Campus Drive Employer",
                "location": location,
                "description": f"{title}\n{wa_text}",
                "batches": list(dict.fromkeys(batches)),
                "salary_raw": salary_raw,
                "listing_url": self.base_url,
                "apply_url": full_detail_url,
                "deadline": None,
                "deadline_status": "OPEN",
                "date_posted": None,
                "raw_metadata": {"whatsapp_share": wa_text, "raw_title": title},
            })

            if len(results) >= max_items:
                break

        logger.info("[campusdrive] Extracted %d listings", len(results))
        return results
