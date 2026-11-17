"""
Application Deadline & Live Status Verification Engine
======================================================
Evaluates recruitment deadlines and live application status against Asia/Kolkata clock.
Strictly identifies expired drives (e.g. 20 October 2026 when current date is November 2026)
and closed portal notices.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional, Tuple, List
import zoneinfo

from core.models import DeadlineStatus, ApplicationStatus

TZ_KOLKATA = zoneinfo.ZoneInfo("Asia/Kolkata")

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

EXPIRED_PATTERNS = [
    r"\bapplication[s]?\s+(?:(?:are|is|now|been|currently)\s+)*closed\b",
    r"\bregistration[s]?\s+(?:(?:are|is|now|been|currently)\s+)*closed\b",
    r"\bdrive\s+(?:(?:is|has|been|now)\s+)*(?:ended|concluded|over)\b",
    r"\bjob\s+(?:(?:is|has)\s+)*expired\b",
    r"\bno\s+longer\s+accepting\s+applications\b",
    r"\bdeadline\s+(?:(?:has|is|now)\s+)*(?:passed|over)\b",
]


def parse_deadline_datetime(date_str: str) -> Optional[datetime]:
    """Parses diverse Indian job deadline formats into timezone-aware Asia/Kolkata datetime."""
    s = date_str.strip()
    # 1. ISO format: 2026-11-25 or 2026-11-25T18:00:00
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_KOLKATA)
        return dt
    except Exception:
        pass

    # 2. Format: "20 October 2026" or "20th Oct 2026"
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-zA-Z]{3,9})\s+(\d{4})", s)
    if m:
        day = int(m.group(1))
        m_str = m.group(2).lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(m_str) or MONTH_MAP.get(m_str[:3])
        if month and 1 <= day <= 31:
            return datetime(year, month, day, 23, 59, 59, tzinfo=TZ_KOLKATA)

    # 3. Format: "October 20, 2026"
    m2 = re.search(r"([a-zA-Z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m2:
        m_str = m2.group(1).lower()
        day = int(m2.group(2))
        year = int(m2.group(3))
        month = MONTH_MAP.get(m_str) or MONTH_MAP.get(m_str[:3])
        if month and 1 <= day <= 31:
            return datetime(year, month, day, 23, 59, 59, tzinfo=TZ_KOLKATA)

    # 4. Format: "20-10-2026" or "20/10/2026"
    m3 = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m3:
        day = int(m3.group(1))
        month = int(m3.group(2))
        year = int(m3.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return datetime(year, month, day, 23, 59, 59, tzinfo=TZ_KOLKATA)

    return None


def verify_application_deadline(
    deadline_str: Optional[str] = None,
    text_content: str = "",
    explicit_status: Optional[str] = None,
) -> Tuple[DeadlineStatus, ApplicationStatus, Optional[str], List[str]]:
    """Evaluates live application status and deadlines against Asia/Kolkata clock.
    
    Returns:
        (deadline_status, application_status, parsed_deadline_iso, rejection_reasons)
    """
    now = datetime.now(TZ_KOLKATA)
    rejection_reasons = []

    # 1. Explicit closed status from source (e.g. JoinSaarthi isDriveEnded)
    if explicit_status and explicit_status.upper() in {"CLOSED", "EXPIRED"}:
        rejection_reasons.append(f"Opportunity explicitly marked as {explicit_status.upper()} by source")
        return DeadlineStatus.CLOSED, ApplicationStatus.CLOSED, None, rejection_reasons

    # 2. Check explicit deadline string if provided
    if deadline_str:
        dt = parse_deadline_datetime(deadline_str)
        if dt:
            iso_str = dt.strftime("%Y-%m-%d")
            if dt < now:
                rejection_reasons.append(
                    f"Application deadline of {dt.strftime('%d %B %Y')} has expired (current date: {now.strftime('%d %B %Y')})"
                )
                return DeadlineStatus.EXPIRED, ApplicationStatus.CLOSED, iso_str, rejection_reasons
            
            # Check if text reports premature closure despite future date
            for exp_pat in EXPIRED_PATTERNS:
                match = re.search(exp_pat, text_content, re.IGNORECASE)
                if match:
                    rejection_reasons.append(f"Application closed notice in text: '{match.group(0)}'")
                    return DeadlineStatus.CLOSED, ApplicationStatus.CLOSED, iso_str, rejection_reasons

            # Deadline is in future, but live application status requires live page verification
            return DeadlineStatus.OPEN, ApplicationStatus.UNKNOWN, iso_str, []

    # 3. Check text content for closed notice
    for exp_pat in EXPIRED_PATTERNS:
        match = re.search(exp_pat, text_content, re.IGNORECASE)
        if match:
            rejection_reasons.append(f"Application closed notice in text: '{match.group(0)}'")
            return DeadlineStatus.CLOSED, ApplicationStatus.CLOSED, None, rejection_reasons

    # 4. Search text content for deadline pattern (e.g. "Last date: 20 October 2026")
    m = re.search(r"(?:last\s+date(?:\s+to\s+register)?|deadline|registration\s+ends|apply\s+before)[:\s]+([^\n\r,.;]+)", text_content, re.IGNORECASE)
    if m:
        candidate_deadline = m.group(1).strip()
        dt = parse_deadline_datetime(candidate_deadline)
        if dt:
            iso_str = dt.strftime("%Y-%m-%d")
            if dt < now:
                rejection_reasons.append(
                    f"Application deadline of {dt.strftime('%d %B %Y')} has expired (current date: {now.strftime('%d %B %Y')})"
                )
                return DeadlineStatus.EXPIRED, ApplicationStatus.CLOSED, iso_str, rejection_reasons
            return DeadlineStatus.OPEN, ApplicationStatus.UNKNOWN, iso_str, []

    # 5. No explicit deadline or closure found - absence of evidence is NOT evidence of openness
    return (
        DeadlineStatus.NOT_PUBLISHED,
        ApplicationStatus.UNKNOWN,
        None,
        [],
    )
