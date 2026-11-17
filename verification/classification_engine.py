"""
Opportunity Classification & Role Family Triage Engine
======================================================
Classifies opportunities into OpportunityType enums and strictly segregates
software/IT roles from non-tech roles (culinary, hospitality, manufacturing, pharma,
finance FP&A, back-office operations, KYC, audio listening, and website navigation links).
Never defaults unmatched opportunities to technology.
"""
from __future__ import annotations

import re
from typing import Tuple, List
from core.models import OpportunityType

NON_TECH_PATTERNS = [
    # 1. Culinary & Hospitality
    r"\bcommis\s*(?:[123i]{1,3}|one|two|three)?\b",
    r"\bchef\s*(?:de\s*partie|cuisinier)?\b",
    r"\bcook\b",
    r"\bkst\b",
    r"\bsteward(?:ing)?\b",
    r"\bbartender\b",
    r"\bhousekeeping\b",
    r"\bfood\s*&\s*beverage\b",
    r"\bf&b\s*(?:associate|executive|attendant)\b",
    r"\bwaiter\b",
    r"\bwaitress\b",
    r"\bfront\s*office\s*(?:associate|executive)\b",
    r"\bguest\s*relations\b",
    r"\bhotel[s]?\b",
    r"\bhospitality\b",
    r"\bresort[s]?\b",

    # 2. Manufacturing, Pharma & Physical Trades
    r"\badhesive\s*technologist\b",
    r"\bofficer\s*[-–—]?\s*production\b",
    r"\bproduction\s*[-–—]?\s*officer\b",
    r"\bpharma(?:ceutical)?s?\b",
    r"\bqa\s*chemist\b",
    r"\bqc\s*chemist\b",
    r"\bformulation\s*operator\b",
    r"\bmachine\s*operator\b",
    r"\bstore\s*executive\b",
    r"\bwarehouse\s*(?:associate|worker)\b",
    r"\bdelivery\s*(?:boy|partner|driver)\b",
    r"\bdriver\b",
    r"\bnurse\b",
    r"\bsecurity\s*guard\b",
    r"\belectrical\s*maintenance\b",
    r"\bmechanical\s*technician\b",
    r"\bplumber\b",
    r"\bfitter\b",

    # 3. Back-Office, BPO, KYC & Support Operations
    r"\b(?:video\s*)?kyc\b",
    r"\bkyc\s*associate\b",
    r"\bprocess\s*(?:associate|executive|specialist|trainee|representative)\b",
    r"\boperations\s*(?:executive|associate|trainee|representative|analyst)\b",
    r"\b(?:business\s*process\s*(?:services|outsourcing|management)|bps|bpm)\b",
    r"\bclient\s*operations\b",
    r"\bequities\s*client\b",
    r"\bcustomer\s*(?:support|service|care)\b",
    r"\btelecaller\b",
    r"\btelemarketing\b",
    r"\bvoice\s*process\b",
    r"\bnon[\s-]?voice\s*process\b",
    r"\bbpo\b",
    r"\bdata\s*entry\b",
    r"\bclaim[s]?\s*(?:associate|processor|analyst)\b",
    r"\bunderwriting\b",

    # 4. Audio, Media Operations & Content Moderation
    r"\baudio\s*listen\w*\b",
    r"\bdigital\s*content\s*associate\b",
    r"\bcontent\s*moderator\b",
    r"\baudio\s*evaluator\b",

    # 5. Finance, Accounting, Tax, HR & Sales
    r"\bfinancial\s*analyst\b",
    r"\bfp&a\b",
    r"\baccounts\s*(?:payable|receivable)\b",
    r"\bbookkeeper\b",
    r"\baudit\s*associate\b",
    r"\btax(?:ation)?\s*analyst\b",
    r"\bhuman\s*resources\b",
    r"\bhr\s*(?:trainee|executive|associate|intern|recruiter)\b",
    r"\btalent\s*acquisition\b",
    r"\bmarketing\s*(?:executive|associate|trainee|intern)\b",
    r"\bsales\s*(?:executive|associate|trainee|representative|development|bda)\b",
    r"\bbusiness\s*development\s*(?:associate|executive|trainee)\b",
    r"\bretail\s*(?:associate|staff|trainee)\b",
    r"\bfront\s*office\b",
    r"\breceptionist\b",

    # 6. Website Navigation, Category Archives & Non-Job Slugs
    r"\b\d{4}\s*batch\s*drives\b",
    r"\binterview\s*questions\b",
    r"\binterview\s*preparation\b",
    r"\bwork\s*from\s*home\s*jobs?\b",
    r"\bresume\s*builder\b",
    r"\bplacement\s*papers\b",
    r"\bsample\s*papers\b",
]

COLLECTIVE_DRIVE_PATTERNS = [
    r"\boff[\s-]?campus(?:\s*recruitment)?\s*drive\b",
    r"\bnqt\b",
    r"\belite\s*nlth\b",
    r"\bgenc(?:\s*(?:elevate|next))?\b",
    r"\bgraduate\s*hiring\s*program\b",
    r"\bcampus\s*(?:drive|recruitment|hiring)\b",
    r"\bpooled\s*campus\b",
]

INTERNSHIP_PATTERNS = [
    r"\bintern(?:ship)?\b",
    r"\bproject\s*intern\b",
    r"\btrainee\s*intern\b",
]

GRADUATE_TRAINEE_PATTERNS = [
    r"\bgraduate\s*(?:engineer\s*)?trainee\b",
    r"\bget\b",
    r"\bengineer\s*trainee\b",
    r"\bassociate\s*software\s*engineer\b",
    r"\bgraduate\s*software\s*engineer\b",
    r"\b(?:java|python|ai|ml|software|cloud|data|tech|it|developer|devops)\s+apprentice\b",
    r"\bapprentice\b",
]

EXPERIENCED_ROLE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.\b",
    r"\blead\b",
    r"\bprincipal\b",
    r"\barchitect\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bhead\s*of\b",
    r"\bvp\b",
]

# Explicit positive tech titles and disciplines
EXPLICIT_TECH_TITLES = [
    r"\bsoftware\s*(?:development\s*)?engineer\b",
    r"\bsde(?:\s*[-–—]?\s*[1i])?\b",
    r"\b(?:[a-z0-9+#.-]+\s+)?developer\b",
    r"\b(?:[a-z0-9+#.-]+\s+)?programmer\b",
    r"\bdata\s*engineer\b",
    r"\bdata\s*analyst\b",
    r"\bsystems?\s*analyst\b",
    r"\bsoftware\s*analyst\b",
    r"\bqa\s*(?:analyst|engineer|tester)\b",
    r"\btest\s*(?:automation\s*)?engineer\b",
    r"\bquality\s*assurance\s*engineer\b",
    r"\bcloud\s*engineer\b",
    r"\bdevops\s*engineer\b",
    r"\bai\s*(?:engineer|developer)\b",
    r"\bml\s*(?:engineer|developer)\b",
    r"\bmachine\s*learning\s*engineer\b",
    r"\bembedded\s*software\s*engineer\b",
    r"\bfirmware\s*engineer\b",
    r"\bcompiler\s*software\s*engineer\b",
    r"\bnetwork\s*(?:dev\s*)?engineer\b",
]


def classify_opportunity(title: str, description: str = "", company: str = "") -> Tuple[OpportunityType, str, List[str]]:
    """Classifies an opportunity based on title, company, and JD text.
    
    Returns:
        (opportunity_type, role_family, classification_reasons)
    """
    clean_title = title.lower().strip()
    clean_comp = company.lower().strip()
    full_text = f"{clean_title} {clean_comp} {description[:1000].lower()}".strip()
    reasons = []

    # 1. Non-tech boundary filter (Strict rejection gate)
    for pat in NON_TECH_PATTERNS:
        match = re.search(pat, f"{clean_title} {clean_comp}")
        if match:
            # Exception: If positive tech keyword is explicitly in title (e.g. "Software Engineer at Pharma Co"), don't reject
            if not any(re.search(tp, clean_title) for tp in EXPLICIT_TECH_TITLES):
                reasons.append(f"Non-tech title or domain detected matching '{match.group(0)}'")
                return OpportunityType.UNRELATED, "NON_TECH", reasons

    # Also check if description indicates physical/culinary/manufacturing non-tech role
    for pat in [r"\bcommis\b", r"\btablet\s*manufacturing\b", r"\bpaint\s*formulation\b", r"\bvideo\s*kyc\b"]:
        if re.search(pat, full_text) and not any(re.search(tp, clean_title) for tp in EXPLICIT_TECH_TITLES):
            reasons.append(f"Non-tech role operations in description matching '{pat}'")
            return OpportunityType.UNRELATED, "NON_TECH", reasons

    # 2. Check for experienced roles in title
    for pat in EXPERIENCED_ROLE_PATTERNS:
        match = re.search(pat, clean_title)
        if match:
            reasons.append(f"Senior / experienced title detected matching '{match.group(0)}'")
            return OpportunityType.EXPERIENCED_JOB, "SENIOR_LEADERSHIP", reasons

    # 3. Collective Off-Campus Drives (Explicit campus drives)
    for pat in COLLECTIVE_DRIVE_PATTERNS:
        match = re.search(pat, clean_title)
        if match:
            # Bare non-tech analyst or operations drive check
            if re.search(r"\banalyst(?:\s*role)?\b", clean_title) and not any(re.search(tp, clean_title) for tp in EXPLICIT_TECH_TITLES):
                if not any(k in full_text for k in ["software", "developer", "coding", "programming", "python", "java", "sql", "data structures"]):
                    reasons.append("Non-tech / generic analyst role in off-campus drive")
                    return OpportunityType.UNRELATED, "NON_TECH", reasons

            is_recognized_tech_exam = any(re.search(p, clean_title) for p in [r"\bnqt\b", r"\bgenc\b", r"\belite\b", r"\bamcat\b", r"\belitmus\b"])
            has_tech_signal = any(re.search(tp, clean_title) for tp in EXPLICIT_TECH_TITLES) or any(
                w in full_text for w in [
                    "software", "developer", "engineer", "programming", "coding", "java", "python",
                    "data structures", "cloud", "devops", "qa", "apprentice", "trainee", "b.tech", "btech", "mca", "b.e"
                ]
            )
            if is_recognized_tech_exam or has_tech_signal:
                reasons.append(f"Collective campus recruitment drive detected matching '{match.group(0)}'")
                return OpportunityType.OFF_CAMPUS_DRIVE, "TECHNOLOGY_CAMPUS_DRIVE", reasons
            else:
                reasons.append("Non-tech / unspecified domain campus drive without software engineering keywords")
                return OpportunityType.UNRELATED, "NON_TECH", reasons

    if re.search(r"\boff[\s-]?campus\s*drive\b", full_text) and any(k in full_text for k in ["engineering", "be", "btech", "mca", "bca", "software"]):
        reasons.append("Off-campus drive announced in posting body")
        return OpportunityType.OFF_CAMPUS_DRIVE, "TECHNOLOGY_CAMPUS_DRIVE", reasons

    # 4. Graduate Trainee Programs
    for pat in GRADUATE_TRAINEE_PATTERNS:
        match = re.search(pat, clean_title)
        if match:
            reasons.append(f"Graduate trainee program detected matching '{match.group(0)}'")
            return OpportunityType.GRADUATE_PROGRAM, "GRADUATE_ENGINEERING", reasons

    # 5. Internships
    for pat in INTERNSHIP_PATTERNS:
        match = re.search(pat, clean_title)
        if match:
            # Must be tech internship
            if any(re.search(tp, clean_title) for tp in EXPLICIT_TECH_TITLES) or any(k in full_text for k in ["software", "developer", "coding", "python", "java"]):
                reasons.append(f"Technology internship detected matching '{match.group(0)}'")
                return OpportunityType.INTERNSHIP, "TECHNOLOGY_INTERNSHIP", reasons
            else:
                reasons.append("Non-tech or unspecified internship")
                return OpportunityType.UNRELATED, "NON_TECH", reasons

    # 6. Explicit Technology Fresher Job
    for pat in EXPLICIT_TECH_TITLES:
        match = re.search(pat, clean_title)
        if match:
            reasons.append(f"Individual technology fresher role matching '{match.group(0)}'")
            return OpportunityType.INDIVIDUAL_FRESHER_JOB, "SOFTWARE_ENGINEERING", reasons

    # Fallback: Check if description explicitly specifies software engineering
    if any(k in full_text for k in ["software development", "programming in python", "writing clean code", "core java", "backend engineering", "frontend development"]):
        reasons.append("Technology role identified from description content")
        return OpportunityType.INDIVIDUAL_FRESHER_JOB, "SOFTWARE_ENGINEERING", reasons

    # FAIL-SAFE: Unmatched generic roles are NEVER classified as tech!
    reasons.append("Non-tech role / domain: No positive software engineering or IT signal found")
    return OpportunityType.UNRELATED, "NON_TECH", reasons
