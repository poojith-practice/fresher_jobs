"""Dynamic Skills Generator separating EXPLICIT and INFERRED competencies."""
from __future__ import annotations

import re
from typing import Dict, List, Tuple
from models.opportunity import OpportunityType

TECH_KEYWORDS = {
    "Python": [r"\bpython\b"],
    "Java": [r"\bjava\b(?!script)"],
    "JavaScript": [r"\bjavascript\b", r"\bjs\b"],
    "TypeScript": [r"\btypescript\b", r"\bts\b"],
    "C++": [r"\bc\+\+\b"],
    "C#": [r"\bc#\b", r"\bcsharp\b"],
    "SQL": [r"\bsql\b", r"\bpostgresql\b", r"\bmysql\b", r"\boracle\b"],
    "Relational Databases": [r"\brelational\s+databases?\b", r"\bdbms\b"],
    "Algorithms & DSA": [r"\balgorithms?\b", r"\bdata\s+structures?\b", r"\bdsa\b"],
    "Distributed Systems": [r"\bdistributed\s+systems?\b"],
    "REST APIs": [r"\brest\s*api[s]?\b", r"\brestful\b"],
    "HTML/CSS": [r"\bhtml\b", r"\bcss\b"],
    "React": [r"\breact\b", r"\breactjs\b"],
    "Angular": [r"\bangular\b"],
    "Node.js": [r"\bnode\b", r"\bnodejs\b"],
    "FastAPI": [r"\bfastapi\b"],
    "Django": [r"\bdjango\b"],
    "Spring Boot": [r"\bspring\s*boot\b"],
    "Cloud Computing": [r"\bcloud\b", r"\bcloud\s+computing\b"],
    "AWS": [r"\baws\b", r"\bamazon web services\b"],
    "Azure": [r"\bazure\b"],
    "Docker": [r"\bdocker\b", r"\bkubernetes\b"],
    "Git": [r"\bgit\b", r"\bgithub\b"],
    "Excel": [r"\bexcel\b", r"\badvanced excel\b"],
    "PowerBI": [r"\bpower\s*bi\b"],
    "Tableau": [r"\btableau\b"],
    "Linux": [r"\blinux\b", r"\bunix\b"],
    "Networking": [r"\bnetworking\b", r"\btcp/ip\b", r"\bdns\b"],
}

ROLE_INFERRED_SKILLS: Dict[str, List[str]] = {
    "software dev engineer": ["Data Structures & Algorithms", "System Design Basics", "OOP", "Relational Databases", "Problem Solving", "Git"],
    "software engineer": ["Data Structures & Algorithms", "Object-Oriented Programming (OOP)", "Database Management (DBMS)", "Problem Solving", "Git"],
    "software developer": ["Data Structures & Algorithms", "Object-Oriented Programming (OOP)", "Database Management (DBMS)", "Problem Solving", "Git"],
    "sde": ["Data Structures & Algorithms", "System Design Basics", "OOP", "DBMS", "Problem Solving", "Git"],
    "associate software engineer": ["Data Structures & Algorithms", "OOP", "DBMS", "Problem Solving", "Git"],
    "graduate software engineer": ["Data Structures & Algorithms", "OOP", "DBMS", "Core CS Fundamentals", "Git"],
    "software intern": ["Data Structures & Algorithms", "OOP", "Problem Solving", "Git", "Web Fundamentals"],
    "software trainee": ["Core Programming", "OOP", "DBMS", "Problem Solving", "Git"],
    "python": ["Python", "Object-Oriented Programming (OOP)", "Data Structures", "SQL", "Debugging"],
    "java": ["Java", "Core Java Fundamentals", "OOP", "Data Structures", "Collections Framework"],
    "data analyst": ["SQL", "Data Analysis", "Excel", "Statistics", "Data Visualization"],
    "business analyst": ["Requirement Gathering", "Process Modeling", "SQL", "Agile / Scrum", "Data Analysis"],
    "financial analyst": ["Financial Modeling", "Excel", "Variance Analysis", "Financial Reporting", "Data Analysis"],
    "analyst": ["Analytical Problem Solving", "Data Interpretation", "Excel", "Communication Skills"],
    "cybersecurity": ["Networking Fundamentals", "Operating Systems", "Linux", "Security Fundamentals", "Log Analysis"],
    "qa": ["Manual Testing", "Test Case Design", "Bug Tracking", "SDLC Fundamentals", "Automation Basics"],
    "web developer": ["HTML/CSS", "JavaScript", "Responsive Design", "REST APIs", "Git"],
    "full stack": ["Frontend Basics (HTML/CSS/JS)", "Backend Frameworks", "Database Modeling", "REST APIs", "Git"],
    "graduate engineer trainee": ["Core Engineering Fundamentals", "Analytical Problem Solving", "Algorithmic Logic", "Communication Skills"],
    "intern": ["Analytical Problem Solving", "Core Domain Fundamentals", "Communication Skills", "Git"],
    "trainee": ["Core Domain Fundamentals", "Analytical Problem Solving", "Learning Agility", "Communication"],
    "operations": ["Process Management", "Problem Solving", "Reporting", "Cross-Functional Collaboration"],
    "associate": ["Analytical Thinking", "Problem Solving", "Domain Fundamentals", "Communication"],
}


def generate_skills(
    title: str,
    description: str,
    opportunity_type: OpportunityType,
) -> Tuple[List[str], List[str]]:
    """Extracts explicit skills and derives inferred skills without fabricating."""
    full_text = f"{title} {description}".lower()
    explicit: List[str] = []

    # 1. Match explicit skills mentioned directly
    for skill_name, patterns in TECH_KEYWORDS.items():
        if any(re.search(pat, full_text, re.IGNORECASE) for pat in patterns):
            if skill_name not in explicit:
                explicit.append(skill_name)

    # 2. Derive inferred skills based on role context
    inferred: List[str] = []

    # For generic off-campus drive without specific technical role, DO NOT fabricate technical skills
    if opportunity_type == OpportunityType.OFF_CAMPUS_DRIVE:
        is_tech_drive = any(k in title.lower() for k in ["software", "developer", "engineer", "analyst", "tech", "sde", "trainee"])
        if not is_tech_drive and not explicit:
            return explicit, ["Aptitude & Logical Reasoning", "Quantitative Ability", "Verbal Communication", "Analytical Problem Solving"]

    # Deduce based on role title keywords
    t_lower = title.lower()
    for role_key, skills in ROLE_INFERRED_SKILLS.items():
        if role_key in t_lower:
            for s in skills:
                if s not in explicit and s not in inferred:
                    inferred.append(s)

    # 3. Guaranteed completeness: Ensure no opportunity has empty skills
    if not explicit and not inferred:
        inferred = ["Aptitude & Logical Reasoning", "Analytical Problem Solving", "Communication Skills"]

    return explicit, inferred[:6]
