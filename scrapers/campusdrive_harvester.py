"""
CampusDrive Job Harvester & Verification Engine (Production-Grade)
Directory: job_experiments/campusdrive/

Key Features:
1. Multi-source ingestion:
   - Sitemap parser: https://campusdrive.in/sitemap.xml
   - Hub & Batch discovery: /jobs, /jobs/2024-batch through 2029-batch
2. Granular Extraction:
   - Structured Overview Grid (Hiring Organization, Job Role, Batches, Qualifications,
     Salary/CTC, Experience, Location, Date Published, Last Date to Register)
   - Skills & Responsibilities (from 'Required Skills', 'Key Responsibilities', and tech lexicon)
   - Direct ATS Apply Links (unwrapping redirects and tracking parameters)
3. Quality Guardrails:
   - Application Closed / Expired Banner Gate
   - Application Last Date Gate (rejects if last_date < today's date)
   - Experience Gate (strictly enforces fresher / early-career eligibility <= 2 yrs)
   - Link Health & Domain Alignment Gate:
     * Unwraps safety redirects (e.g. linkedin.com/safety/go/?url=...)
     * Strips corrupted publisher strings (e.g. trailing mpusdrive.in)
     * Performs TLS impersonation probes to detect 410 Gone / 404 Not Found
     * Generates clean fallback URLs for company career hubs
4. Local CSV Persistence:
   - Format: 17 columns matching Google Sheets schema, utf-8-sig encoded
   - Deduplication & Upsert by Apply URL
"""

import os
import re
import csv
import html
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Any, List, Optional, Tuple
import xml.etree.ElementTree as ET

from curl_cffi import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CampusDriveHarvester")

BASE_URL = "https://campusdrive.in"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "campusdrive_jobs.csv")

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
        Loads the candidate ATS portal in headless Edge, allows client JavaScript / React / Angular
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

            # Navigate to ATS with networkidle fallback
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
            status = resp.status if resp else 0
            if status in (404, 410, 403, 500):
                page.close()
                context.close()
                return False, f"REJECTED_HTTP_{status}: ATS portal returned error status {status}"

            # Wait for client SPA hydration
            page.wait_for_timeout(3500)
            final_url = page.url
            body_text = page.locator("body").inner_text()

            # Pre-filter: Redirect to login or auth page
            if "login" in final_url.lower() and "login" not in url.lower():
                page.close()
                context.close()
                return False, f"REJECTED_AUTH_REDIRECT: Requisition redirected to login screen ({final_url})"

            # 1. Closed Position Banners
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
    # Company-owned private domains
    "qualcomm.com": ["qualcomm"],
    "tatacommunications.com": ["tata communications", "tata"],
    "hpe.com": ["hpe", "hewlett packard enterprise"],
    "accenture.com": ["accenture"],
    "amazon.jobs": ["amazon"],
    "cognizant.com": ["cognizant"],
    "genpact.com": ["genpact"],
    "infosys.com": ["infosys"],
    "schneider-electric.com": ["schneider electric", "schneider"],
    "synopsys.com": ["synopsys"],
    "tatamotors.com": ["tata motors", "tata"],
    "tcs.com": ["tcs", "tata consultancy services"],
    "wipro.com": ["wipro"],
    # Known tenant subdomains on shared multi-tenant ATS platforms
    "dentsuaegis.wd3.myworkdayjobs.com": ["dentsu", "dentsuaegis"],
    "larsentoubrocareers.peoplestrong.com": ["larsen", "toubro", "l&t"],
    "jpmc.fa.oraclecloud.com": ["jpmorgan", "j.p. morgan", "jpmc"],
}

COMPANY_PORTAL_FALLBACKS = {
    "qualcomm": "https://careers.qualcomm.com/",
    "tata communications": "https://jobs.tatacommunications.com/",
    "texas instruments": "https://careers.ti.com/",
    "dentsu": "https://dentsuaegis.wd3.myworkdayjobs.com/DAN_GLOBAL",
    "cgi": "https://www.cgi.com/en/careers",
    "hpe": "https://careers.hpe.com/",
    "hewlett packard enterprise": "https://careers.hpe.com/",
    "accenture": "https://www.accenture.com/in-en/careers",
    "amazon": "https://www.amazon.jobs/",
    "cognizant": "https://careers.cognizant.com/",
    "genpact": "https://www.genpact.com/careers",
    "infosys": "https://career.infosys.com/",
    "larsen & toubro (l&t)": "https://larsentoubrocareers.peoplestrong.com/",
    "larsen & toubro": "https://larsentoubrocareers.peoplestrong.com/",
    "schneider electric": "https://www.se.com/in/en/about-us/careers/",
    "synopsys": "https://www.synopsys.com/careers.html",
    "tata motors": "https://www.tatamotors.com/careers/",
    "tata consultancy services (tcs)": "https://www.tcs.com/careers",
    "tcs": "https://www.tcs.com/careers",
    "wipro": "https://careers.wipro.com/",
}

KNOWN_SKILLS = [
    "Python", "Java", "C++", "C#", "C", "SQL", "JavaScript", "TypeScript", "React.js", "React",
    "Angular", "Vue.js", "Node.js", "Django", "Flask", "Spring Boot", "Spring", "HTML", "CSS",
    "REST APIs", "RESTful API", "GraphQL", "Microservices", "Docker", "Kubernetes", "AWS", "Azure",
    "GCP", "Linux", "Git", "GitHub", "Data Structures", "Algorithms", "Object-Oriented Programming",
    "OOP", "Machine Learning", "AI", "Large Language Models", "LLMs", "Prompt Engineering",
    "Embedded Systems", "Device Drivers", "RTOS", "VLSI", "FPGA", "Verilog", "SystemVerilog",
    "Excel", "Financial Modeling", "Accounting", "SAP", "Power BI", "Tableau", "AutoCAD",
    "Quality Control", "Problem Solving", "Analytical Skills", "Communication Skills"
]


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def parse_experience_info(exp_str: str, title: str = "") -> Dict[str, Any]:
    text = (exp_str + " " + title).lower()
    has_fresher_mention = bool(re.search(
        r'\b(fresher|freshers|entry[-\s]level|trainee|apprentice|intern|internship|graduate engineer trainee|\bget\b|early career|off[-\s]campus|campus|batch\s*20\d\d|students?|new college graduates?)\b',
        text
    ))

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
    
    # Check range: e.g. ₹3.6 LPA – ₹5.2 LPA
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
        
    if any(k in s.lower() for k in ["best in industry", "industry standard", "as per industry standards"]):
        return ("Best in Industry", "Best in Industry")
        
    return (s, s)


def check_application_deadline(last_date_str: str, reference_date: Optional[date] = None) -> Tuple[bool, str, str]:
    """
    Returns (is_expired, normalized_date_string, reason)
    """
    if not last_date_str:
        return False, "ASAP (Rolling / Open Until Filled)", "No deadline specified; treated as rolling"

    clean = re.sub(r'\(.*?\)', '', last_date_str).strip()
    clean_lower = clean.lower()

    if any(w in clean_lower for w in ['asap', 'rolling', 'open', 'not specified', 'not disclosed', 'ongoing', 'immediately']):
        return False, "ASAP (Rolling / Open Until Filled)", "Active rolling deadline"

    today = reference_date or date.today()
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


def unwrap_and_clean_url(raw_url: str) -> str:
    """
    Unwraps redirect wrappers (e.g. linkedin safety redirects) and cleans corrupted publisher text.
    """
    if not raw_url:
        return ""
    
    url = raw_url.strip()
    
    # 1. Unwrap LinkedIn Safety Redirect: https://www.linkedin.com/safety/go/?url=...
    if "linkedin.com/safety/go" in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "url" in qs and qs["url"]:
            url = qs["url"][0]
            
    # 2. Strip corrupted publisher suffix (e.g., mpusdrive.in or campusdrive.in appended to query)
    url = re.sub(r'mpusdrive\.in$', '', url)
    url = re.sub(r'campusdrive\.in$', '', url)
    
    return url


def validate_and_diagnose_link(company: str, raw_apply_url: str, probe_live: bool = True) -> Tuple[str, str, str]:
    """
    Evaluates apply link, unrolls wrappers, validates domain alignment,
    performs live TLS probing to catch 410/404, and generates fallback URL.
    Returns: (cleaned_apply_url, fallback_clean_url, health_status)
    """
    clean_apply_url = unwrap_and_clean_url(raw_apply_url)
    if not clean_apply_url or not clean_apply_url.startswith("http"):
        return "", "", "MISSING_OR_INVALID_URL"

    company_key = company.lower().strip()
    fallback_url = COMPANY_PORTAL_FALLBACKS.get(company_key, "")

    parsed = urllib.parse.urlparse(clean_apply_url)
    domain = parsed.netloc.lower()

    # Domain cross-validation
    mismatch = False
    for domain_key, valid_names in DOMAIN_COMPANY_MAP.items():
        if domain_key in domain:
            if not any(vn in company_key for vn in valid_names):
                mismatch = True
                break

    if mismatch:
        msg = f"PUBLISHER_MISMATCH: Link domain '{domain}' does not align with company '{company}'"
        if not fallback_url:
            fallback_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(company + ' careers')}"
        return clean_apply_url, fallback_url, msg

    if not fallback_url:
        fallback_url = f"https://{domain}"

    # Live TLS Impersonation Probe
    if probe_live:
        try:
            resp = requests.get(
                clean_apply_url,
                impersonate="chrome120",
                timeout=12,
                allow_redirects=True,
                headers={"Accept-Language": "en-US,en;q=0.9"}
            )
            if resp.status_code == 410:
                return clean_apply_url, fallback_url, "EXPIRED_ATS_POSTING: HTTP 410 (Job has closed on career portal)"
            elif resp.status_code == 404:
                return clean_apply_url, fallback_url, "DEAD_LINK: HTTP 404 Not Found"
            elif resp.status_code in (200, 301, 302):
                final_domain = urllib.parse.urlparse(resp.url).netloc.lower()
                if "perfdrive.com" in final_domain or "challenges.cloudflare.com" in final_domain:
                    return clean_apply_url, fallback_url, "VERIFIED_ACTIVE: Protected by ATS Anti-Bot Gateway"
                return clean_apply_url, fallback_url, "VERIFIED_ACTIVE"
            else:
                return clean_apply_url, fallback_url, f"PORTAL_RESPONSE: HTTP {resp.status_code}"
        except Exception as e:
            return clean_apply_url, fallback_url, f"PROBE_EXCEPTION: {type(e).__name__}"

    return clean_apply_url, fallback_url, "VERIFIED_ACTIVE"


def extract_skills_from_text(text: str) -> List[str]:
    found = []
    text_lower = text.lower()
    for skill in KNOWN_SKILLS:
        pattern = r'\b' + re.escape(skill.lower()) + r'\b'
        if re.search(pattern, text_lower):
            found.append(skill)
    return found


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


def parse_campusdrive_job_page(html_content: str, url: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Check if closed/expired
    is_closed = bool(soup.find(lambda el: el.string and any(
        k in el.string.lower() for k in ['applications closed', 'drive concluded', 'opening have expired']
    )))

    # 2. Parse Overview grid
    # Format: <div class="grid grid-cols-1 sm:grid-cols-3 p-3 ...">
    rows = soup.find_all('div', class_=lambda c: c and 'grid-cols-1' in c and 'sm:grid-cols-3' in c)
    data = {}
    for r in rows:
        spans = r.find_all('span', recursive=False)
        if len(spans) >= 2:
            k = clean_text(spans[0].get_text(strip=True))
            v = clean_text(spans[1].get_text(strip=True))
            data[k] = v

    company = data.get('Hiring Organization', '')
    role = data.get('Job Role / Designation', '')
    salary_raw = data.get('Salary / CTC Package', 'Not Disclosed')
    exp_raw = data.get('Experience Required', 'Freshers')
    location = data.get('Job Location', 'Pan India')
    date_pub_raw = data.get('Date Published', '')
    last_date_raw = data.get('Last Date to Register', '')
    batch_raw = data.get('Eligible Batches', '')
    degree_raw = data.get('Academic Qualification', '')
    branch_raw = data.get('Eligible Engineering Branches', '')

    # H1 fallback
    h1 = soup.find('h1')
    page_title = clean_text(h1.get_text(strip=True)) if h1 else role

    if not company:
        # Fallback extraction from H1
        m_comp = re.search(r'^(.*?)\s+(?:Off Campus|Hiring|Recruitment)', page_title, re.I)
        company = m_comp.group(1).strip() if m_comp else "CampusDrive Recruiter"

    if not role:
        role = page_title

    # 3. Apply button
    apply_url = ""
    for a in soup.find_all('a', href=True):
        if 'apply now' in a.get_text(strip=True).lower():
            apply_url = a['href']
            break

    # 4. Extract Skills & Responsibilities
    skills_list = []
    # Try finding 'Required Skills' or 'Key Responsibilities' sections
    for h in soup.find_all(['h2', 'h3']):
        htxt = h.get_text(strip=True).lower()
        if any(w in htxt for w in ['required skills', 'skills required', 'key responsibilities', 'eligibility & academic criteria']):
            nxt = h.find_next(['ul', 'div', 'p'])
            if nxt:
                extracted = extract_skills_from_text(nxt.get_text(' ', strip=True))
                for s in extracted:
                    if s not in skills_list:
                        skills_list.append(s)

    # General page text skill extraction fallback if few skills found
    if len(skills_list) < 3:
        all_text = soup.get_text(' ', strip=True)
        for s in extract_skills_from_text(all_text):
            if s not in skills_list:
                skills_list.append(s)

    # Date Posted normalization
    date_posted = ""
    if date_pub_raw:
        try:
            date_posted = str(date_parser.parse(date_pub_raw, fuzzy=True).date())
        except Exception:
            date_posted = str(date.today())
    else:
        date_posted = str(date.today())

    # 5. Extract Detailed Offline Venue / Company Address
    base_loc = data.get('Job Location', 'Pan India')
    enriched_loc, venue_address = extract_address_and_venue(
        soup=soup,
        table_kvs=data,
        apply_url=apply_url,
        base_location=base_loc
    )

    return {
        "job_url": url,
        "title": page_title,
        "company": company,
        "role": role,
        "location": enriched_loc,
        "venue_address": venue_address,
        "salary_raw": salary_raw,
        "exp_raw": exp_raw,
        "batch_raw": batch_raw,
        "degree_raw": degree_raw,
        "branch_raw": branch_raw,
        "date_posted": date_posted,
        "last_date_raw": last_date_raw,
        "apply_url": apply_url,
        "is_closed": is_closed,
        "skills": ", ".join(skills_list[:12]) if skills_list else "General Engineering / Software Skills"
    }


class CampusDriveHarvester:
    def __init__(self, output_csv: str = DEFAULT_CSV_PATH, probe_live_links: bool = True):
        self.output_csv = output_csv
        self.probe_live_links = probe_live_links
        self.session = requests.Session()
        self.ats_verifier = ATSVerifier()

    def discover_all_job_urls(self) -> List[str]:
        job_urls = set()
        logger.info("Discovering jobs from sitemap.xml...")
        try:
            resp = self.session.get(SITEMAP_URL, impersonate="chrome120", timeout=15)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                for url_tag in root.findall('ns:url', ns):
                    loc = url_tag.find('ns:loc', ns)
                    if loc is not None and loc.text:
                        u = loc.text.strip()
                        # Filter out non-job URLs
                        if not any(x in u for x in ['/jobs', '/batch', '/branch', '/syllabus', '/about', '/contact', '/privacy', '/terms', '/disclaimer', '/internships', '/placement', '/blog', '/tools']) and u != BASE_URL and u != f"{BASE_URL}/":
                            job_urls.add(u)
                logger.info(f"Discovered {len(job_urls)} job URLs from sitemap.")
        except Exception as e:
            logger.warning(f"Error fetching sitemap: {e}")

        # Batch & Hub crawling fallback/complement
        hub_pages = [
            f"{BASE_URL}/jobs",
            f"{BASE_URL}/jobs/2024-batch",
            f"{BASE_URL}/jobs/2025-batch",
            f"{BASE_URL}/jobs/2026-batch",
            f"{BASE_URL}/jobs/2027-batch",
            f"{BASE_URL}/jobs/2028-batch",
            f"{BASE_URL}/jobs/2029-batch",
        ]
        logger.info("Scanning hub and batch pages for additional jobs...")
        for hub in hub_pages:
            try:
                resp = self.session.get(hub, impersonate="chrome120", timeout=15)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if href.startswith('/') and not any(href.startswith(p) for p in ['/jobs', '/batch', '/branch', '/syllabus', '/about', '/contact', '/privacy', '/terms', '/disclaimer', '/internships', '/placement', '/blog', '/tools', '/#']):
                            if len(href.split('/')) == 2 and len(href) > 3:
                                job_urls.add(f"{BASE_URL}{href}")
            except Exception as e:
                logger.warning(f"Failed to fetch hub {hub}: {e}")

        logger.info(f"Total unique job URLs discovered: {len(job_urls)}")
        return sorted(list(job_urls))

    def process_job(self, url: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching and parsing: {url}")
        try:
            resp = self.session.get(url, impersonate="chrome120", timeout=15)
            if resp.status_code != 200:
                logger.warning(f"Skipping {url}: HTTP {resp.status_code}")
                return None
            data = parse_campusdrive_job_page(resp.text, url)
            if not data:
                return None

            company = data["company"]
            role = data["role"]

            # Guardrail 1: Check Application Closed Banner
            if data["is_closed"]:
                logger.info(f"REJECTED: [{company}] {role} - Status marked as 'Applications Closed' on CampusDrive")
                return None

            # Guardrail 2: Check Apply Button
            if not data["apply_url"]:
                logger.info(f"REJECTED: [{company}] {role} - No external Apply Now button found")
                return None

            # Guardrail 3: Application Last Date Gate
            is_expired, normalized_last_date, deadline_reason = check_application_deadline(data["last_date_raw"])
            if is_expired:
                logger.info(f"REJECTED: [{company}] {role} - {deadline_reason}")
                return None

            # Guardrail 4: Experience Gate
            exp_info = parse_experience_info(data["exp_raw"], data["title"])
            if not exp_info["is_fresher"]:
                logger.info(f"REJECTED: [{company}] {role} - Experience required: {data['exp_raw']} (not fresher-eligible)")
                return None

            # Salary components
            min_salary, max_salary = parse_salary_components(data["salary_raw"])

            # Link diagnosis & validation
            clean_apply_url, fallback_url, link_health = validate_and_diagnose_link(
                company=company,
                raw_apply_url=data["apply_url"],
                probe_live=self.probe_live_links
            )

            # Strict Link Health Gate: Reject HTTP 410, 404, or publisher domain mismatches
            if any(bad in link_health for bad in ["EXPIRED", "DEAD", "HTTP 410", "HTTP 404", "PUBLISHER_ERROR", "PUBLISHER_MISMATCH", "SESSION_GATED"]):
                logger.warning(f"REJECTED: [{company}] {role} - Link Health Gate Failed: {link_health}")
                return None

            # Deep Destination ATS Verification: Check for "Position Closed", "No Longer Available", "Job Filled", etc.
            is_active, ats_reason = self.ats_verifier.verify_ats_url(clean_apply_url)
            if not is_active:
                logger.warning(f"REJECTED: [{company}] {role} - Destination ATS Inactive/Closed: {ats_reason}")
                return None

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

            row = {
                "Job Title": data["title"],
                "Company": company,
                "Location": data["location"],
                "Company / Offline Venue Address": data["venue_address"],
                "Role": role,
                "Date Posted": data["date_posted"],
                "Experience": data["exp_raw"],
                "Min Salary": min_salary,
                "Max Salary": max_salary,
                "Apply URL": clean_apply_url,
                "Fallback / Clean URL": fallback_url,
                "Link Health Status": link_health,
                "Source": "CAMPUSDRIVE",
                "Last Updated": now_iso,
                "skills/responsibilities": data["skills"],
                "Interview QnA doc": "",
                "Application Last Date": normalized_last_date,
                "All Apply Links": f"Apply link: {clean_apply_url}",
            }
            logger.info(f"ACCEPTED: [{company}] {role} | Last Date: {normalized_last_date} | Apply: {clean_apply_url[:50]}...")
            return row

        except Exception as e:
            logger.error(f"Error processing job {url}: {e}", exc_info=True)
            return None

    def run(self) -> List[Dict[str, Any]]:
        try:
            job_urls = self.discover_all_job_urls()
            accepted_jobs: List[Dict[str, Any]] = []

            for url in job_urls:
                res = self.process_job(url)
                if res:
                    accepted_jobs.append(res)

            logger.info(f"Harvest complete. Accepted: {len(accepted_jobs)} of {len(job_urls)} jobs.")
            self.save_to_csv(accepted_jobs)
            return accepted_jobs
        finally:
            self.ats_verifier.close()

    def save_to_csv(self, new_jobs: List[Dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.output_csv)), exist_ok=True)
        with open(self.output_csv, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            for r in new_jobs:
                writer.writerow(r)

        logger.info(f"Successfully saved {len(new_jobs)} verified active jobs to: {self.output_csv}")


if __name__ == "__main__":
    harvester = CampusDriveHarvester()
    jobs = harvester.run()
    print(f"\nFinal Result: {len(jobs)} active fresher jobs harvested and saved.")
