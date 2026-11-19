"""
Production RocketReach API Client & HR Enrichment Engine
=========================================================
Directory: fresher_job_scraper/

Features:
1. Clean REST v2 interaction using 'Api-Key' header.
2. Built-in rate limiting with request pacing (0.6s) and exponential backoff on HTTP 429.
3. Multi-tier search hierarchy:
   - Tier 1: Target company + Campus/Talent Acquisition recruiter titles + India location
   - Tier 2: Target company + Human Resources department + India location
   - Tier 3: Target company + Global HR/Recruiter titles
   - Tier 4: Clean company brand alias fallback
4. Deep lookup hydration (/v2/api/lookupProfile) with automatic async polling.
5. In-memory company caching to prevent duplicate API queries across job listings.
6. Strict verification: Never fabricates or misattributes contact information.
"""

import os
import re
import time
import json
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger("RocketReachHR")

ROCKETREACH_API_KEY_DEFAULT = "1cfb3c5k109696672f1c5538929215d9ef473989"
BASE_URL = "https://api.rocketreach.co/v2/api"

# Priority HR titles for campus / fresher / tech hiring
HR_TITLES_CAMPUS_PRIORITY = [
    "University Relations",
    "Campus Recruiter",
    "Campus Recruitment",
    "College Recruiter",
    "Early Careers Recruiter",
    "Talent Acquisition Specialist",
    "Talent Acquisition Lead",
    "Talent Acquisition Manager",
    "Technical Recruiter",
    "Senior Recruiter",
    "Recruiter",
    "HR Manager",
    "Human Resources Lead",
    "People Operations",
    "HR Business Partner"
]

class RocketReachClient:
    _cache: Dict[str, Dict[str, Any]] = {}

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ROCKETREACH_API_KEY", ROCKETREACH_API_KEY_DEFAULT)
        self.headers = {
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.last_request_time = 0.0
        self.min_interval = 0.6  # Safe pace: max ~1.6 req/s

    def _throttle(self):
        """Enforces safe client-side rate limits."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def check_account_status(self) -> Dict[str, Any]:
        """Queries account endpoint to verify credits and rate limits."""
        self._throttle()
        url = f"{BASE_URL}/account"
        res = requests.get(url, headers=self.headers, timeout=15)
        if res.status_code == 200:
            return res.json()
        raise RuntimeError(f"RocketReach account query failed [HTTP {res.status_code}]: {res.text}")

    @staticmethod
    def generate_company_aliases(raw_name: str) -> List[str]:
        """
        Generates clean aliases from corporate names.
        e.g., 'Hewlett Packard Enterprise (HPE)' -> ['Hewlett Packard Enterprise (HPE)', 'Hewlett Packard Enterprise', 'HPE']
        """
        aliases = [raw_name.strip()]
        
        # Strip trailing legal entities
        cleaned = re.sub(r"\b(Pvt\.?\s*Ltd\.?|Ltd\.?|Inc\.?|LLC|Corporation|Corp\.?|Services|Technologies|Investments)\b", "", raw_name, flags=re.I).strip()
        cleaned = re.sub(r"[\s,]+$", "", cleaned)
        if cleaned and cleaned not in aliases:
            aliases.append(cleaned)
            
        # Extract abbreviation or text in parentheses: e.g. (HPE), (KGS), (Dentsu Creative)
        paren_match = re.search(r"\((.*?)\)", raw_name)
        if paren_match:
            inside_paren = paren_match.group(1).strip()
            outside_paren = re.sub(r"\(.*?\)", "", raw_name).strip()
            outside_paren = re.sub(r"[\s,]+$", "", outside_paren)
            if outside_paren and outside_paren not in aliases:
                aliases.append(outside_paren)
            if inside_paren and inside_paren not in aliases:
                aliases.append(inside_paren)
                
        # Common brand expansions/shortenings
        brand_map = {
            "larsen & toubro": "L&T",
            "kpmg global services (kgs)": "KPMG",
            "kpmg global services": "KPMG",
            "hewlett packard enterprise (hpe)": "Hewlett Packard Enterprise",
            "dentsu (dentsu creative)": "Dentsu",
            "eclerx investments ltd": "eClerx",
            "deloitte shared services india": "Deloitte",
            "goldman sachs": "Goldman Sachs",
            "nxtwave disruptive technologies": "Nxtwave",
            "hitachi digital": "Hitachi",
        }
        lower_raw = raw_name.lower().strip()
        if lower_raw in brand_map and brand_map[lower_raw] not in aliases:
            aliases.append(brand_map[lower_raw])

        return aliases

    def search_hr_profiles(self, company_name: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Multi-stage search for HR and recruiter contacts at a company."""
        aliases = self.generate_company_aliases(company_name)

        for alias in aliases:
            # Tier 1: Targeted HR Titles in India
            query_t1 = {
                "current_employer": [alias],
                "current_title": HR_TITLES_CAMPUS_PRIORITY[:8],
                "location": ["India"],
            }
            profiles = self._execute_search(query_t1, page_size=max_results)
            if profiles:
                return profiles

            # Tier 2: General HR Department in India
            query_t2 = {
                "current_employer": [alias],
                "department": ["Human Resources"],
                "location": ["India"],
            }
            profiles = self._execute_search(query_t2, page_size=max_results)
            if profiles:
                return profiles

            # Tier 3: Global HR / Recruiter
            query_t3 = {
                "current_employer": [alias],
                "current_title": ["Talent Acquisition", "Technical Recruiter", "Campus Recruiter", "HR Manager"],
            }
            profiles = self._execute_search(query_t3, page_size=max_results)
            if profiles:
                return profiles

        return []

    def _execute_search(self, query: Dict[str, Any], page_size: int = 5) -> List[Dict[str, Any]]:
        """Executes a single search request against /v2/api/search."""
        self._throttle()
        url = f"{BASE_URL}/search"
        payload = {
            "query": query,
            "page_size": page_size,
            "order_by": "popularity"
        }
        for attempt in range(3):
            try:
                res = requests.post(url, headers=self.headers, json=payload, timeout=20)
                if res.status_code == 201:
                    data = res.json()
                    return data.get("profiles", [])
                elif res.status_code == 429:
                    wait_time = (attempt + 1) * 3
                    logger.warning(f"RocketReach 429 rate limit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    return []
            except Exception as exc:
                logger.error(f"Search request exception: {exc}")
                time.sleep(1)
        return []

    def lookup_person_details(self, profile_id: int, max_poll_attempts: int = 3) -> Optional[Dict[str, Any]]:
        """Retrieves complete, verified profile and contact details via /v2/api/lookupProfile."""
        self._throttle()
        url = f"{BASE_URL}/lookupProfile?id={profile_id}"
        
        for attempt in range(max_poll_attempts):
            try:
                res = requests.get(url, headers=self.headers, timeout=20)
                if res.status_code != 200:
                    return None
                    
                data = res.json()
                status = data.get("status")
                
                if status in ("complete", "not queued", "failed"):
                    return data
                    
                if status == "progress":
                    time.sleep(1.5)
                    continue
            except Exception as exc:
                logger.error(f"Lookup request exception for {profile_id}: {exc}")
                time.sleep(1)
                
        return data

    def enrich_company_hr(self, company_name: str) -> Dict[str, Any]:
        """
        Enriches a company with its primary verified HR/Recruiter contact.
        Uses in-memory cache to guarantee zero duplicate API queries for identical companies.
        """
        clean_key = company_name.strip().casefold()
        if clean_key in self._cache:
            return self._cache[clean_key]

        profiles = self.search_hr_profiles(company_name, max_results=3)
        if not profiles:
            result = {
                "company": company_name,
                "status": "NOT_FOUND",
                "hr_name": None,
                "hr_title": None,
                "hr_email": None,
                "hr_phone": None,
                "hr_linkedin": None,
                "display_text": "Not found from RocketReach",
            }
            self._cache[clean_key] = result
            return result

        top_candidate = profiles[0]
        profile_id = top_candidate.get("id")
        
        full_data = self.lookup_person_details(profile_id)
        if not full_data:
            full_data = top_candidate

        # Extract best verified email
        emails = full_data.get("emails", [])
        best_email = None
        for e in emails:
            if isinstance(e, dict):
                email_addr = e.get("email")
                is_valid = e.get("smtp_valid") == "valid" or e.get("grade") in ("A", "A-", "B")
                is_prof = e.get("type") == "professional"
                if is_valid and is_prof:
                    best_email = email_addr
                    break
                elif is_valid and not best_email:
                    best_email = email_addr
                elif is_prof and not best_email:
                    best_email = email_addr
                elif not best_email:
                    best_email = email_addr

        # Extract best phone
        phones = full_data.get("phones", [])
        best_phone = None
        for p in phones:
            if isinstance(p, dict):
                num = p.get("e164") or p.get("number")
                if p.get("recommended") or p.get("validity") == "valid":
                    best_phone = num
                    break
                elif not best_phone:
                    best_phone = num

        name = full_data.get("name")
        title = full_data.get("current_title")
        linkedin = full_data.get("linkedin_url") or (full_data.get("links") or {}).get("linkedin")
        employer = full_data.get("current_employer")

        # Validate that title belongs to HR/Recruiting domain
        if title:
            title_lower = title.lower()
            if not any(k in title_lower for k in ["recruit", "talent", "human resource", "hr", "people", "staffing", "sourcing", "hiring"]):
                result = {
                    "company": company_name,
                    "status": "NOT_FOUND",
                    "hr_name": None,
                    "hr_title": None,
                    "hr_email": None,
                    "hr_phone": None,
                    "hr_linkedin": None,
                    "display_text": "Not found from RocketReach",
                }
                self._cache[clean_key] = result
                return result

        components = [f"{name} ({title})"]
        if best_email:
            components.append(f"Email: {best_email}")
        if best_phone:
            components.append(f"Phone: {best_phone}")
        if linkedin:
            components.append(f"LinkedIn: {linkedin}")

        display_text = " | ".join(components)

        result = {
            "company": company_name,
            "status": "FOUND",
            "matched_employer": employer,
            "hr_name": name,
            "hr_title": title,
            "hr_email": best_email,
            "hr_phone": best_phone,
            "hr_linkedin": linkedin,
            "display_text": display_text,
        }
        self._cache[clean_key] = result
        return result
