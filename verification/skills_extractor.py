"""
Dynamic Skills Extraction Engine (Zero-Hallucination)
=====================================================
Extracts technical and domain skills strictly from authentic job description text.
Never injects synthetic fallback skills (e.g. never assigns Java/Python to chefs or generic drives).
If no technical skills are published in the source JD, produces an empty skills list []
with status 'NO_ROLE_SPECIFIC_SKILLS_PUBLISHED'.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple
from core.models import SkillEvidence

# Canonical catalog of tech skills, tools, frameworks, and languages
TECH_SKILL_CATALOG = {
    # Programming Languages
    "Python": [r"\bpython\b"],
    "Java": [r"\bjava\b(?!\s*script)"],
    "C++": [r"\bc\+\+\b"],
    "C": [r"\bc\b(?!\+\+|#|\s*sharp)"],
    "C#": [r"\bc#\b", r"\bc\s*sharp\b"],
    "JavaScript": [r"\bjavascript\b", r"\bjs\b"],
    "TypeScript": [r"\btypescript\b", r"\bts\b"],
    "Golang": [r"\bgolang\b", r"\bgo\s+language\b"],
    "Rust": [r"\brust\b"],
    "PHP": [r"\bphp\b"],
    "Ruby": [r"\bruby\b"],
    "Kotlin": [r"\bkotlin\b"],
    "Swift": [r"\bswift\b"],
    "Scala": [r"\bscala\b"],
    "R": [r"\br\s+programming\b", r"\br\s+language\b"],

    # Web & Frameworks
    "React": [r"\breact(?:\.js)?\b"],
    "Node.js": [r"\bnode(?:\.js)?\b"],
    "Angular": [r"\bangular(?:\.js)?\b"],
    "Vue.js": [r"\bvue(?:\.js)?\b"],
    "Next.js": [r"\bnext\.js\b", r"\bnextjs\b"],
    "Django": [r"\bdjango\b"],
    "Flask": [r"\bflask\b"],
    "FastAPI": [r"\bfastapi\b"],
    "Spring Boot": [r"\bspring\s*boot\b", r"\bspring\s*framework\b"],
    "Express.js": [r"\bexpress\.js\b", r"\bexpressjs\b"],
    "HTML/CSS": [r"\bhtml5?\b", r"\bcss3?\b", r"\btailwind\b", r"\bbootstrap\b"],

    # Databases & Big Data
    "SQL": [r"\bsql\b"],
    "PostgreSQL": [r"\bpostgres(?:ql)?\b"],
    "MySQL": [r"\bmysql\b"],
    "MongoDB": [r"\bmongodb\b", r"\bmongo\b"],
    "Redis": [r"\bredis\b"],
    "Oracle DB": [r"\boracle\s*(?:db|database)?\b"],
    "Snowflake": [r"\bsnowflake\b"],
    "Kafka": [r"\bkafka\b"],
    "Spark": [r"\bspark\b", r"\bpyspark\b"],

    # Cloud & DevOps
    "AWS": [r"\baws\b", r"\bamazon\s*web\s*services\b"],
    "Azure": [r"\bazure\b", r"\bmicrosoft\s*azure\b"],
    "GCP": [r"\bgcp\b", r"\bgoogle\s*cloud(?:\s*platform)?\b"],
    "Docker": [r"\bdocker\b"],
    "Kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    "Git": [r"\bgit\b", r"\bgithub\b", r"\bgitlab\b"],
    "CI/CD": [r"\bci[\s/]?cd\b", r"\bjenkins\b"],
    "Linux": [r"\blinux\b", r"\bunix\b"],

    # Core CS & Domain
    "Data Structures & Algorithms": [r"\bdsa\b", r"\bdata\s*structures\b", r"\balgorithms\b"],
    "Object-Oriented Programming (OOP)": [r"\boop[s]?\b", r"\bobject[\s-]oriented\b"],
    "Database Management Systems (DBMS)": [r"\bdbms\b", r"\brdbms\b"],
    "Computer Networks": [r"\bcomputer\s*networks\b", r"\btcp[\s/]ip\b", r"\bnetworking\s*protocols\b"],
    "Operating Systems": [r"\boperating\s*systems\b"],
    "REST APIs": [r"\brest(?:ful)?\s*api[s]?\b", r"\bapi\s*design\b"],
    "Machine Learning": [r"\bmachine\s*learning\b", r"\bml\b(?!\s*language)"],
    "Deep Learning": [r"\bdeep\s*learning\b", r"\bneural\s*networks\b"],
    "Natural Language Processing (NLP)": [r"\bnlp\b", r"\bnatural\s*language\s*processing\b"],
}

SOFT_SKILL_CATALOG = {
    "Communication Skills": [r"\bcommunication\s*skills?\b", r"\bverbal\s*and\s*written\s*communication\b"],
    "Problem Solving": [r"\bproblem[\s-]solving\b", r"\banalytical\s*thinking\b", r"\banalytical\s*skills?\b"],
    "Teamwork & Collaboration": [r"\bteamwork\b", r"\bcollaboration\b", r"\bteam\s*player\b"],
    "Adaptability": [r"\badaptab(?:le|ility)\b", r"\bfast\s*learner\b", r"\beager\s*to\s*learn\b"],
}


def _find_evidence_snippet(text: str, match_start: int, match_end: int, window: int = 50) -> str:
    """Extracts a readable contextual snippet around the matched skill."""
    start = max(0, match_start - window)
    end = min(len(text), match_end + window)
    snippet = text[start:end].replace("\n", " ").strip()
    return f"...{snippet}..." if start > 0 or end < len(text) else snippet


def _is_preferred_context(text_before: str) -> bool:
    """Checks whether the skill is preceded by preferred/nice-to-have phrasing."""
    context = text_before[-60:].lower()
    return any(p in context for p in ["good to have", "nice to have", "plus", "preferred", "bonus", "advantageous"])


def extract_skills_dynamically(
    description: str,
    title: str = "",
    source_url: str = "",
) -> Tuple[List[str], List[SkillEvidence], List[SkillEvidence], List[SkillEvidence], str]:
    """Dynamically extracts skills strictly from JD text with provenance.
    
    Returns:
        (all_skill_names, required_skills, preferred_skills, skill_evidence_items, status)
    """
    full_text = f"{title}\n{description}".strip()
    if not full_text:
        return [], [], [], [], "NO_TEXT_PROVIDED"

    matched_skills: Set[str] = set()
    required_evidence: List[SkillEvidence] = []
    preferred_evidence: List[SkillEvidence] = []
    all_evidence: List[SkillEvidence] = []

    # 1. Match Technical Skills
    for skill_name, patterns in TECH_SKILL_CATALOG.items():
        for pat in patterns:
            match = re.search(pat, full_text, re.IGNORECASE)
            if match:
                matched_skills.add(skill_name)
                start_pos, end_pos = match.span()
                snippet = _find_evidence_snippet(full_text, start_pos, end_pos)
                is_preferred = _is_preferred_context(full_text[:start_pos])

                evidence_item = SkillEvidence(
                    name=skill_name,
                    category="tools_and_technologies" if skill_name in ["Docker", "Git", "Kubernetes", "AWS", "Azure"] else "required_skills",
                    evidence=snippet,
                    evidence_url=source_url,
                    confidence=0.95,
                    is_explicit=True,
                    is_required=not is_preferred,
                )
                all_evidence.append(evidence_item)
                if is_preferred:
                    preferred_evidence.append(evidence_item)
                else:
                    required_evidence.append(evidence_item)
                break

    # 2. Match Soft Skills
    for skill_name, patterns in SOFT_SKILL_CATALOG.items():
        for pat in patterns:
            match = re.search(pat, full_text, re.IGNORECASE)
            if match:
                matched_skills.add(skill_name)
                start_pos, end_pos = match.span()
                snippet = _find_evidence_snippet(full_text, start_pos, end_pos)

                evidence_item = SkillEvidence(
                    name=skill_name,
                    category="soft_skills",
                    evidence=snippet,
                    evidence_url=source_url,
                    confidence=0.9,
                    is_explicit=True,
                    is_required=True,
                )
                all_evidence.append(evidence_item)
                required_evidence.append(evidence_item)
                break

    # 3. CRITICAL RULE: If no skills found, DO NOT INJECT FALLBACKS.
    skill_names_sorted = sorted(list(matched_skills))
    if not skill_names_sorted:
        return [], [], [], [], "NO_ROLE_SPECIFIC_SKILLS_PUBLISHED"

    return skill_names_sorted, required_evidence, preferred_evidence, all_evidence, "EXTRACTED_SUCCESSFULLY"
