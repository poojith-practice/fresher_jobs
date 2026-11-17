"""
Company Authenticity, Domain Corroboration & Scam Detection
===========================================================
Validates employer identity against official registries, verifies career portal domains,
and screens for upfront fee / training fee recruitment scams.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from models.verification_result import CompanyAuthenticity

logger = logging.getLogger("verification.company")

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "employer_registry.json"

MULTI_TENANT_ATS_DOMAINS = [
    "myworkdayjobs.com", "taleo.net", "brassring.com", "greenhouse.io", "lever.co",
    "smartrecruiters.com", "ashbyhq.com", "teamtailor.com", "personio.de", "recruitee.com",
    "oraclecloud.com", "icims.com", "successfactors.com", "successfactors.eu",
    "njoyn.com", "jobvite.com", "adp.com", "workday.com", "phenompeople.com",
    "eightfold.ai", "avature.net", "joinsuperset.com",
]

OFFICIAL_ENTERPRISE_DOMAINS = MULTI_TENANT_ATS_DOMAINS

REPUTABLE_AGGREGATOR_DOMAINS = [
    "elitmus.com", "joinsaarthi.com", "campusdrive.in", "useastra.in",
    "hirastra.com", "jobs4fresher.com", "freshersnow.com", "prepinsta.com",
    "freshersdunia.com",
]

FRAUD_PATTERNS = [
    r"\b(?:pay|mandatory|require[ds]?|deposit|charge[ds]?)\s+(?:a\s+)?registration\s+fees?\b",
    r"\bregistration\s+fees?\s+(?:of|is|\brequired\b|mandatory)\b",
    r"\bnon[\s-]?refundable\s+registration\s+fee\b",
    r"\bprocessing\s+charges?\b",
    r"\bsecurity\s+deposit\b",
    r"\bpay\s+(?:rs|inr|\$|\d+)\s+(?:for|before)\s+(?:interview|training|offer)\b",
    r"\btraining\s+fees?\b",
    r"\bplacement\s+charges?\b",
    r"\b100%\s+guaranteed\s+job\s+offer\s+after\s+payment\b",
]


def load_employer_domains() -> Dict[str, List[str]]:
    """Loads employer domain lookup map from employer_registry.json."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
        domain_map = {}
        for item in registry:
            cname = (item.get("name") or "").lower()
            domains = item.get("official_domains", [])
            domain_map[cname] = domains
            for alias in item.get("aliases", []):
                domain_map[alias.lower()] = domains
        return domain_map
    except Exception as exc:
        logger.error("[company_verifier] Failed to load registry domains: %s", exc)
        return {}


def load_reverse_employer_domains() -> Dict[str, Tuple[str, List[str]]]:
    """Loads reverse domain-to-employer owner lookup map with aliases."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
        reverse_map: Dict[str, Tuple[str, List[str]]] = {}
        for item in registry:
            cname = item.get("name") or ""
            aliases = [a.lower() for a in item.get("aliases", [])]
            for d in item.get("official_domains", []):
                d_clean = d.lower()
                if d_clean not in MULTI_TENANT_ATS_DOMAINS:
                    reverse_map[d_clean] = (cname, aliases)
        return reverse_map
    except Exception as exc:
        logger.error("[company_verifier] Failed to load reverse domains: %s", exc)
        return {}


def verify_company_authenticity(
    company: str,
    apply_url: str,
    text_content: str = "",
) -> Tuple[CompanyAuthenticity, List[str], List[str]]:
    """Evaluates company authenticity, official portal backing, and screens for fraud.
    
    Returns:
        (verification_status, supporting_evidence, contradiction_flags)
    """
    supporting = []
    contradictions = []

    # 1. Screen for upfront payment or training fee scams (with question & negation awareness)
    full_text = f"{company} {text_content}".lower()
    for sentence in re.split(r"[\n;]", full_text):
        sentence_clean = sentence.strip()
        if not sentence_clean:
            continue

        # If sentence is an FAQ question or inquiry, do not treat as a fraud demand
        is_faq_question = "?" in sentence_clean or any(
            sentence_clean.startswith(q) for q in ["is there", "are there", "do i", "do candidates", "can i", "what is", "how much"]
        ) or "frequently asked questions" in sentence_clean or "faq" in sentence_clean
        if is_faq_question:
            continue

        # If the sentence states no fee/deposit is demanded, skip it
        if any(w in sentence_clean for w in ["never", "no", "not", "without", "zero", "free", "neither", "nil", "none"]):
            continue

        for fraud_pat in FRAUD_PATTERNS:
            match = re.search(fraud_pat, sentence_clean, re.IGNORECASE)
            if match:
                # Neighborhood check: check 50 characters around match for negation
                idx = sentence_clean.find(match.group(0).lower())
                window = sentence_clean[max(0, idx - 40):min(len(sentence_clean), idx + len(match.group(0)) + 40)]
                if any(w in window for w in ["never", "no", "not", "without", "zero", "free", "neither", "nil", "none"]):
                    continue
                contradictions.append(f"Severe scam signal: Upfront fee demand detected ('{match.group(0)}')")
                return CompanyAuthenticity.FRAUDULENT, supporting, contradictions

    # 2. Extract domain from application URL
    domain = ""
    try:
        parsed = urlparse(apply_url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        pass

    # 3. Cross-reference against official enterprise domains & employer registry
    domain_map = load_employer_domains()
    reverse_map = load_reverse_employer_domains()
    comp_clean = company.lower().strip()

    # Detect employer brand conflicts: If domain belongs to Company A, but posting is for Company B
    for owned_domain, (owner_name, aliases) in reverse_map.items():
        if domain.endswith(owned_domain) or domain == owned_domain:
            owner_clean = owner_name.lower()
            owner_first = owner_clean.split()[0]
            is_match = (
                owner_clean in comp_clean
                or owner_first in comp_clean
                or comp_clean in owner_clean
                or any(alias in comp_clean or comp_clean in alias for alias in aliases)
            )
            if not is_match:
                contradictions.append(
                    f"Employer mismatch: Posting claims to be for '{company}' but application portal belongs to '{owner_name}' ({domain})"
                )
                return CompanyAuthenticity.SUSPICIOUS, supporting, contradictions

    registered_domains = domain_map.get(comp_clean, [])
    if registered_domains and any(domain.endswith(d) or domain == d for d in registered_domains):
        supporting.append(f"Application hosted on verified employer corporate domain: {domain}")
        return CompanyAuthenticity.VERIFIED_OFFICIAL, supporting, []

    # Check against known enterprise ATS domains
    if any(domain.endswith(off_d) or domain == off_d for off_d in OFFICIAL_ENTERPRISE_DOMAINS):
        supporting.append(f"Application hosted on verified enterprise ATS portal: {domain}")
        return CompanyAuthenticity.VERIFIED_OFFICIAL, supporting, []

    # Corroborate by company name keywords in domain (e.g. jobs.natwestgroup.com for NatWest)
    generic_words = {
        "group", "india", "private", "limited", "technologies", "technology", "services",
        "corporation", "solutions", "international", "global", "off", "campus", "hiring",
        "drive", "careers", "unknown", "stealth", "startup", "confidential", "anonymous",
        "employer", "company", "tech", "enterprise", "system", "systems", "network", "networks",
        "pvt", "ltd", "corp", "inc", "llc", "jobs", "career",
    }
    if comp_clean not in ["unknown", "unknown employer", "stealth startup", "confidential", "anonymous"]:
        comp_tokens = [w for w in re.split(r"\W+", comp_clean) if len(w) >= 3 and w not in generic_words]
        domain_parts = domain.split(".")
        domain_stem = domain_parts[-2] if len(domain_parts) >= 2 else domain_parts[0]
        for token in comp_tokens:
            if token in domain_stem or (len(domain_parts) > 2 and token in domain_parts[0]):
                supporting.append(f"Application hosted on corroborated employer portal: {domain}")
                return CompanyAuthenticity.VERIFIED_OFFICIAL, supporting, []

    # Check if aggregator domain
    if any(domain.endswith(agg_d) or domain == agg_d for agg_d in REPUTABLE_AGGREGATOR_DOMAINS):
        supporting.append(f"Opportunity listed via tracked placement aggregator: {domain}")
        return CompanyAuthenticity.REPUTABLE_AGGREGATOR, supporting, []

    if not domain:
        contradictions.append("Missing or unparseable application URL domain")
        return CompanyAuthenticity.UNCORROBORATED, supporting, contradictions

    supporting.append(f"External unverified domain: {domain}")
    return CompanyAuthenticity.UNCORROBORATED, supporting, []
