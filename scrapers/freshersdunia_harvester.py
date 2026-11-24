"""
FreshersDunia Job Harvester & Verification Engine (Production-Grade)
Directory: job_experiments/

Key Features:
1. Multi-tier ingestion (WordPress REST API + Fallbacks)
2. Guardrails:
   - Experience Gate: Strictly discards experienced/senior postings (e.g. 3+ years, 1-10 years)
   - Application Last Date Gate: Strictly discards postings where last_date < today's date
   - Domain & Link Health Gate: Dissects and validates every external ATS/Apply link
     * Catches Publisher Copy-Paste Errors (e.g. Deloitte job with Infosys URL)
     * Detects Session-Gated URLs (e.g. Jio error.aspx timeout)
     * Detects Blank SPA Requisition shells (e.g. PeopleStrong L&T)
     * Auto-generates clean, working Fallback Career URLs based on Company & Job Requisition ID
3. Local CSV Persistence matching Google Sheets schema with Link Diagnostics:
   [Job Title, Company, Location, Role, Date Posted, Experience, Min Salary, Max Salary,
    Apply URL, Fallback / Clean URL, Link Health Status, Source, Last Updated,
    skills/responsibilities, Interview QnA doc, Application Last Date, All Apply Links]
"""

import os
import re
import csv
import json
import html
import subprocess
import logging
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Any, List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FreshersDuniaHarvester")

BASE_URL = "https://freshersdunia.in"
WP_API_URL = f"{BASE_URL}/wp-json/wp/v2/posts"
DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "freshersdunia_jobs.csv")

CLOSED_PATTERNS = [
    r'thanks\s+for\s+your\s+interest',
    r'thank\s+you\s+for\s+your\s+interest',
    r'position\s+is\s+closed',
    r'this\s+position\s+is\s+closed',
    r'position\s+has\s+been\s+closed',
    r'this\s+job\s+is\s+closed',
    r'job\s+is\s+closed',
    r'no\s+longer\s+available',
    r'is\s+no\s+longer\s+available',
    r'this\s+job\s+is\s+no\s+longer\s+available',
    r'the\s+job\s+you\s+are\s+looking\s+for\s+has\s+been\s+filled',
    r'the\s+job\s+you\s+are\s+trying\s+to\s+apply\s+for\s+has\s+been\s+filled',
    r'job\s+has\s+been\s+filled',
    r'has\s+been\s+filled',
    r'no\s+longer\s+accepting\s+applications',
    r'not\s+currently\s+accepting\s+applications',
    r'job\s+has\s+expired',
    r'posting\s+has\s+expired',
    r'this\s+opening\s+has\s+expired',
    r'applications\s+closed',
    r'job\s+is\s+inactive',
    r'job\s+not\s+found',
    r'job\s+posting\s+not\s+found',
    r'the\s+page\s+you\s+are\s+looking\s+for\s+doesn\'?t\s+exist',
    r'requisition\s+has\s+been\s+closed',
    r'invalid\s+request',
    r'can\'?t\s+view\s+this\s+job',
    r'not\s+available\s+at\s+this\s+time',
    r'access\s+denied',
    r'login_required',
    r'session\s+has\s+timed\s+out',
    r'sign\s+in\s+to\s+your\s+account'
]

APPLY_BUTTON_REGEX = re.compile(
    r'^\s*(apply\s+now|apply\s+for\s+this\s+job|apply\s+online|easy\s+apply|submit\s+application|start\s+application|register\s+and\s+apply|apply)\s*$',
    re.I
)

class ATSVerifier:
    def __init__(self):
        self._playwright = None
        self._browser = None

    def _ensure_browser(self):
        if not self._playwright:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                channel="msedge",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"]
            )

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def verify_ats_url(self, url: str, timeout_ms: int = 25000) -> Tuple[bool, str]:
        """
        Loads candidate ATS portal in headless Edge, allows client JavaScript / React / Angular
        to hydrate, and inspects whether the position is actually open and has a live application action.
        Returns: (is_active: bool, diagnostic_message: str)
        """
        if not url or not url.startswith("http"):
            return False, "INVALID_URL: Link missing or empty"

        # Pre-filter: Reject generic corporate homepages or search URLs
        if any(h in url.lower() for h in ['google.com/search', 'wipro.com/', 'infosys.com/', 'deloitte.com/us/en.html']):
            if not any(k in url.lower() for k in ['/job/', '/careers/job', 'jobdesc', 'requisition', 'profile']):
                return False, "REJECTED_GENERIC_HOMEPAGE: Link points to a corporate home page, not a specific requisition"

        try:
            self._ensure_browser()
            context = self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()

            try:
                resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
            status = resp.status if resp else 0
            if status in (404, 410, 403, 500):
                page.close()
                context.close()
                return False, f"REJECTED_HTTP_{status}: ATS portal returned error status {status}"

            page.wait_for_timeout(3500)
            final_url = page.url
            body_text = page.locator("body").inner_text()

            # Pre-filter: Redirect to login or auth page
            if "login" in final_url.lower() and "login" not in url.lower():
                page.close()
                context.close()
                return False, f"REJECTED_AUTH_REDIRECT: Requisition redirected to login screen ({final_url})"

            # 1. Closed Pattern Detection
            for pat in CLOSED_PATTERNS:
                m = re.search(pat, body_text, re.I) or re.search(pat, final_url, re.I)
                if m:
                    match_snippet = m.group(0)
                    page.close()
                    context.close()
                    return False, f"REJECTED_POSITION_CLOSED: ATS renders '{match_snippet}'"

            # 2. Positive Apply Action Detection
            valid_apply_buttons = []
            for frame in page.frames:
                for selector in ["button", "a", "input[type='button']", "input[type='submit']", "div[role='button']"]:
                    try:
                        elements = frame.locator(selector).all()
                        for el in elements:
                            if el.is_visible():
                                txt = el.inner_text().strip().replace('\n', ' ')
                                if APPLY_BUTTON_REGEX.search(txt) and len(txt) < 40:
                                    valid_apply_buttons.append((selector, txt))
                    except Exception:
                        pass

            if not valid_apply_buttons:
                forms = page.locator("form").all()
                if forms and len(body_text.strip()) > 300:
                    valid_apply_buttons.append(("form", "Application Form / Registration Portal"))
                else:
                    page.close()
                    context.close()
                    return False, "REJECTED_NO_APPLY_ACTION: No visible active public application button or registration form found"

            # 3. Minimum Content Gate
            if len(body_text.strip()) < 150:
                page.close()
                context.close()
                return False, f"REJECTED_BLANK_OR_UNLISTED: ATS page has no rendered content (len: {len(body_text.strip())})"

            page.close()
            context.close()
            return True, f"VERIFIED_ACTIVE: Found action '{valid_apply_buttons[0][1]}'"

        except Exception as e:
            return False, f"REJECTED_LOAD_FAILED: {type(e).__name__} ({str(e)[:80]})"


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, application/xhtml+xml, application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SOCIAL_BLACKLIST = [
    'telegram', 'instagram', 'whatsapp', 'youtube', 'facebook', 
    'twitter', 'freshersdunia.in', 't.me', 'bit.ly/freshersdunia', '#'
]

CSV_HEADERS = [
    "Job Title",
    "Company",
    "Location",
    "Company / Offline Venue Address",
    "Role",
    "Date Posted",
    "Experience",
    "Min Salary",
    "Max Salary",
    "Apply URL",
    "Fallback / Clean URL",
    "Link Health Status",
    "Source",
    "Last Updated",
    "skills/responsibilities",
    "Interview QnA doc",
    "Application Last Date",
    "All Apply Links",
]

DOMAIN_COMPANY_MAP = {
    # Company-owned private domains (any mismatch is a genuine copy-paste error)
    "deloitte.com": ["deloitte"],
    "infosys.com": ["infosys"],
    "wipro.com": ["wipro"],
    "jio.com": ["jio", "reliance"],
    "amazon.jobs": ["amazon"],
    "accenture.com": ["accenture"],
    "capgemini.com": ["capgemini"],
    # Known tenant subdomains on shared multi-tenant ATS platforms
    # (Never key on bare shared roots like oraclecloud.com/eightfold.ai/peoplestrong.com)
    "larsentoubrocareers.peoplestrong.com": ["larsen", "toubro", "l&t"],
    "paypal.eightfold.ai": ["paypal", "eightfold"],
    "jpmc.fa.oraclecloud.com": ["jpmorgan", "j.p. morgan", "jpmc"],
    "ejgk.fa.em2.oraclecloud.com": ["kpmg"],
}

COMPANY_PORTAL_FALLBACKS = {
    "larsen & toubro": "https://larsentoubrocareers.peoplestrong.com/",
    "deloitte": "https://southasiacareers.deloitte.com/",
    "deloitte touche tohmatsu india llp": "https://southasiacareers.deloitte.com/",
    "reliance jio": "https://careers.jio.com/",
    "reliance jio infocomm ltd.": "https://careers.jio.com/",
    "wipro limited": "https://careers.wipro.com/",
    "wipro": "https://careers.wipro.com/",
    "infosys": "https://career.infosys.com/",
    "infosys bpm limited": "https://career.infosys.com/",
    "mouser electronics": "https://www.mouser.in/careers/",
    "kpmg": "https://www.kpmgcareers.co.uk/experienced-professionals/",
    "paypal": "https://paypal.eightfold.ai/careers",
}

def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()

def parse_experience_info(exp_str: str, title: str = "") -> Dict[str, Any]:
    text = (exp_str + " " + title).lower()
    
    # If explicitly marked for experienced professionals without 0-year fresher clause, reject
    if ('experienced' in text or 'experienced professionals' in text) and not any(f in text for f in ['0 years', '0-1', '0-2', '0 to 1', '0 to 2', 'freshers eligible', 'freshers allowed', 'freshers welcome', 'fresher (0', '0 to 4']):
        return {"min_years": 2, "max_years": 5, "is_fresher": False}

    has_fresher_mention = bool(re.search(r'\b(fresher|freshers|entry[-\s]level|trainee|intern|graduate engineer trainee|\bget\b|off[-\s]campus|campus|batch\s*20\d\d)\b', text))
    
    m_range = re.search(r'(\d+)\s*(?:to|-|–)\s*(\d+)\s*(?:years?|yrs?)', exp_str.lower())
    if m_range:
        min_y = int(m_range.group(1))
        max_y = int(m_range.group(2))
        is_fresher = (min_y == 0) or (has_fresher_mention and min_y <= 1) or (max_y <= 2)
        return {"min_years": min_y, "max_years": max_y, "is_fresher": is_fresher}

    m_single = re.search(r'(\d+)\+?\s*(?:years?|yrs?)', exp_str.lower())
    if m_single:
        y = int(m_single.group(1))
        is_fresher = (y <= 1) or (has_fresher_mention and y <= 2)
        return {"min_years": y, "max_years": y, "is_fresher": is_fresher}

    if has_fresher_mention:
        return {"min_years": 0, "max_years": 0, "is_fresher": True}

    return {"min_years": None, "max_years": None, "is_fresher": False}

def parse_salary_components(salary_str: str) -> Tuple[str, str]:
    if not salary_str:
        return ("Not Disclosed", "Not Disclosed")
    s = salary_str.strip()
    m = re.search(r'([₹$€£]?\s*[\d\.\,]+\s*(?:lpa|k|lakhs?|per month|month|pm)?)\s*(?:to|-|–)\s*([₹$€£]?\s*[\d\.\,]+\+?\s*(?:lpa|k|lakhs?|per month|month|pm)?)', s, re.I)
    if m:
        min_s = m.group(1).strip()
        max_s = m.group(2).strip()
        if re.search(r'lpa|k|lakh|month', max_s, re.I) and not re.search(r'lpa|k|lakh|month', min_s, re.I):
            unit_match = re.search(r'(lpa|k|lakhs?|per month|month|pm)', max_s, re.I)
            if unit_match:
                min_s = f"{min_s} {unit_match.group(0)}"
        return (min_s, max_s)
    m_up = re.search(r'up\s*to\s*([₹$€£]?\s*[\d\.\,]+\+?\s*(?:lpa|k|lakhs?|per month|month|pm)?)', s, re.I)
    if m_up:
        return ("Not Disclosed", m_up.group(1).strip())
    return (s, s)

def check_application_deadline(last_date_str: str, reference_date: Optional[date] = None) -> Tuple[bool, str, str]:
    if not last_date_str:
        return False, "ASAP (Rolling / Open Until Filled)", "No deadline specified; treated as open"
    
    clean = re.sub(r'\(.*?\)', '', last_date_str).strip()
    clean_lower = clean.lower()
    
    if any(w in clean_lower for w in ['asap', 'rolling', 'open', 'not specified', 'not disclosed', 'quickly', 'immediate']):
        return False, "ASAP (Rolling / Open Until Filled)", "Active rolling deadline"

    today = reference_date or datetime.now().date()
    try:
        parsed_dt = date_parser.parse(clean, fuzzy=True, dayfirst=True)
        deadline_date = parsed_dt.date()
        if deadline_date < today:
            return True, str(deadline_date), f"EXPIRED: Cutoff date ({deadline_date}) < Today ({today})"
        else:
            return False, str(deadline_date), f"VALID: Cutoff date ({deadline_date}) >= Today ({today})"
    except Exception:
        m_yr = re.search(r'\b(20\d\d)\b', clean)
        if m_yr and int(m_yr.group(1)) < today.year:
            return True, clean, f"EXPIRED: Stated year {m_yr.group(1)} < current year {today.year}"
        return False, clean, f"Unparseable date '{clean}' treated as active"

def validate_and_diagnose_link(company: str, primary_url: str, job_id: str = "") -> Tuple[str, str, str]:
    """
    Evaluates the apply link, checks company-domain alignment, detects known failure patterns,
    and constructs a clean fallback career URL if the direct link is flawed.
    Returns: (final_apply_url, fallback_clean_url, health_status)
    """
    if not primary_url or not primary_url.startswith("http"):
        return "", "", "MISSING_OR_INVALID_URL"

    company_key = company.lower().strip()
    fallback_url = COMPANY_PORTAL_FALLBACKS.get(company_key, "")
    
    parsed = urlparse(primary_url)
    domain = parsed.netloc.lower()
    
    # Check 1: Publisher Copy-Paste Error (Domain Mismatch)
    for domain_key, valid_names in DOMAIN_COMPANY_MAP.items():
        if domain_key in domain:
            if not any(vn in company_key for vn in valid_names):
                # Mismatch detected! (e.g. Deloitte job linking to Infosys)
                msg = f"PUBLISHER_ERROR: Link points to '{domain}' but company is '{company}'"
                if job_id and "deloitte" in company_key:
                    fallback_url = f"https://southasiacareers.deloitte.com/search/?q={job_id}"
                elif not fallback_url:
                    fallback_url = f"https://www.google.com/search?q={company}+careers"
                return primary_url, fallback_url, msg

    # Check 2: Session-Gated URLs (e.g., Reliance Jio)
    if "jio.com" in domain and "frmjobdescription.aspx" in primary_url:
        fallback_jio = "https://careers.jio.com/"
        return primary_url, fallback_jio, "SESSION_GATED: Requires direct navigation from careers.jio.com (ASP.NET state)"

    # Check 3: PeopleStrong ATS (e.g., L&T - verified active direct requisition)
    if "peoplestrong.com" in domain and "/job/detail/" in primary_url:
        fallback_lt = "https://larsentoubrocareers.peoplestrong.com/"
        return primary_url, fallback_lt, "VERIFIED_ACTIVE"

    # Default: Domain aligns and standard ATS
    if not fallback_url:
        fallback_url = f"https://{domain}"

    return primary_url, fallback_url, "VERIFIED_ACTIVE"

def extract_address_and_venue(soup, table_kvs: Optional[Dict[str, str]] = None, apply_url: str = "", base_location: str = "") -> Tuple[str, str]:
    """
    Extracts offline venue, company office address, campus address, or drive location.
    Returns: (enriched_location, specific_address_venue)
    """
    table_kvs = table_kvs or {}
    specific_venue = ""

    # 1. Search table / overview grid key-value pairs
    venue_table_keys = [
        'venue', 'walk-in venue', 'walkin venue', 'drive venue', 'interview venue',
        'address', 'office address', 'company address', 'reporting address', 'plant address',
        'drive location', 'interview location', 'reporting venue', 'campus address',
        'work address', 'facility address', 'test venue'
    ]
    for k, v in table_kvs.items():
        k_clean = k.lower().strip()
        for vtk in venue_table_keys:
            if vtk in k_clean and len(v.strip()) > 3:
                specific_venue = v.strip()
                break
        if specific_venue:
            break

    # 2. Search body text using regex for walk-in or offline drive venues
    if not specific_venue and soup:
        text = soup.get_text(' ', strip=True) if hasattr(soup, 'get_text') else str(soup)
        patterns = [
            r'(?:walk[-\s]?in\s*(?:venue|address)|interview\s*venue|drive\s*venue|reporting\s*(?:venue|address)|company\s*address|office\s*address|campus\s*address|plant\s*(?:location|address)|venue\s*(?:details|address)?|interview\s*location|drive\s*location)[:\s]+([^\n\<\>]{8,200})',
            r'(?:venue|address)\s*for\s*(?:the\s*)?(?:walk[-\s]?in|interview|drive|exam|test)[:\s]+([^\n\<\>]{8,200})'
        ]
        for pat in patterns:
            m = re.search(pat, text, re.I)
            if m:
                cand = m.group(1).strip()
                cand = re.split(r'[\.\;\n]|\bNote\b|\bPlease\b|\bCandidates\b|\bBring\b|\bDate\b', cand)[0].strip()
                if len(cand) >= 5 and not any(bad in cand.lower() for bad in ['http', 'click here', 'apply online', 'telegram']):
                    specific_venue = cand
                    break

    # 3. Extract from ATS URL facility tokens (e.g. Workday location path)
    if not specific_venue and apply_url:
        m_wd = re.search(r'/job/(?:India---)?([^/]+)/\w+', apply_url)
        if m_wd:
            parts = re.split(r'-{2,3}', m_wd.group(1))
            clean_parts = [p.replace('-', ' ').strip() for p in parts if p.strip()]
            if len(clean_parts) >= 2:
                specific_venue = ', '.join(clean_parts)

    # 4. Synthesize Enriched Location
    loc = base_location.strip()
    if specific_venue:
        if loc and loc.lower() not in specific_venue.lower() and loc.lower() not in ['not disclosed', 'pan india', 'multiple', 'across india']:
            enriched_loc = f"{loc} ({specific_venue})"
        else:
            enriched_loc = specific_venue
    else:
        enriched_loc = loc if loc and loc.lower() != 'not disclosed' else 'Pan India / Multiple'
        specific_venue = enriched_loc

    return enriched_loc, specific_venue


def extract_job_fields(html_content: str, title: str, url: str, pub_date: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_content, 'html.parser')
    tables = soup.find_all('table')
    
    table_kvs = {}
    for table in tables:
        for tr in table.find_all('tr'):
            cols = tr.find_all(['th', 'td'])
            if len(cols) >= 2:
                k = clean_text(cols[0].get_text()).lower()
                v = clean_text(cols[1].get_text())
                if k and v:
                    table_kvs[k] = v

    def get_table_val(patterns: List[str]) -> Optional[str]:
        for pat in patterns:
            regex = re.compile(pat, re.I)
            for k, v in table_kvs.items():
                if regex.search(k):
                    return v
        return None

    # 1. Company Name
    company = get_table_val([r'^company(\s*name)?$']) or ""
    if not company:
        m = re.match(r'^([^–\-\|]+)(?:Careers|Recruitment|Off Campus|Hiring)', title, re.I)
        if m:
            company = clean_text(m.group(1))

    # 2. Role / Job Title
    role = get_table_val([r'^(official\s*)?job\s*(title|role|roles)$', r'^job\s*role$', r'^role$']) or ""
    if not role:
        m = re.search(r'(?:–|-|Hiring|Role)\s*([^–\-\|]+?)(?:\||–|-|Freshers|Apply|\d+–\d+)', title, re.I)
        if m:
            role = clean_text(m.group(1))

    # 3. Job ID / Requisition ID
    job_id = get_table_val([r'job\s*(requisition\s*)?id', r'reference\s*code', r'job\s*identification']) or ""

    # 4. Experience Required
    exp_req = get_table_val([r'^experience(\s*required)?$', r'^experience$']) or ""
    if not exp_req:
        exp_req = get_table_val([r'professional\s*requirement', r'eligibility']) or ""

    # 5. Educational Qualification
    education = get_table_val([r'(educational\s*)?qualification', r'eligible\s*batches', r'academic\s*rule']) or ""

    # 6. Core Skills (Table 1 -> Fallback to headings)
    skills = get_table_val([r'skills|tech(nical)?\s*stack|domain\s*skills|competenc']) or ""
    if not skills:
        h = soup.find(lambda tag: tag.name in ['h2', 'h3', 'h4'] and 'skill' in tag.get_text().lower())
        if h:
            nxt = h.find_next_sibling()
            skills_texts = []
            while nxt and nxt.name not in ['h2', 'h3', 'h4']:
                txt = clean_text(nxt.get_text())
                if txt and 'adsbygoogle' not in txt:
                    skills_texts.append(txt)
                nxt = nxt.find_next_sibling()
            if skills_texts:
                skills = " | ".join(skills_texts[:2])[:250]

    # Extract All External Apply Links (Purged of Socials) First
    apply_links = []
    if len(tables) > 1:
        for a in tables[1].find_all('a', href=True):
            href = a['href'].strip()
            txt = clean_text(a.get_text())
            if href and not any(b in href.lower() for b in SOCIAL_BLACKLIST):
                apply_links.append({"label": txt or "Apply Link", "url": href})
                
    if not apply_links:
        for t in tables:
            for a in t.find_all('a', href=True):
                href = a['href'].strip()
                txt = clean_text(a.get_text())
                if href and not any(b in href.lower() for b in SOCIAL_BLACKLIST):
                    if any(w in txt.lower() for w in ['apply', 'click', 'register']) or 'job' in href.lower() or 'career' in href.lower():
                        apply_links.append({"label": txt or "Apply Link", "url": href})

    if not apply_links:
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            txt = clean_text(a.get_text())
            if href and not any(b in href.lower() for b in SOCIAL_BLACKLIST):
                if any(w in txt.lower() for w in ['apply online', 'official application link', 'click here to apply']):
                    apply_links.append({"label": txt or "Apply Link", "url": href})

    raw_primary_url = apply_links[0]["url"] if apply_links else url

    # 7. Job Location & Offline Drive / Venue Address
    base_loc = get_table_val([r'^(job\s*)?locations?$']) or "Pan India / Multiple"
    enriched_loc, venue_address = extract_address_and_venue(
        soup=soup,
        table_kvs=table_kvs,
        apply_url=raw_primary_url,
        base_location=base_loc
    )

    # 8. Salary / CTC / Stipend
    salary = get_table_val([r'salary|stipend|ctc']) or ""
    if not salary:
        m = re.search(r'(?:salary|stipend|ctc)[^\d]*([₹$€£\d\.\,\-]+\s*(?:lpa|k|per month|lakhs?|pm)?)', title, re.I)
        if m:
            salary = m.group(0).strip()
        else:
            salary = "Not Disclosed / Best in Industry"

    # 9. APPLICATION LAST DATE
    last_date = get_table_val([r'last\s*date|end\s*date|deadline|closing\s*date'])
    if not last_date:
        body_text = clean_text(soup.get_text(separator=' '))
        m = re.search(r'(?:last\s*date\s*(?:to\s*apply)?|application\s*(?:end\s*date|deadline)|apply\s*before)[:\s]+([^\n\.\,]+)', body_text, re.I)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) < 40 and not any(x in candidate.lower() for x in ['telegram', 'how to apply', 'click']):
                last_date = candidate
    if not last_date:
        last_date = "ASAP (Rolling / Open Until Filled)"

    # 11. Run Link Diagnostics & Cross-Domain Validation
    clean_apply_url, fallback_clean_url, link_health = validate_and_diagnose_link(
        company=company,
        primary_url=raw_primary_url,
        job_id=job_id
    )

    exp_info = parse_experience_info(exp_req, title)
    min_sal, max_sal = parse_salary_components(salary)
    all_links_str = " | ".join([f"{lnk['label']}: {lnk['url']}" for lnk in apply_links])

    return {
        "job_title": title,
        "company": company,
        "location": enriched_loc,
        "venue_address": venue_address,
        "role": role or title,
        "date_posted": pub_date.split("T")[0] if "T" in pub_date else pub_date,
        "experience": exp_req or "Fresher (0 Years)",
        "min_exp_years": exp_info["min_years"],
        "max_exp_years": exp_info["max_years"],
        "is_fresher": exp_info["is_fresher"],
        "min_salary": min_sal,
        "max_salary": max_sal,
        "raw_salary": salary,
        "qualification": education,
        "skills": skills or "Basic Technical Fundamentals",
        "application_last_date": last_date,
        "apply_url": clean_apply_url,
        "fallback_url": fallback_clean_url,
        "link_health": link_health,
        "all_apply_links": all_links_str,
        "freshersdunia_url": url,
        "published_at": pub_date
    }

def save_jobs_to_csv(jobs: List[Dict[str, Any]], csv_path: str = DEFAULT_CSV_PATH) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for j in jobs:
            writer.writerow({
                "Job Title": j["job_title"],
                "Company": j["company"],
                "Location": j["location"],
                "Company / Offline Venue Address": j.get("venue_address") or j.get("location"),
                "Role": j["role"],
                "Date Posted": j["date_posted"],
                "Experience": j["experience"],
                "Min Salary": j["min_salary"],
                "Max Salary": j["max_salary"],
                "Apply URL": j["apply_url"],
                "Fallback / Clean URL": j["fallback_url"],
                "Link Health Status": j["link_health"],
                "Source": "FRESHERSDUNIA",
                "Last Updated": datetime.now().isoformat(timespec="seconds"),
                "skills/responsibilities": j["skills"],
                "Interview QnA doc": "",
                "Application Last Date": j["application_last_date"],
                "All Apply Links": j["all_apply_links"]
            })

    total_rows = len(jobs)
    logger.info(f"Saved to CSV [{csv_path}]. Total verified active rows: {total_rows}.")
    return total_rows

def harvest_freshersdunia_jobs(
    hours_lookback: int = 168, 
    per_page: int = 30, 
    csv_path: str = DEFAULT_CSV_PATH,
    reference_date: Optional[date] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    since_dt = datetime.now(timezone.utc) - timedelta(hours=hours_lookback)
    after_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    
    params = {
        "per_page": per_page,
        "page": 1,
        "after": after_iso
    }
    logger.info(f"Connecting to FreshersDunia REST API (Lookback: {hours_lookback}h, after: {after_iso})...")
    
    posts = []
    try:
        resp = requests.get(WP_API_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            posts = resp.json()
    except Exception:
        pass

    if not posts:
        logger.info("Requests blocked or failed. Invoking browser-grade curl pipeline for WordPress REST API...")
        query_str = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        curl_cmd = [
            'curl.exe', '-s',
            '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            '-H', 'Accept: application/json',
            f"{WP_API_URL}{query_str}"
        ]
        res = subprocess.run(curl_cmd, capture_output=True, text=True, encoding='utf-8')
        try:
            posts = json.loads(res.stdout)
        except Exception as e:
            logger.error(f"Failed to fetch posts via curl: {e}")
            return [], {"total_posts_fetched": 0, "accepted_jobs": 0, "rejected_experienced": 0, "rejected_expired_deadline": 0, "error": str(e)}

    stats = {
        "total_posts_fetched": len(posts),
        "rejected_experienced": 0,
        "rejected_expired_deadline": 0,
        "accepted_jobs": 0,
        "rejections": []
    }
    
    accepted_jobs = []
    today = reference_date or datetime.now().date()
    logger.info(f"Evaluating {len(posts)} posts against guardrails (Reference Today: {today})...")

    verifier = ATSVerifier()
    try:
        for p in posts:
            title = p["title"]["rendered"]
            url = p["link"]
            pub_date = p["date"]
            
            job = extract_job_fields(
                html_content=p["content"]["rendered"],
                title=title,
                url=url,
                pub_date=pub_date
            )

            # Guardrail 1: Fresher Eligibility
            if not job["is_fresher"]:
                stats["rejected_experienced"] += 1
                reason = f"Experience required ({job['experience']}) exceeds fresher threshold"
                stats["rejections"].append({"title": title, "reason": reason})
                logger.info(f"[-] REJECTED (EXPERIENCED): {title} -> {reason}")
                continue

            # Guardrail 2: Application Last Date (< today's date)
            is_expired, normalized_deadline, deadline_msg = check_application_deadline(
                job["application_last_date"], 
                reference_date=today
            )
            if is_expired:
                stats["rejected_expired_deadline"] += 1
                stats["rejections"].append({"title": title, "reason": deadline_msg})
                logger.info(f"[-] REJECTED (EXPIRED DEADLINE): {title} -> {deadline_msg}")
                continue

            # Guardrail 3: Strict Link Health Gate
            if any(bad in job["link_health"] for bad in ["EXPIRED", "DEAD", "HTTP 410", "HTTP 404", "PUBLISHER_ERROR", "PUBLISHER_MISMATCH", "SESSION_GATED"]):
                stats["rejections"].append({"title": title, "reason": f"Link Health Gate Failed: {job['link_health']}"})
                logger.warning(f"[-] REJECTED (LINK HEALTH): {title} -> {job['link_health']}")
                continue

            # Guardrail 4: Deep Destination ATS Portal Verification
            is_active, ats_reason = verifier.verify_ats_url(job["apply_url"])
            if not is_active:
                stats["rejections"].append({"title": title, "reason": f"ATS Inactive/Closed: {ats_reason}"})
                logger.warning(f"[-] REJECTED (ATS POSITION CLOSED): {title} -> {ats_reason}")
                continue

            job["application_last_date"] = normalized_deadline
            accepted_jobs.append(job)
            stats["accepted_jobs"] += 1
            logger.info(f"[+] ACCEPTED: {job['company']} | {job['role']} | Link Status: {job['link_health']}")

        if accepted_jobs:
            save_jobs_to_csv(accepted_jobs, csv_path=csv_path)

        return accepted_jobs, stats
    finally:
        verifier.close()

if __name__ == '__main__':
    jobs, stats = harvest_freshersdunia_jobs(hours_lookback=168, per_page=35)
    print("\n" + "="*80)
    print(f"HARVEST EXECUTION SUMMARY:")
    print(f"  Total Fetched               : {stats['total_posts_fetched']}")
    print(f"  Rejected (Experienced)      : {stats['rejected_experienced']}")
    print(f"  Rejected (Expired Deadline) : {stats['rejected_expired_deadline']}")
    print(f"  Accepted & Saved to CSV     : {stats['accepted_jobs']}")
    print("="*80)
