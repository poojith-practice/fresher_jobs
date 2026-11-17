"""Application Deadline & Live Status Verification Engine.

Operates in Asia/Kolkata timezone to verify deadline expiry and portal status.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Tuple, Optional
import zoneinfo

TZ_KOLKATA = zoneinfo.ZoneInfo("Asia/Kolkata")

EXPIRED_PATTERNS = [
    r"\bapplication[s]?\s+(?:(?:are|is|now|been|currently)\s+)*closed\b",
    r"\bregistration[s]?\s+(?:(?:are|is|now|been|currently)\s+)*closed\b",
    r"\bdrive\s+(?:(?:is|has|been|now)\s+)*(?:ended|concluded|over)\b",
    r"\bjob\s+(?:(?:is|has)\s+)*expired\b",
    r"\bno\s+longer\s+accepting\s+applications\b",
    r"\bdeadline\s+(?:(?:has|is|now)\s+)*(?:passed|over)\b",
]

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_string(date_str: str) -> Optional[datetime]:
    """Tries to parse diverse Indian job deadline formats into a timezone-aware datetime."""
    s = date_str.strip()
    # ISO format: 2026-11-25T18:00:00 or 2026-11-25
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ_KOLKATA)
        return dt
    except Exception:
        pass

    # Regex: 25 Nov 2026 or 25th November 2026
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-zA-Z]{3,9})\s+(\d{4})", s)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)[:3].lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(month_str)
        if month:
            # Assume end of day 23:59:59 IST
            return datetime(year, month, day, 23, 59, 59, tzinfo=TZ_KOLKATA)

    # Regex: 2026/11/25 or 25-11-2026
    m2 = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m2:
        day = int(m2.group(1))
        month = int(m2.group(2))
        year = int(m2.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return datetime(year, month, day, 23, 59, 59, tzinfo=TZ_KOLKATA)

    return None


def verify_application_status(
    deadline_str: Optional[str] = None,
    text_content: str = "",
    explicit_status: Optional[str] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """Evaluates live recruitment status against current Asia/Kolkata time.
    
    Returns:
        (status, deadline_evidence, status_reason)
    """
    now = datetime.now(TZ_KOLKATA)

    # 1. Explicit status passed from source (e.g. isDriveEnded from JoinSaarthi)
    if explicit_status and explicit_status.upper() in {"CLOSED", "EXPIRED"}:
        return "CLOSED", None, f"Source metadata explicitly marks drive as {explicit_status.upper()}"

    # 2. Check explicit deadline_str if provided
    if deadline_str:
        dt = parse_date_string(deadline_str)
        if dt:
            if dt < now:
                return "EXPIRED", deadline_str, f"Application deadline of {dt.strftime('%Y-%m-%d %H:%M %Z')} has passed (current: {now.strftime('%Y-%m-%d %H:%M %Z')})"
            # Check if text reports premature closure despite valid deadline
            for exp_pat in EXPIRED_PATTERNS:
                match = re.search(exp_pat, text_content, re.IGNORECASE)
                if match:
                    return "CLOSED", deadline_str, f"Explicit closed notice found: '{match.group(0)}' despite deadline"
            return "OPEN", deadline_str, f"Active deadline verified until {dt.strftime('%Y-%m-%d %H:%M %Z')}"

    # 3. Check for explicit closed notices in text
    for exp_pat in EXPIRED_PATTERNS:
        match = re.search(exp_pat, text_content, re.IGNORECASE)
        if match:
            return "CLOSED", None, f"Explicit closed notice found: '{match.group(0)}'"

    # 4. Search for deadline pattern in text: e.g. "Last date: 20 Nov 2026"
    m = re.search(r"(?:last\s+date|deadline|registration\s+ends|walk[\s-]?in\s+date)[:\s]+([^\n\r,]+)", text_content, re.IGNORECASE)
    if m:
        extracted_deadline = m.group(1).strip()
        dt = parse_date_string(extracted_deadline)
        if dt:
            if dt < now:
                return "EXPIRED", extracted_deadline, f"Application deadline of {dt.strftime('%Y-%m-%d %H:%M %Z')} has passed (current: {now.strftime('%Y-%m-%d %H:%M %Z')})"
            else:
                return "OPEN", extracted_deadline, f"Active deadline verified until {dt.strftime('%Y-%m-%d %H:%M %Z')}"

    # 5. If no deadline could be parsed and no closed notice found, status is UNKNOWN
    # Critical Rule: Never silently label UNKNOWN as OPEN
    return "UNKNOWN", None, "No explicit application deadline or closing notice found in listing"
