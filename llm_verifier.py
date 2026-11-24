"""
LLM Verifier & Skills Curator Module
====================================
Acts as the final intelligent gatekeeper for fresher jobs:
1. Extracts relevant requirements, qualifications, responsibilities, and experience sections from JDs.
2. Prompts LLM to strictly verify whether the role is genuine fresher (0 prior experience / 0-1 yr).
3. If experienced (>1 yr or prior professional work required), rejects the job.
4. If fresher, curates a concise list of concrete technical and domain skills (without fluff).
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
logger = logging.getLogger("LLMVerifier")

_CACHED_LLM = None


def get_groq_keys() -> list:
    """Returns a deduplicated list of active Groq API keys in priority order."""
    keys = []
    names = [
        "GROQ_API_KEY1", "GROQ_API_KEY_1",
        "GROQ_API_KEY2", "GROQ_API_KEY_2",
        "GROQ_API_KEY3", "GROQ_API_KEY_3",
        "GROQ_API_KEY",
    ]
    for n in names:
        val = os.getenv(n, "").strip().lstrip("#").strip("\"'")
        if val and not val.startswith("YOUR_") and not val.startswith("gsk_PLACEHOLDER") and val not in keys:
            keys.append(val)
    return keys


def get_openrouter_keys() -> list:
    """Returns a deduplicated list of active OpenRouter API keys in priority order."""
    keys = []
    names = [
        "OPENROUTER_API_KEY1", "OPENROUTER_API_KEY_1",
        "OPENROUTER_API_KEY2", "OPENROUTER_API_KEY_2",
        "OPENROUTER_API_KEY3", "OPENROUTER_API_KEY_3",
        "OPENROUTER_API_KEY",
    ]
    for n in names:
        val = os.getenv(n, "").strip().lstrip("#").strip("\"'")
        if val and not val.startswith("YOUR_") and not val.startswith("sk-or-PLACEHOLDER"):
            if not val.startswith("sk-or-"):
                val = f"sk-or-v1-{val}"
            if val not in keys:
                keys.append(val)
    return keys


class RotatingLLM:
    """
    Multi-provider, multi-key rotating LLM client with automatic failover.
    Sequentially rotates through OpenRouter keys (1 -> 2 -> 3) first.
    If all OpenRouter keys are exhausted, seamlessly falls back to Groq keys (1 -> 2 -> 3).
    When an API key encounters rate limits, errors, or timeouts on a job, it DOES NOT abandon
    the job: it immediately retries the EXACT SAME JOB with the next active key until success
    or all available provider keys are exhausted.
    """

    def __init__(self):
        self.openrouter_keys = get_openrouter_keys()
        self.groq_keys = get_groq_keys()
        self.active_openrouter_idx = 0
        self.active_groq_idx = 0
        self.openrouter_exhausted = False
        self.groq_exhausted = False
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")
        self.groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    def has_keys(self) -> bool:
        return bool(self.openrouter_keys or self.groq_keys)

    def invoke(self, messages: Any, max_tokens: Optional[int] = None) -> Any:
        from langchain_openai import ChatOpenAI

        def _extract_text(resp: Any) -> str:
            content = getattr(resp, "content", resp)
            if isinstance(content, (list, tuple)):
                content = " ".join(str(p) for p in content)
            return str(content or "").strip()

        last_exception = None

        # 1. Iterate through configured OpenRouter keys first (1 -> 2 -> 3)
        if self.openrouter_keys and not self.openrouter_exhausted:
            start_idx = self.active_openrouter_idx % len(self.openrouter_keys)
            for attempt in range(len(self.openrouter_keys)):
                idx = (start_idx + attempt) % len(self.openrouter_keys)
                curr_key = self.openrouter_keys[idx]
                key_id = f"OpenRouter Key #{idx + 1}"
                try:
                    client = ChatOpenAI(
                        api_key=curr_key,
                        base_url="https://openrouter.ai/api/v1",
                        model=self.openrouter_model,
                        temperature=0.1,
                        max_tokens=max_tokens or 600,
                        model_kwargs={"reasoning": {"enabled": False}},
                        default_headers={
                            "HTTP-Referer": "https://github.com/placement-prep/fresher-job-scraper",
                            "X-Title": "Fresher Job Intelligence Scraper",
                        },
                    )
                    res = client.invoke(messages)
                    if not _extract_text(res):
                        raise ValueError("OpenRouter returned empty response body")
                    self.active_openrouter_idx = idx
                    return res
                except Exception as exc:
                    last_exception = exc
                    logger.warning(
                        "[%s] Request failed: %s. Retrying same job with next key...",
                        key_id, exc
                    )
                    self.active_openrouter_idx = (idx + 1) % len(self.openrouter_keys)

            logger.info("All %d configured OpenRouter keys exhausted. Shifting to Groq pool...", len(self.openrouter_keys))
            self.openrouter_exhausted = True

        # 2. Iterate through configured Groq keys as fallback (1 -> 2 -> 3)
        if self.groq_keys and not self.groq_exhausted:
            start_idx = self.active_groq_idx % len(self.groq_keys)
            for attempt in range(len(self.groq_keys)):
                idx = (start_idx + attempt) % len(self.groq_keys)
                curr_key = self.groq_keys[idx]
                key_id = f"Groq Key #{idx + 1}"
                try:
                    client = ChatOpenAI(
                        api_key=curr_key,
                        base_url="https://api.groq.com/openai/v1",
                        model=self.groq_model,
                        temperature=0.1,
                        max_tokens=max_tokens or 600,
                        model_kwargs={"reasoning_effort": "none"},
                    )
                    res = client.invoke(messages)
                    if not _extract_text(res):
                        raise ValueError("Groq returned empty response body")
                    self.active_groq_idx = idx
                    return res
                except Exception as exc:
                    last_exception = exc
                    logger.warning(
                        "[%s] Request failed: %s. Retrying same job with next key...",
                        key_id, exc
                    )
                    self.active_groq_idx = (idx + 1) % len(self.groq_keys)

            logger.info("All %d configured Groq keys exhausted.", len(self.groq_keys))
            self.groq_exhausted = True

        raise RuntimeError(f"All configured OpenRouter and Groq keys have been exhausted for this job! Last error: {last_exception}")


def get_llm():
    """Returns the singleton RotatingLLM instance or None if no keys configured."""
    global _CACHED_LLM
    if _CACHED_LLM is not None:
        return _CACHED_LLM

    pool = RotatingLLM()
    if not pool.has_keys():
        logger.warning("No Groq or OpenRouter API keys detected.")
        return None

    _CACHED_LLM = pool
    logger.info(
        "Initialized RotatingLLM pool with %d Groq key(s) and %d OpenRouter key(s).",
        len(pool.groq_keys), len(pool.openrouter_keys)
    )
    return _CACHED_LLM


def extract_requirements_and_skills_context(description: str, max_chars: int = 3500) -> str:
    """
    Extracts the key requirements, skills, qualifications, responsibilities,
    and experience sections from a raw job description, stripping corporate boilerplate.
    """
    if not description or not str(description).strip():
        return ""

    text = str(description).strip()
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(separator="\n", strip=True)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    section_keywords = [
        "requirement", "qualification", "responsibilit", "what you", "who you",
        "skill", "experience", "eligibility", "role overview", "role description",
        "duties", "profile", "must have", "good to have", "nice to have", "technical stack"
    ]

    boilerplate_markers = [
        "equal opportunity employer", "eeo is the law", "reasonable accommodation",
        "background check", "color, religion, sex", "sexual orientation, gender identity",
        "physical demands", "work environment", "veteran status", "about amgen",
        "about persistent", "about cognizant", "about wipro", "about infosys", "about accenture"
    ]

    captured_lines = []
    in_relevant_section = False

    for line in lines:
        clean_line = re.sub(r"^[*#-]+|\*\*|:", "", line).strip()
        lower_line = clean_line.lower()

        if any(b in lower_line for b in boilerplate_markers):
            in_relevant_section = False
            continue

        if len(clean_line) < 65 and any(k in lower_line for k in section_keywords):
            in_relevant_section = True
            captured_lines.append(f"\n### {clean_line}")
            continue

        if len(clean_line) < 65 and any(k in lower_line for k in [
            "about us", "about company", "about the company", "benefits", "perks",
            "compensation", "why join", "equal opportunity"
        ]):
            in_relevant_section = False
            continue

        if in_relevant_section:
            captured_lines.append(line)

    extracted_text = "\n".join(captured_lines).strip()

    # Fallback if specific sections were not isolated
    if len(extracted_text) < 250:
        filtered_lines = [
            l for l in lines
            if not any(b in l.lower() for b in boilerplate_markers)
        ]
        extracted_text = "\n".join(filtered_lines)

    return extracted_text[:max_chars].strip()


SYSTEM_GATEKEEPER_PROMPT = """You are a strict technical job gatekeeper for fresher IT hiring.
Evaluate the job title and description on TWO strict conditions:

1. FRESHER ELIGIBLE (0-1 years):
- True if the job is for freshers, 0-1 years exp, entry-level, fresh graduates, or requires no prior professional work.
- False if it requires >1 year experience, specialist tool mastery (e.g. 3+ yrs SAP, Salesforce, Oracle), senior scope, or previous full-time industry experience.

2. LEGITIMATE SOFTWARE / TECH ROLE:
- True ONLY if the role is in Software Engineering, Web/Full-stack Development, Data Analytics, BI, Machine Learning, or IT/Technical Business Analyst.
- False if the role is NON-TECH or unrelated engineering:
  * Plant, factory, industrial operations, shift operators, machine operators, water treatment/systems, boiler, maintenance.
  * Diploma engineering, ITI, mechanical, civil, electrical hardware, site engineering, construction, welder, fitter, machinist.
  * Telecalling, telemarketing, BPO, voice process, call center, customer care/support executive, physical sales, non-IT data entry.
  * Non-tech business operations or non-technical trainees.

If the description has no clear tech responsibilities/skills or is vague, return false.

Return ONLY this raw JSON (no other text):
{
  "is_fresher_eligible": true or false,
  "is_software_or_tech_role": true or false,
  "experience_detected": "decisive evidence from the description",
  "rejection_reason": "short reason if either condition is false, or null if both true",
  "curated_skills": "concrete technical tools/skills only (e.g. Python, SQL, React), comma separated"
}
"""


def extract_fallback_skills(text: str, title: str = "", role: str = "") -> str:
    """Extracts concrete technical skills and tools from text or role fallback."""
    found = []
    combined = f"{title} {role} {text}".lower()

    tech_keywords = [
        ("Python", r"\bpython\b"),
        ("SQL", r"\bsql\b"),
        ("Advanced Excel", r"\b(?:advanced\s+)?excel\b"),
        ("Power BI", r"\bpower\s*bi\b"),
        ("Tableau", r"\btableau\b"),
        ("JavaScript", r"\bjavascript\b|\bjs\b"),
        ("React", r"\breact(?:\.js)?\b"),
        ("Node.js", r"\bnode(?:\.js)?\b"),
        ("Java", r"\bjava\b"),
        ("C++", r"\bc\+\+\b"),
        ("HTML/CSS", r"\bhtml\b|\bcss\b"),
        ("Git", r"\bgit\b"),
        ("REST APIs", r"\brest(?:ful)?\s*api[s]?\b"),
        ("Pandas", r"\bpandas\b"),
        ("NumPy", r"\bnumpy\b"),
        ("AWS", r"\baws\b|\bamazon\s+web\s+services\b"),
        ("Azure", r"\bazure\b"),
        ("Docker", r"\bdocker\b"),
        ("Linux", r"\blinux\b"),
        ("JIRA", r"\bjira\b"),
        ("Agile", r"\bagile\b|\bscrum\b"),
        ("VLOOKUP/HLOOKUP", r"\bvlookup\b|\bhlookup\b"),
        ("Data Analysis", r"\bdata\s+analy(?:sis|tics)\b"),
        ("Data Modeling", r"\bdata\s+model(?:ing)?\b"),
        ("ETL", r"\betl\b"),
        ("KYC/AML", r"\bkyc\b|\baml\b"),
        ("Requirements Gathering", r"\brequirement[s]?\s+gathering\b"),
        ("BRD/FRD", r"\bbrd\b|\bfrd\b"),
        ("Problem Solving", r"\bproblem[\s-]solving\b"),
        ("Financial Analysis", r"\bfinancial\s*(?:processes|analysis|modeling)?\b"),
        ("Backup Administration", r"\bbackup\s*(?:administration|admin)?\b"),
        ("System Administration", r"\bsystem\s*admin(?:istration)?\b"),
        ("Communication Skills", r"\bcommunication\s*(?:skills)?\b"),
    ]

    for label, pattern in tech_keywords:
        if re.search(pattern, combined, re.IGNORECASE):
            found.append(label)

    if found:
        if len(found) < 3:
            t_lower = f"{title} {role}".lower()
            if "data" in t_lower or "analyst" in t_lower:
                supplements = ["Microsoft Excel", "Data Validation", "Analytical Problem Solving"]
            elif "web" in t_lower or "developer" in t_lower:
                supplements = ["Git", "REST APIs", "Debugging"]
            else:
                supplements = ["Microsoft Excel", "Reporting", "Documentation"]
            for s in supplements:
                if s not in found and len(found) < 5:
                    found.append(s)
        return ", ".join(found[:8])

    t_lower = f"{title} {role}".lower()
    if "data" in t_lower:
        return "Python, SQL, Advanced Excel, Data Analysis, Power BI, Tableau"
    elif "web" in t_lower or "developer" in t_lower or "frontend" in t_lower or "backend" in t_lower:
        return "HTML, CSS, JavaScript, React, Node.js, Git, REST APIs"
    elif "business" in t_lower:
        return "Requirements Gathering, BRD/FRD, Advanced Excel, Process Modeling, Agile, JIRA"
    elif "tax" in t_lower or "accounting" in t_lower or "finance" in t_lower:
        return "Financial Reporting, Tax Compliance, Advanced Excel, General Ledger, Auditing"
    else:
        return "Analytical Problem Solving, Microsoft Excel, Data Validation, Reporting, Process Documentation"


def _as_bool(value: Any, default: bool = False) -> bool:
    """Robustly interpret LLM booleans (true/false, "true"/"false", 1/0)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "eligible"}:
            return True
        if normalized in {"false", "no", "0", "ineligible", "not eligible"}:
            return False
    return default


def verify_fresher_and_curate_skills(
    description: str,
    title: str = "",
    company: str = "",
    llm: Any = None,
) -> Dict[str, Any]:
    """
    Evaluates a job description with LLM to strictly ensure fresher eligibility
    and curate a clean list of required skills.

    Fails CLOSED: if the description is too thin, no LLM is configured, the call
    fails, or the response cannot be parsed, the job is NOT treated as verified.
    Callers must route `llm_verified=False` jobs to manual review rather than to
    the live Google Sheet.
    """
    context = extract_requirements_and_skills_context(description)
    if not context or len(context) < 80:
        return {
            "is_fresher_eligible": False,
            "llm_verified": False,
            "experience_detected": "Insufficient description text",
            "rejection_reason": "Description too short to verify fresher eligibility",
            "curated_skills": extract_fallback_skills(description, title=title),
        }

    active_llm = llm or get_llm()
    if active_llm is None:
        logger.warning("No LLM available for fresher verification; failing closed.")
        return {
            "is_fresher_eligible": False,
            "is_valid_fresher": False,
            "llm_verified": False,
            "experience_detected": "LLM not configured",
            "rejection_reason": "LLM verification unavailable (no API keys configured)",
            "curated_skills": extract_fallback_skills(context, title=title),
        }

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
    except ImportError:
        class SystemMessage:  # type: ignore[no-redef]
            def __init__(self, content: str):
                self.content = content

        class HumanMessage:  # type: ignore[no-redef]
            def __init__(self, content: str):
                self.content = content

    user_content = f"Job Title: {title}\nCompany: {company}\n\nJob Description Excerpt:\n{context}"
    try:
        response = active_llm.invoke([
            SystemMessage(content=SYSTEM_GATEKEEPER_PROMPT),
            HumanMessage(content=user_content),
        ])
        raw_text = getattr(response, "content", str(response)).strip()

        # Extract JSON from response
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            is_fresher = _as_bool(data.get("is_fresher_eligible"), default=False)
            is_tech = _as_bool(data.get("is_software_or_tech_role"), default=True) if "is_software_or_tech_role" in data else True
            is_eligible = is_fresher and is_tech

            skills_val = data.get("curated_skills", "")
            if isinstance(skills_val, list):
                skills = ", ".join(str(s).strip() for s in skills_val if str(s).strip())
            elif isinstance(skills_val, dict):
                skills = ", ".join(f"{k}: {v}" for k, v in skills_val.items())
            else:
                skills = str(skills_val or "").strip()

            skills = re.sub(r"^[*\-•\s]+", "", skills)
            skills = re.sub(r"\n+[*\-•\s]*", ", ", skills)
            skills = re.sub(r",\s*,+", ", ", skills).strip(" ,")

            if not skills:
                skills = extract_fallback_skills(context, title=title)

            exp_det = str(data.get("experience_detected", "") or "").strip()
            reason = data.get("rejection_reason")
            if not is_tech and not reason:
                reason = "Role is non-technical / not software, web, or data engineering"
            elif not is_fresher and not reason:
                reason = "Role requires prior experience (>1 year)"

            return {
                "is_fresher_eligible": is_eligible,
                "is_software_or_tech_role": is_tech,
                "is_valid_fresher": is_eligible,
                "llm_verified": True,
                "experience_detected": exp_det,
                "rejection_reason": reason if not is_eligible else None,
                "curated_skills": skills,
            }
    except Exception as exc:
        logger.error("LLM verification call failed: %s", exc)

    return {
        "is_fresher_eligible": False,
        "is_valid_fresher": False,
        "llm_verified": False,
        "experience_detected": "Evaluation failed",
        "rejection_reason": "LLM verification failed; job not verified",
        "curated_skills": extract_fallback_skills(context, title=title),
    }


def hydrate_job_description(job: Dict[str, Any]) -> str:
    """
    Hydrates the job description for a job dictionary from Naukri, LinkedIn, or Indeed
    if not already present.
    """
    existing_desc = str(job.get("description") or "").strip()
    if len(existing_desc) > 150:
        return existing_desc

    site = str(job.get("site") or "").lower()
    apply_url = str(job.get("apply_url") or job.get("job_url_direct") or job.get("job_url") or "")
    job_id = str(job.get("id") or "")

    # 1. Naukri Hydration
    if site == "naukri" or "naukri.com" in apply_url:
        numeric_id = ""
        # Extract numeric id from URL (e.g. ...-0-to-1-years-131126011049)
        url_match = re.search(r"(\d{10,14})$", apply_url.rstrip("/"))
        if url_match:
            numeric_id = url_match.group(1)
        elif job_id.replace("nk-", "").isdigit():
            numeric_id = job_id.replace("nk-", "")

        if numeric_id:
            try:
                from curl_cffi import requests as cffi_requests
                from jobspy.naukri.constant import job_page_headers
                from jobspy.naukri import generate_nkparam
                session = cffi_requests.Session(impersonate="chrome")
                url = f"https://www.naukri.com/jobapi/v4/job/{numeric_id}"
                headers = job_page_headers | {"nkparam": generate_nkparam(str(numeric_id))}
                res = session.get(url, headers=headers, timeout=8)
                if res.status_code == 200:
                    data = res.json().get("jobDetails", {})
                    desc_html = data.get("description", "")
                    clean_desc = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)
                    if clean_desc:
                        job["description"] = clean_desc
                        return clean_desc
            except Exception as e:
                logger.debug("Naukri hydration failed for %s: %s", numeric_id, e)

    # 2. LinkedIn Hydration
    if site == "linkedin" or "linkedin.com" in apply_url:
        # Check direct external ATS first
        direct_url = str(job.get("job_url_direct") or "")
        if direct_url and direct_url.startswith("http") and "linkedin.com" not in direct_url:
            try:
                import requests
                ats_resp = requests.get(
                    direct_url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                    timeout=6,
                )
                if ats_resp.status_code == 200:
                    soup = BeautifulSoup(ats_resp.text, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    ats_text = soup.get_text("\n", strip=True)
                    if len(ats_text) >= 150:
                        job["description"] = ats_text[:16000]
                        return ats_text[:16000]
            except Exception:
                pass

        li_id = ""
        m = re.search(r"/view/(\d+)", apply_url)
        if m:
            li_id = m.group(1)
        elif job_id.replace("li-", "").isdigit():
            li_id = job_id.replace("li-", "")

        if li_id:
            try:
                import scraper
                import time
                if time.time() < getattr(scraper, "_LINKEDIN_HYDRATION_COOLDOWN_UNTIL", 0.0):
                    return existing_desc
            except Exception:
                pass
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                }
                url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{li_id}"
                try:
                    from curl_cffi import requests as cffi_requests
                    s = cffi_requests.Session(impersonate="chrome")
                    res = s.get(url, headers=headers, timeout=8)
                except Exception:
                    import requests
                    res = requests.get(url, headers=headers, timeout=6)

                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "html.parser")
                    desc_div = soup.find("div", class_="show-more-less-html__markup")
                    if desc_div:
                        clean_desc = desc_div.get_text(separator="\n", strip=True)
                        job["description"] = clean_desc
                        return clean_desc
                elif res.status_code in (429, 403, 999):
                    logger.warning("LinkedIn guest endpoint rate-limited/blocked (HTTP %s) for job %s.", res.status_code, li_id)
                    try:
                        import scraper
                        import time
                        with scraper._LINKEDIN_LOCK:
                            scraper._LINKEDIN_HYDRATION_COOLDOWN_UNTIL = time.time() + 20.0
                    except Exception:
                        pass
                        pass
            except Exception as e:
                logger.debug("LinkedIn hydration failed for %s: %s", li_id, e)

    # 3. Foundit / Monster India Hydration
    if site in {"monsterindia", "foundit"} or "foundit.in" in apply_url:
        jid = job_id.replace("fi-", "").strip()
        url_match = re.search(r"(\d{7,10})", apply_url)
        target_id = jid if jid.isdigit() else (url_match.group(1) if url_match else "")
        if target_id:
            try:
                from foundit_scraper import fetch_foundit_job_description
                desc = fetch_foundit_job_description(target_id)
                if desc:
                    job["description"] = desc
                    return desc
            except Exception as e:
                logger.debug("Foundit hydration failed for %s: %s", target_id, e)

    return existing_desc
