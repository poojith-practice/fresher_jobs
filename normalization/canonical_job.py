"""Canonical job record and cross-source deduplication.

The scraper keeps board-specific column names because JobSpy, the harvester
adapters and the discovery layer all speak slightly different dialects. This
module produces one stable, documented shape so downstream consumers (Google
Sheets, the API, n8n, PostgreSQL) do not need to know which adapter ran.

Deduplication is deliberately conservative: a job is a duplicate only when its
normalised URL matches, or else when company + title + city all match. A shared
title alone is never enough, because "Data Analyst" at two companies or in two
cities is two different jobs.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

CANONICAL_FIELDS = [
    "job_id",
    "source",
    "job_title",
    "company",
    "location",
    "experience_required",
    "employment_type",
    "salary",
    "job_description",
    "posted_date",
    "job_url",
    "is_fresher_eligible",
    "scraped_at",
    "also_seen_on",
]

_TRACKING_PARAMS = {"ref", "refid", "trk", "trackingid", "originalsubdomain", "position", "pagenum", "utm_source", "utm_medium", "utm_campaign"}

_LEGAL_SUFFIXES = re.compile(
    r"\b(?:private|pvt|limited|ltd|llp|inc|incorporated|corp|corporation|"
    r"technologies|technology|solutions|services|systems|consulting|group)\b"
)

_TITLE_NOISE = re.compile(
    r"\b(?:hiring|urgent|apply|now|immediate|joiner|joiners|remote|onsite|"
    r"walk ?in|off ?campus|fresher|freshers|internship|job|opening|openings)\b"
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat", "null"} else text


def normalize_url(url: str) -> str:
    """Strip tracking parameters and trailing slashes for stable matching."""
    raw = _text(url)
    if not raw:
        return ""
    try:
        parsed = urlparse(raw.lower())
        query = [
            (k, v)
            for k, v in parse_qsl(parsed.query)
            if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
        ]
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", urlencode(query), "")
        )
    except Exception:
        return raw.lower().rstrip("/")


def normalize_company(company: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", _text(company).lower())
    text = _LEGAL_SUFFIXES.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9+#.\s]", " ", _text(title).lower())
    text = _TITLE_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_city(location: str) -> str:
    text = _text(location).lower()
    if not text:
        return ""
    first = re.split(r"[,/|(]", text)[0]
    return re.sub(r"[^a-z\s]", " ", first).strip()


def dedup_key(record: Dict[str, Any]) -> Tuple[str, str]:
    """Return (url_key, composite_key) for a canonical record."""
    return (
        normalize_url(record.get("job_url", "")),
        "|".join(
            [
                normalize_company(record.get("company", "")),
                normalize_title(record.get("job_title", "")),
                normalize_city(record.get("location", "")),
            ]
        ),
    )


def _salary_text(job: Dict[str, Any]) -> str:
    display = _text(job.get("salary_display"))
    if display and display.lower() != "not mentioned":
        return display
    low = _text(job.get("min_amount"))
    high = _text(job.get("max_amount"))
    if low and high and low.lower() not in {"not mentioned", "nan"}:
        return f"{low} - {high}"
    label = _text(job.get("salary"))
    return "" if label.lower() in {"nan", "none"} else label


def _job_url(job: Dict[str, Any]) -> str:
    for key in ("apply_url", "job_url_direct", "job_url", "url"):
        value = _text(job.get(key))
        if value.startswith("http"):
            return value
    return ""


def _posted_date(job: Dict[str, Any]) -> str:
    value = _text(job.get("date_posted"))
    return value


def to_canonical(job: Dict[str, Any]) -> Dict[str, Any]:
    """Map one internal job dict onto the canonical schema.

    Missing optional fields stay empty; they never cause the job to be dropped.
    """
    title = _text(job.get("title") or job.get("job_title") or job.get("Job Title"))
    company = _text(job.get("company") or job.get("Company"))
    url = _job_url(job)
    source = _text(job.get("site") or job.get("source")).lower() or "unknown"

    digital = hashlib.sha1(
        f"{source}|{url}|{company.lower()}|{title.lower()}".encode("utf-8", "ignore")
    ).hexdigest()[:16]

    eligible = job.get("is_valid_fresher_job")
    if eligible is None:
        eligible = job.get("llm_eligible")
    eligible = bool(eligible) if eligible is not None else False

    record = {
        "job_id": _text(job.get("id")) or f"{source}-{digital}",
        "source": source,
        "job_title": title,
        "company": company,
        "location": _text(job.get("location")),
        "experience_required": _text(job.get("experience_range")),
        "employment_type": _text(job.get("job_type") or job.get("employment_type")),
        "salary": _salary_text(job),
        "job_description": _text(job.get("description") or job.get("job_requirement"))[:20000],
        "posted_date": _posted_date(job),
        "job_url": url,
        "is_fresher_eligible": eligible,
        "scraped_at": _text(job.get("scraped_at"))
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "also_seen_on": [],
    }
    return record


def deduplicate(jobs: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Collapse duplicates across sources, preserving provenance.

    Returns ``(unique_records, duplicate_count)``.
    """
    unique: List[Dict[str, Any]] = []
    by_url: Dict[str, int] = {}
    by_composite: Dict[str, int] = {}
    duplicates = 0

    for job in jobs:
        record = to_canonical(job)
        url_key, composite_key = dedup_key(record)

        index = by_url.get(url_key) if url_key else None
        if index is None and composite_key.strip("|"):
            index = by_composite.get(composite_key)

        if index is not None:
            duplicates += 1
            existing = unique[index]
            other = record["source"]
            if other and other != existing["source"] and other not in existing["also_seen_on"]:
                existing["also_seen_on"].append(other)
            # Prefer the richer record for optional fields.
            for field_name in ("job_description", "salary", "experience_required", "posted_date"):
                if not existing.get(field_name) and record.get(field_name):
                    existing[field_name] = record[field_name]
            if record.get("is_fresher_eligible"):
                existing["is_fresher_eligible"] = True
            continue

        unique.append(record)
        if url_key:
            by_url[url_key] = len(unique) - 1
        if composite_key.strip("|"):
            by_composite.setdefault(composite_key, len(unique) - 1)

    return unique, duplicates
