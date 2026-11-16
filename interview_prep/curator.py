"""LLM curation of the interview-prep question pack.

Turns a verified job + scraped evidence into a comprehensive, research-backed
pack of 15-20 technical interview questions with concise, student-friendly answers,
evidence classifications, and research summaries.
Fails CLOSED: any LLM/parse/validation failure raises :class:`CuratorError`
and the calling runner skips the job (no half-baked PDFs).
"""
from __future__ import annotations

import html as html_module
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("interview_prep.curator")

PACK_VERSION = "2.0"  # Deep Company Research & Technical Interview Prediction

MIN_QUESTIONS = 10    # Hard floor: below this the pack fails closed
TARGET_MIN = 12       # Lower acceptable bound
TARGET_MAX = 20       # Target 20 questions per user specification
MAX_ANSWERED_CODING = 2   # At most 2 coding questions get full code answers
MAX_BULLETS = 5
MAX_BULLET_CHARS = 350

ALLOWED_KINDS = {"coding", "technical", "scenario", "fundamentals", "behavioral", "hr", "role"}

SYSTEM_PROMPT = """You are a Senior Technical Recruiter, Engineering Research Analyst, and Technical Interview Strategist.

Your task is to conduct comprehensive, evidence-backed research on the target company and its technical interview process to generate the 20 most probable and relevant technical interview questions for the given job role.

Do not generate a generic interview preparation list. Every question must be selected based on evidence gathered about the company, its business domain, technical specialization, projects, technology stack, job requirements, and previous interview experiences.

PRIORITY SCORING MODEL
- Job Description (JD) relevance: 30%
- Company technical specialization and project relevance: 25%
- Previous interview evidence: 25%
- Employee technical profile patterns: 10%
- Role & experience-level relevance (Fresher 0-1 yrs): 10%

STRICT RULES
1. Output ONLY valid JSON matching the schema below. No markdown fences, no text before or after.
2. Produce 15 to 20 questions (target exactly 20).
3. Answer AT MOST 2 coding questions fully (with "code"). Every additional coding problem goes into "more_coding_questions" as an un-answered prompt.
4. Balanced mixture:
   - Core technical fundamentals
   - Framework & technology-specific concepts
   - Database and backend concepts
   - Company-domain-specific technical concepts
   - Real-world scenario and practical engineering problems
   - 1-2 behavioral/situational questions appropriate for a fresh graduate
5. Answer format for each question:
   - "answer_bullets": 2 to 4 concise bullet points in simple, intuitive English.
   - Start with a direct, simple explanation. If a term is technical, explain it in the same sentence.
   - "example": include a concrete real-world example (1-2 sentences) wherever useful.
   - "relevance": 1-2 sentences explaining why this question matters to this specific company and role.
6. Evidence classification:
   - "A": Previously reported for exact company and comparable role
   - "B": Reported for company but different or broader role
   - "C": Supported by company projects, employee profiles, and JD tech stack overlap
   - "D": Predicted from JD and industry/role requirements
7. Likelihood rating: "Very High", "High", or "Medium".
8. For coding questions, "code" must include:
   - "approach": 3-4 lines explaining the approach
   - "code": clean, readable code in relevant language (Python/JS/SQL), max 15 lines
   - "complexity": Time & Space complexity (e.g. "Time: O(N), Space: O(1)")

JSON SCHEMA
{
  "role_summary": "1-2 sentences summarizing the interview focus and key competencies",
  "company_specialization": {
    "primary_business": "Company's primary industry and business domain",
    "products_platforms": "Key products, platforms, or client solutions",
    "core_tech_stack": "Core programming languages, frameworks, databases, and infrastructure"
  },
  "interview_pattern": {
    "rounds_overview": "Summary of likely interview rounds (e.g. Screening, Assessment, Technical Deep-Dive)",
    "evaluation_focus": "Core competencies tested by interviewers"
  },
  "top_technologies": [
    "Top prioritized technology or concept 1",
    "Top prioritized technology or concept 2",
    "Top prioritized technology or concept 3",
    "Top prioritized technology or concept 4",
    "Top prioritized technology or concept 5"
  ],
  "top_5_questions_to_prepare_first": [
    "Question text to prepare first (1)",
    "Question text to prepare first (2)",
    "Question text to prepare first (3)",
    "Question text to prepare first (4)",
    "Question text to prepare first (5)"
  ],
  "research_gaps": "Brief note distinguishing confirmed company facts vs role/JD predictions",
  "questions": [
    {
      "number": 1,
      "topic": "Technical topic title",
      "question": "The interview question",
      "kind": "coding|technical|scenario|fundamentals|behavioral",
      "evidence_class": "A|B|C|D",
      "likelihood": "Very High|High|Medium",
      "relevance": "Why this question is relevant to the company and role",
      "answer_bullets": ["bullet 1", "bullet 2", "bullet 3"],
      "example": "Real-world example (1-2 sentences)",
      "code": {
        "language": "python",
        "approach": "Approach explanation",
        "code": "def solve(): pass",
        "complexity": "Time: O(N), Space: O(1)"
      }
    }
  ],
  "more_coding_questions": [
    "Unanswered practice coding problem 1",
    "Unanswered practice coding problem 2"
  ]
}
"""

USER_TEMPLATE = """Conduct Deep Company Research & Technical Interview Prediction for this job opportunity:

COMPANY & JOB INPUT
Company Name: {company}
Job Title: {title}
Role Category: {role}
Location: {location}
Job Board Source: {site}
Skills Required: {skills}
Experience Level: Fresher (0-1 years)

JOB DESCRIPTION EXCERPT
{jd_excerpt}

SCRAPED EVIDENCE & PUBLIC INTELLIGENCE
Company-specific evidence & public notes:
{company_evidence}

Role & domain interview evidence:
{role_evidence}

Skill-specific interview evidence:
{skill_evidence}

Discovered public sources:
{sources}

Generate the full research-backed prediction pack adhering strictly to the JSON schema and 20-question target.
"""


class CuratorError(RuntimeError):
    """Raised when a question pack cannot be produced (fail-closed)."""


def _call_llm(llm: Any, messages: list, max_tokens: int = 6500) -> str:
    """Invoke an LLM, tolerating clients whose invoke() ignores max_tokens."""
    try:
        response = llm.invoke(messages, max_tokens=max_tokens)
    except TypeError:
        response = llm.invoke(messages)
    content = getattr(response, "content", response)
    if isinstance(content, (list, tuple)):
        content = " ".join(str(part) for part in content)
    return str(content or "")


def _extract_json(raw: str) -> Optional[dict]:
    """Pull the outermost JSON object out of an LLM response."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = match.group(0) if match else text
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        import json_repair
        repaired = json_repair.loads(candidate)
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass
    return None


def _clean_bullets(bullets: Any) -> list[str]:
    out: list[str] = []
    if isinstance(bullets, str):
        bullets = [bullets]
    if isinstance(bullets, list):
        for b in bullets:
            text = re.sub(r"\s+", " ", str(b or "")).strip().lstrip("-•* ").strip()
            if text:
                out.append(text[:MAX_BULLET_CHARS])
            if len(out) >= MAX_BULLETS:
                break
    return out


def _normalize_code(code: Any) -> Optional[dict]:
    if not isinstance(code, dict):
        return None
    body = str(code.get("code") or "").strip()
    approach = str(code.get("approach") or "").strip()
    if not body:
        return None
    return {
        "language": str(code.get("language") or "python").strip().lower()[:20],
        "approach": approach[:600],
        "code": body,
        "complexity": str(code.get("complexity") or "").strip()[:150],
    }


def _normalize_question(item: Any, default_idx: int = 1) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    question = re.sub(r"\s+", " ", str(item.get("question") or "")).strip()
    if len(question) < 8:
        return None
    kind = str(item.get("kind") or "technical").strip().lower()
    if kind not in ALLOWED_KINDS:
        kind = "technical"
    if kind == "role":
        kind = "technical"

    origin = str(item.get("origin") or "role").strip().lower()
    if origin not in {"company", "role"}:
        origin = "role"

    evidence_class = str(item.get("evidence_class") or "D").strip().upper()
    if evidence_class not in {"A", "B", "C", "D"}:
        evidence_class = "D"

    likelihood = str(item.get("likelihood") or "High").strip()
    if likelihood.lower() in {"very high", "very_high"}:
        likelihood = "Very High"
    elif likelihood.lower() in {"medium", "med"}:
        likelihood = "Medium"
    else:
        likelihood = "High"

    topic = re.sub(r"\s+", " ", str(item.get("topic") or "")).strip()[:120]
    relevance = re.sub(r"\s+", " ", str(item.get("relevance") or "")).strip()[:350]

    normalized: dict = {
        "number": int(item.get("number") or default_idx),
        "topic": topic,
        "question": question[:400],
        "kind": kind,
        "origin": origin,
        "evidence_class": evidence_class,
        "likelihood": likelihood,
        "relevance": relevance,
        "answer_bullets": _clean_bullets(item.get("answer_bullets")),
    }
    example = str(item.get("example") or "").strip()
    if example and example.lower() not in {"none", "null", "n/a"}:
        normalized["example"] = re.sub(r"\s+", " ", example)[:500]
    if kind == "coding":
        code = _normalize_code(item.get("code"))
        if code:
            normalized["code"] = code
    if not normalized["answer_bullets"]:
        return None
    return normalized


def normalize_pack(raw_pack: dict) -> dict:
    """Validate + normalize an LLM pack; raises CuratorError when unusable."""
    if not isinstance(raw_pack, dict):
        raise CuratorError("LLM returned non-object JSON")

    questions: list[dict] = []
    for idx, item in enumerate(raw_pack.get("questions") or [], 1):
        q = _normalize_question(item, default_idx=idx)
        if q:
            questions.append(q)

    if len(questions) > TARGET_MAX:
        # Keep coding questions up to MAX_ANSWERED_CODING, then fill to TARGET_MAX
        coding = [q for q in questions if q["kind"] == "coding"][:MAX_ANSWERED_CODING]
        rest = [q for q in questions if q not in coding]
        questions = coding + rest[: TARGET_MAX - len(coding)]

    if len(questions) < MIN_QUESTIONS:
        raise CuratorError(f"Only {len(questions)} usable questions (minimum {MIN_QUESTIONS})")

    # Enforce the "at most 2 fully-answered coding questions" rule
    answered_coding = [q for q in questions if q["kind"] == "coding" and q.get("code")]
    overflow_coding = answered_coding[MAX_ANSWERED_CODING:]
    if overflow_coding:
        questions = [q for q in questions if q not in overflow_coding]

    more_coding: list[str] = []
    for extra in list(raw_pack.get("more_coding_questions") or []) + overflow_coding:
        if isinstance(extra, dict):
            text = str(extra.get("question") or "").strip()
        else:
            text = str(extra or "").strip()
        text = re.sub(r"\s+", " ", text).strip()
        if text and text not in more_coding:
            more_coding.append(text[:400])

    role_summary = re.sub(r"\s+", " ", str(raw_pack.get("role_summary") or "")).strip()[:600]

    company_spec = raw_pack.get("company_specialization") or {}
    if not isinstance(company_spec, dict):
        company_spec = {}

    interview_pat = raw_pack.get("interview_pattern") or {}
    if not isinstance(interview_pat, dict):
        interview_pat = {}

    top_techs = [
        re.sub(r"\s+", " ", str(t)).strip()
        for t in (raw_pack.get("top_technologies") or [])
        if str(t).strip()
    ][:10]

    top_5 = [
        re.sub(r"\s+", " ", str(q)).strip()
        for q in (raw_pack.get("top_5_questions_to_prepare_first") or [])
        if str(q).strip()
    ][:5]

    research_gaps = re.sub(r"\s+", " ", str(raw_pack.get("research_gaps") or "")).strip()[:600]

    return {
        "pack_version": PACK_VERSION,
        "role_summary": role_summary,
        "company_specialization": {
            "primary_business": str(company_spec.get("primary_business") or "").strip(),
            "products_platforms": str(company_spec.get("products_platforms") or "").strip(),
            "core_tech_stack": str(company_spec.get("core_tech_stack") or "").strip(),
        },
        "interview_pattern": {
            "rounds_overview": str(interview_pat.get("rounds_overview") or "").strip(),
            "evaluation_focus": str(interview_pat.get("evaluation_focus") or "").strip(),
        },
        "top_technologies": top_techs,
        "top_5_questions_to_prepare_first": top_5,
        "research_gaps": research_gaps,
        "questions": questions,
        "more_coding_questions": more_coding[:15],
    }


def build_interview_pack(job: dict, context: dict, llm: Any) -> dict:
    """Curate a normalized question pack for one job. Raises CuratorError on failure."""
    if llm is None:
        raise CuratorError("No LLM configured for question curation")

    skills = job.get("skills_requirements") or job.get("required_skills") or ""
    if isinstance(skills, (list, tuple)):
        skills = ", ".join(str(s) for s in skills)
    skill_list = [s.strip() for s in str(skills).split(",") if s.strip()]

    description = str(job.get("description") or "")
    jd_excerpt = description[:3500] if description.strip() else "(no description captured)"

    def _fmt(lines: list[str], cap: int) -> str:
        text = "\n".join(f"- {line}" for line in lines)
        return text[:cap] if text.strip() else "(none found)"

    user_content = USER_TEMPLATE.format(
        title=str(job.get("title") or "")[:160],
        company=str(job.get("company") or "")[:120],
        role=str(job.get("tech_category") or job.get("title") or "")[:120],
        location=str(job.get("location") or "")[:120],
        site=str(job.get("site") or "")[:30],
        skills=", ".join(skill_list) if skill_list else "(not captured)",
        jd_excerpt=jd_excerpt,
        company_evidence=_fmt(context.get("company_excerpts") or [], 3500),
        role_evidence=_fmt(context.get("role_excerpts") or [], 2800),
        skill_evidence=_fmt(context.get("skill_excerpts") or [], 3200),
        sources="\n".join(context.get("sources") or [])[:1200] or "(none)",
    )

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]

    raw = _call_llm(llm, messages, max_tokens=6500)
    parsed = _extract_json(raw)
    if parsed is None:
        logger.warning("Curator output did not contain parseable JSON; raw response:\n%s", raw[:300])
        raise CuratorError("LLM curation did not return parseable JSON")

    try:
        pack = normalize_pack(parsed)
    except CuratorError:
        logger.info("Pack incomplete; retrying once with an explicit count nudge.")
        messages.append(HumanMessage(
            content="The previous pack had too few usable questions. Regenerate the FULL JSON with AT LEAST 15 questions, exactly the same schema, and nothing else."
        ))
        raw = _call_llm(llm, messages, max_tokens=6500)
        parsed2 = _extract_json(raw)
        if parsed2 is None:
            raise
        pack = normalize_pack(parsed2)
    return pack


def escape_for_pdf(text: str) -> str:
    """Escape and sanitize text for reportlab Paragraph XML with Helvetica-safe characters."""
    if not text:
        return ""
    s = str(text)
    replacements = {
        "\u2010": "-",    # hyphen
        "\u2011": "-",    # non-breaking hyphen
        "\u2012": "-",    # figure dash
        "\u2013": "-",    # en dash
        "\u2014": " - ",  # em dash
        "\u2015": "-",    # horizontal bar
        "\u2212": "-",    # minus sign
        "\u00a0": " ",    # non-breaking space
        "\u200b": "",     # zero-width space
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201a": "'",    # single low-9 quote
        "\u201b": "'",    # single high-reversed-9 quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u201e": '"',    # double low-9 quote
        "\u2026": "...",  # ellipsis
        "\u2022": "*",    # bullet
        "\u00b7": "*",    # middle dot
        "\u2265": ">=",   # greater than or equal
        "\u2264": "<=",   # less than or equal
        "\u2260": "!=",   # not equal
    }
    for char, rep in replacements.items():
        s = s.replace(char, rep)
    # Strip any remaining unhandled non-ASCII characters outside standard latin
    s = "".join(c if ord(c) < 128 or ord(c) in {0xa9, 0xae} else "-" for c in s)
    return html_module.escape(s, quote=False)
