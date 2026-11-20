"""
Filter Engine for Fresher Job Listings
======================================
Strict verification pipeline that ensures:
1. Freshness: Posted strictly within the last 48 hours.
2. Experience: Strictly for freshers (0 to 1 year max, rejecting all senior/experienced roles).
3. Legitimacy: Excludes training institutes, scam consultancies, and unpaid schemes.
4. Categorization: Maps each job to one of the 5 requested tracks.
"""

import math
import re
from datetime import datetime, date, timedelta, time
from typing import Tuple, Optional, Dict, Any, List, Union

from config import (
    MAX_HOURS_OLD,
    MAX_ALLOWED_EXPERIENCE_YEARS,
    FORBIDDEN_TITLE_KEYWORDS,
    FORBIDDEN_JOB_LEVELS,
    COMPANY_BLACKLIST,
    FORBIDDEN_DESCRIPTION_PATTERNS,
)


def _text(value: Any) -> str:
    """Normalize JobSpy's nullable/NaN fields to safe strings."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


class DatePrecision:
    EXACT_TIMESTAMP = "exact_timestamp"
    DATE_ONLY = "date_only"
    RELATIVE_DATE = "relative_date"
    UNKNOWN = "unknown"


class DateParseResult:
    """
    Structured date parsing result preserving date precision and time intervals.
    Unpacks as (datetime, precision) for tuple compatibility, while also
    providing direct attribute access (.dt, .precision, .interval).
    """

    def __init__(
        self,
        dt: Optional[datetime],
        precision: str,
        interval: Optional[Tuple[datetime, datetime]] = None,
    ):
        self.dt = dt
        self.precision = precision
        self.interval = interval

    def __iter__(self):
        yield self.dt
        yield self.precision

    def __getitem__(self, index):
        if index == 0:
            return self.dt
        elif index == 1:
            return self.precision
        raise IndexError("Index out of range for DateParseResult")

    def __eq__(self, other):
        if other is None:
            return self.dt is None
        if isinstance(other, datetime):
            return self.dt == other
        if isinstance(other, tuple) and len(other) == 2:
            return (self.dt, self.precision) == other
        return super().__eq__(other)

    def __repr__(self):
        return f"DateParseResult(dt={self.dt}, precision='{self.precision}', interval={self.interval})"


def parse_date_posted(
    date_val: Any,
    return_precision: bool = False,
    now: Optional[datetime] = None,
) -> Union[Optional[datetime], DateParseResult]:
    """
    Parses various date_posted formats from LinkedIn, Indeed, and Naukri
    into a standardized Python datetime object with precision metadata.

    Preserves whether the timestamp is an exact datetime, a calendar-date interval
    (date_only), or a relative string (relative_date). Never invents an exact midnight
    timestamp as the definite posting time for a date-only entry.
    """
    if date_val is None:
        return None

    ref_now = now or datetime.now()

    # 1. Exact datetime object
    if isinstance(date_val, datetime):
        dt = date_val
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        res = DateParseResult(dt=dt, precision=DatePrecision.EXACT_TIMESTAMP)
        return (res.dt, res.precision) if return_precision else res

    # 2. Calendar date object (date-only)
    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        # A date-only posting represents the entire 24-hour interval [00:00:00, 23:59:59.999999]
        d_start = datetime.combine(date_val, time.min)
        d_end = datetime.combine(date_val, time.max)
        # Conservative dt: latest possible time on that date (avoids false age inflation)
        res = DateParseResult(
            dt=d_end,
            precision=DatePrecision.DATE_ONLY,
            interval=(d_start, d_end),
        )
        return (res.dt, res.precision) if return_precision else res

    val_str = str(date_val).strip()
    if not val_str or val_str.lower() in {"nan", "nat", "none", "null"}:
        return None

    val_lower = val_str.lower()

    # 3. Relative date patterns
    if "just posted" in val_lower or val_lower == "today":
        d_start = datetime.combine(ref_now.date(), time.min)
        res = DateParseResult(
            dt=ref_now,
            precision=DatePrecision.RELATIVE_DATE,
            interval=(d_start, ref_now),
        )
        return (res.dt, res.precision) if return_precision else res

    hour_match = re.search(r"(\d+)\s+hour", val_lower)
    if hour_match:
        hours = int(hour_match.group(1))
        dt = ref_now - timedelta(hours=hours)
        res = DateParseResult(dt=dt, precision=DatePrecision.RELATIVE_DATE)
        return (res.dt, res.precision) if return_precision else res

    minute_match = re.search(r"(\d+)\s+minute", val_lower)
    if minute_match:
        mins = int(minute_match.group(1))
        dt = ref_now - timedelta(minutes=mins)
        res = DateParseResult(dt=dt, precision=DatePrecision.RELATIVE_DATE)
        return (res.dt, res.precision) if return_precision else res

    if "yesterday" in val_lower:
        yesterday_date = ref_now.date() - timedelta(days=1)
        d_start = datetime.combine(yesterday_date, time.min)
        d_end = datetime.combine(yesterday_date, time.max)
        res = DateParseResult(
            dt=d_end,
            precision=DatePrecision.RELATIVE_DATE,
            interval=(d_start, d_end),
        )
        return (res.dt, res.precision) if return_precision else res

    days_match = re.search(r"(\d+)\s+day", val_lower)
    if days_match:
        days = int(days_match.group(1))
        target_date = ref_now.date() - timedelta(days=days)
        d_start = datetime.combine(target_date, time.min)
        d_end = datetime.combine(target_date, time.max)
        res = DateParseResult(
            dt=d_end,
            precision=DatePrecision.RELATIVE_DATE,
            interval=(d_start, d_end),
        )
        return (res.dt, res.precision) if return_precision else res

    weeks_match = re.search(r"(\d+)\s+week", val_lower)
    if weeks_match:
        weeks = int(weeks_match.group(1))
        target_date = ref_now.date() - timedelta(weeks=weeks)
        d_start = datetime.combine(target_date, time.min)
        d_end = datetime.combine(target_date, time.max)
        res = DateParseResult(
            dt=d_end,
            precision=DatePrecision.RELATIVE_DATE,
            interval=(d_start, d_end),
        )
        return (res.dt, res.precision) if return_precision else res

    # 4. Try full ISO / formatted timestamp WITH time component
    if any(c in val_str for c in ("T", " ", ":")):
        try:
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00").replace("z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            res = DateParseResult(dt=dt, precision=DatePrecision.EXACT_TIMESTAMP)
            return (res.dt, res.precision) if return_precision else res
        except Exception:
            pass

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
            try:
                dt = datetime.strptime(val_str[:19], fmt)
                res = DateParseResult(dt=dt, precision=DatePrecision.EXACT_TIMESTAMP)
                return (res.dt, res.precision) if return_precision else res
            except (ValueError, IndexError):
                pass

    # 5. Date-only strings: YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            parsed_d = datetime.strptime(val_str[:10], fmt).date()
            d_start = datetime.combine(parsed_d, time.min)
            d_end = datetime.combine(parsed_d, time.max)
            res = DateParseResult(
                dt=d_end,
                precision=DatePrecision.DATE_ONLY,
                interval=(d_start, d_end),
            )
            return (res.dt, res.precision) if return_precision else res
        except (ValueError, IndexError):
            pass

    return None


def is_within_hours(
    date_val: Any,
    max_hours: int = MAX_HOURS_OLD,
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """
    Verifies if a job was posted within the allowed hours limit.
    Correctly distinguishes exact timestamps, date-only intervals, and relative dates.

    Date-only freshness policy:
    A date-only posting represents a calendar-date interval [date 00:00:00, date 23:59:59.999999].
    Because the board omitted the exact time, we do not fabricate midnight or penalize the posting.
    Instead, we determine whether the possible posting-time interval overlaps the configured
    freshness window [now - max_hours, now].
    If the date is in the future, it is rejected as invalid.
    If the interval's latest possible time (23:59:59) is older than (now - max_hours), it is rejected as too old.
    If the interval overlaps the freshness window, it is accepted with date_only precision.
    """
    ref_now = now or datetime.now()
    parsed_res = parse_date_posted(date_val, now=ref_now)
    if parsed_res is None or (isinstance(parsed_res, DateParseResult) and parsed_res.dt is None):
        return False, "Posting date unavailable; cannot verify freshness"

    if isinstance(parsed_res, DateParseResult):
        precision = parsed_res.precision
        parsed_dt = parsed_res.dt
        interval = parsed_res.interval
    else:
        parsed_dt = parsed_res
        precision = DatePrecision.EXACT_TIMESTAMP
        interval = None

    # Handle interval-based evaluations (date_only or relative date with interval)
    if interval is not None:
        int_start, int_end = interval

        # Future date check
        if int_start > ref_now:
            return False, f"Future posting date ({date_val}); invalid date"

        window_start = ref_now - timedelta(hours=max_hours)
        window_end = ref_now

        # If latest possible posting time is older than window start -> definitely too old
        if int_end < window_start:
            min_age_hours = (ref_now - int_end).total_seconds() / 3600.0
            return (
                False,
                f"Too old: date-only posting ({date_val}) latest possible time was {min_age_hours:.1f}h ago "
                f"(> {max_hours}h limit; {precision} precision)",
            )

        # Interval overlaps [window_start, window_end]
        if int_end >= window_start and int_start <= window_end:
            min_age = max(0.0, (ref_now - int_end).total_seconds() / 3600.0)
            max_age = (ref_now - int_start).total_seconds() / 3600.0
            return (
                True,
                f"Date-only posting ({date_val}) overlaps {max_hours}h freshness window "
                f"(possible age {min_age:.1f}h to {max_age:.1f}h; {precision} precision)",
            )

        return False, f"Posting date ({date_val}) outside {max_hours}h freshness window"

    # Exact timestamp evaluation
    if parsed_dt.tzinfo is not None:
        parsed_dt = parsed_dt.astimezone().replace(tzinfo=None)

    age_hours = (ref_now - parsed_dt).total_seconds() / 3600.0

    if age_hours < 0:
        return False, f"Future posting timestamp ({parsed_dt}); invalid date"

    if age_hours <= max_hours:
        return True, f"Posted {age_hours:.1f}h ago (within {max_hours}h limit; {precision} precision)"
    else:
        return False, f"Too old: posted {age_hours:.1f}h ago (> {max_hours}h limit; {precision} precision)"


def _has_location_token(text: str, token: str) -> bool:
    """Match short tokens on word boundaries and phrases as substrings."""
    if " " in token:
        return token in text
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def normalize_location_for_search(location: Optional[str], search_city: Optional[str]) -> str:
    """
    Normalize state-only board locations using the city that was searched.

    Indeed frequently returns "MH, India" or "TS, India" instead of a city.
    Rejecting those outright drops every Mumbai result on Indeed, even when the
    search itself was `location=Mumbai`. The query city is valid context for a
    state-level card, so use it as a fallback display and validation value.
    """
    loc = _text(location)
    city = _text(search_city).lower()
    if not loc:
        return ""
    loc_clean = loc.lower().strip()
    if "mumbai" in city and re.fullmatch(r"(?:mh|maharashtra)(?:,\s*india)?", loc_clean):
        return "Mumbai, Maharashtra, India"
    if "hyderabad" in city and re.fullmatch(r"(?:ts|telangana)(?:,\s*india)?", loc_clean):
        return "Hyderabad, Telangana, India"
    return loc


def is_valid_location(
    location: Optional[str],
    search_city: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verifies that the job is located in one of the target tech hubs in India,
    their recognized metropolitan areas / tech corridors, or is explicitly Remote/Hybrid.
    Rejects jobs exclusively in foreign countries.
    """
    loc_clean = _text(location).lower()
    if not loc_clean:
        return False, "Empty location"

    # Reject foreign locations that are explicitly outside India
    foreign_tokens = [
        "united states", "usa", "u.s.", "united kingdom", "london", "dubai", "uae",
        "singapore", "australia", "canada", "germany", "netherlands", "philippines"
    ]
    if any(_has_location_token(loc_clean, ft) for ft in foreign_tokens) and "india" not in loc_clean:
        return False, f"Location '{location}' is in a foreign country outside India"

    # If search_city was provided and matches state-level cards (e.g. Indeed's "MH, India", "KA, India")
    search_city_clean = _text(search_city).lower()
    if search_city_clean:
        return True, f"Valid target location: '{location}' (matched search city '{search_city}')"

    # Recognized Indian tech hub tokens across major tech corridors
    tech_hub_tokens = [
        # Mumbai Metropolitan Region
        "mumbai", "navi mumbai", "thane", "kalyan", "dombivli", "panvel", "bhiwandi",
        "mira bhayandar", "andheri", "bandra", "bkc", "kurla", "goregaon", "malad",
        "powai", "worli", "airoli", "vashi", "mahape", "ghansoli", "belapur", "mmr",
        "mumbai metropolitan region", "mumbai (all areas)", "maharashtra", "mh",
        # Hyderabad
        "hyderabad", "secunderabad", "cyberabad", "telangana", "ts", "hitec city",
        "hitech city", "gachibowli", "madhapur", "kondapur", "kukatpally", "uppal",
        "begumpet", "banjara hills", "jubilee hills", "greater hyderabad area",
        "hyderabad area", "hyderabad(all areas)",
        # Bangalore / Bengaluru
        "bangalore", "bengaluru", "whitefield", "electronic city", "koramangala",
        "indiranagar", "marathahalli", "bellandur", "hebbal", "manyata", "karnataka", "ka",
        # Pune
        "pune", "hinjewadi", "magarpatta", "kharadi", "vimannagar", "viman nagar", "baner",
        "wakad", "hadapsar", "bhosari", "kothrud", "pcmc", "pimpri", "chinchwad",
        # Delhi NCR
        "gurgaon", "gurugram", "noida", "greater noida", "delhi", "new delhi", "delhi ncr",
        "ncr", "faridabad", "ghaziabad", "haryana",
        # Chennai
        "chennai", "omr", "sholinganallur", "guindy", "taramani", "siruseri", "tamil nadu", "tn",
        # Other Tech Cities
        "kolkata", "ahmedabad", "kochi", "cochin", "chandigarh", "mohali", "indore", "jaipur",
        "coimbatore", "trivandrum", "thiruvananthapuram", "bhubaneswar", "lucknow",
        # Remote & Pan-India
        "remote", "work from home", "wfh", "anywhere in india", "pan india", "pan-india", "all india", "hybrid"
    ]

    if any(_has_location_token(loc_clean, tok) for tok in tech_hub_tokens):
        return True, f"Valid target location: '{location}'"

    return False, f"Location '{location}' is not a recognized Indian tech location"


def resolve_apply_url(job: Dict[str, Any]) -> str:
    """
    Extracts or reconstructs a guaranteed valid HTTP/HTTPS apply URL.
    Handles JobSpy platform quirks (e.g. raw LinkedIn numeric IDs).
    """
    direct = _text(job.get("job_url_direct"))
    if direct.startswith("http"):
        return direct

    url = _text(job.get("job_url"))
    if url.startswith("http"):
        return url

    apply = _text(job.get("apply_url"))
    if apply.startswith("http"):
        return apply

    job_id = _text(job.get("id"))
    site = _text(job.get("site")).lower()

    if site == "linkedin" and job_id.isdigit():
        return f"https://www.linkedin.com/jobs/view/{job_id}"
    elif site == "naukri" and job_id.isdigit():
        return f"https://www.naukri.com/job-listings-{job_id}"
    elif site == "indeed" and job_id:
        return f"https://www.indeed.com/viewjob?jk={job_id}"

    if job_id.startswith("http"):
        return job_id

    return ""


def parse_experience_range(exp_str: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Extracts min and max years from experience strings.
    Examples:
      - '0-1 Yrs' -> (0.0, 1.0)
      - '0-2 Yrs' -> (0.0, 2.0)
      - '3-4 Yrs' -> (3.0, 4.0)
      - '7-12 Yrs' -> (7.0, 12.0)
      - 'Fresher' -> (0.0, 0.0)
    """
    if not exp_str:
        return None, None

    exp_clean = str(exp_str).strip().lower()

    if "fresher" in exp_clean:
        return 0.0, 0.0
    # Match ranges written with hyphens, en/em dashes, or "to".
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:[-–—]|to)\s*(\d+(?:\.\d+)?)", exp_clean
    )
    if range_match:
        min_yr = float(range_match.group(1))
        max_yr = float(range_match.group(2))
        if re.search(r"months?|mos?\b", exp_clean[range_match.end():]):
            min_yr /= 12
            max_yr /= 12
        return min_yr, max_yr

    months = re.search(r"(\d+(?:\.\d+)?)\s*(?:months?|mos?)\b", exp_clean)
    if months:
        years = float(months.group(1)) / 12
        return years, years

    # An open-ended requirement such as "5+ years" has no safe upper bound.
    open_ended = re.search(
        r"(\d+(?:\.\d+)?)\s*\+\s*(?P<unit>months?|mos?|yrs?|years?)",
        exp_clean,
    )
    if open_ended:
        yr = float(open_ended.group(1))
        if open_ended.group("unit").startswith(("month", "mo")):
            yr /= 12
        return yr, float("inf")

    # Match "X yrs" / "X years".
    single_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:yr|year)", exp_clean)
    if single_match:
        yr = float(single_match.group(1))
        return yr, yr

    return None, None


def _experience_claims_from_description(description: Optional[str]) -> List[Tuple[float, float]]:
    """Extract explicit experience requirements without an LLM.

    Only considers a numeric duration when the same sentence/line also refers
    to experience. This intentionally errs on the side of rejecting uncertain
    experience claims for a strict fresher pipeline.
    """
    text = _text(description).lower().replace("\u2011", "-")
    claims: List[Tuple[float, float]] = []

    # JDs often put the label and the value on separate lines:
    #     Years of Experience:
    #     5 to 8 years
    # Clause splitting below treats the newline as a boundary, which would
    # separate "experience" from "5 to 8 years" and silently drop the claim.
    # Join a label line to a numeric value on the following line first.
    experience_label = (
        r"(?:years?|yrs?)\s+of\s+(?:relevant\s+|professional\s+|total\s+|work\s+)?experience"
        r"|total\s+experience"
        r"|relevant\s+experience"
        r"|experience\s+(?:required|needed|minimum)"
        r"|experience|exp"
    )
    text = re.sub(
        rf"\b({experience_label})\b\s*[:\-–—]?\s*\n+\s*(?=\d)",
        r"\1 ",
        text,
    )

    # "Experience: 5 - 8" / "Experience: 5+" (unit omitted on the line).
    # Anchored to end-of-line so unrelated numbers (projects, team size) do
    # not become experience claims.
    for bare_match in re.finditer(
        rf"\b(?:{experience_label})\b\s*[:\-–—]\s*"
        r"(\d+(?:\.\d+)?)\s*(?:\+|[-–—]|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?=\r?\n|$)",
        text,
    ):
        lo, hi = float(bare_match.group(1)), float(bare_match.group(2))
        claims.append((lo, hi if hi >= lo else lo))

    # Check for direct fresher declarations in description
    if re.search(r"\b(?:freshers?\s+(?:can\s+apply|are\s+welcome|eligible|welcome)|welcome\s+freshers|no\s+(?:prior\s+)?experience(?:\s+required|\s+needed)?|zero\s+experience|0\s*(?:years?|yrs?)\s+experience|fresh\s+graduates?|campus\s+(?:hiring|recruitment|placement))\b", text):
        claims.append((0.0, 0.0))

    for clause in re.split(r"[\n.!?;]+", text):
        if not re.search(r"\b(?:experience|exp)\b", clause):
            continue
        has_requirement_context = bool(re.search(
            r"\b(?:required|requirement|requires?|must|need(?:ed)?|minimum|at\s+least|"
            r"should\s+have|preferred|desired|candidate|you\s+have)\b",
            clause,
        ))
        # "2 years of professional experience" is itself a clear claim.
        has_experience_duration = bool(
            re.search(
                r"\b\d+(?:\.\d+)?\s*(?:\+|[-–—]|to)?\s*\d*(?:\.\d+)?\s*"
                r"(?:months?|mos?|years?|yrs?)\b[^,]{0,45}\b(?:experience|exp)\b",
                clause,
            )
            or re.search(
                r"\b(?:experience|exp)\b[^.!?]{0,40}"
                r"\b\d+(?:\.\d+)?\s*(?:\+|[-–—]|to)?\s*\d*(?:\.\d+)?\s*"
                r"(?:months?|mos?|years?|yrs?)\b",
                clause,
            )
        )
        if not has_requirement_context and not has_experience_duration:
            continue
        for match in re.finditer(
            r"\b\d+(?:\.\d+)?\s*(?:\+|[-–—]|to)?\s*\d*(?:\.\d+)?\s*"
            r"(?:months?|mos?|years?|yrs?)\b",
            clause,
        ):
            lo, hi = parse_experience_range(match.group(0))
            if lo is not None and hi is not None:
                claims.append((lo, hi))
    return claims


def is_fresher_job(
    title: Optional[str],
    experience_range: Optional[str],
    description: Optional[str] = None,
    job_level: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Strictly verifies if a job listing is suitable for a fresher.
    Rejects experienced, mid-level, lead, senior, and managerial roles.
    """
    title_str = _text(title).lower()
    desc_str = _text(description).lower()
    level_str = _text(job_level).lower()

    # 1. Check metadata job level
    if re.search(r"\bintern(?:ship)?\b", title_str):
        return False, "Internship role excluded"
    for forbidden_level in FORBIDDEN_JOB_LEVELS:
        if forbidden_level in level_str:
            return False, f"Forbidden job level: {level_str}"

    # 2. Check title for senior/lead/manager keywords
    title_words = re.sub(r"[^\w\s]", " ", title_str)
    for keyword in FORBIDDEN_TITLE_KEYWORDS:
        clean_kw = re.sub(r"[^\w\s]", " ", keyword).strip()
        # Avoid single-character or numeric-only matching that could match numbers like 5 in '8.5 LPA' or '5S'
        if not clean_kw or clean_kw.isdigit() or len(clean_kw) < 2:
            continue
        pattern = r"\b" + re.escape(clean_kw) + r"\b"
        if re.search(pattern, title_words):
            return False, f"Title contains senior/non-fresher keyword: '{keyword}'"

    # Explicit senior experience requirements in title (e.g. '2+ years', '3+ yrs', '5+ yoe', '5 years exp')
    senior_exp_in_title = re.search(r"\b([2-9]|\d{2})\s*\+?\s*(?:years?|yrs?|yoe)\b", title_str)
    if senior_exp_in_title:
        return False, f"Title specifies senior experience: '{senior_exp_in_title.group(0)}'"

    # 3. Check for Roman numerals or level numbers indicating experienced roles
    # e.g. "SW Engineer II", "SDE 2", "Developer III", "Analyst L2", "Level 2"
    level_pattern = r"\b(ii|iii|iv|v|l2|l3|l4|level\s*[2-9])\b|\b(?:sde|swe|engineer|developer|analyst|consultant|executive|specialist)\s*[-_ ]*[2-9]\b"
    level_match = re.search(level_pattern, title_str)
    if level_match:
        return False, f"Title indicates Level 2+ / experienced role: '{level_match.group(0)}'"

    # 4. Check board metadata and explicit experience requirements in JD.
    exp_text = str(experience_range or "")
    min_exp, max_exp = parse_experience_range(exp_text)
    if exp_text.lower().startswith(("unverified", "unspecified")):
        return False, "Experience is unspecified/unverified; cannot guarantee fresher limit"

    has_fresher_title = any(w in title_str for w in [
        "fresher", "junior", "trainee", "entry level", "entry-level",
        "associate", "graduate", "l1", "level 1"
    ])
    has_fresher_desc = any(w in desc_str for w in [
        "fresher", "0-1 year", "0 to 1 year", "0-1 yr", "0 to 1 yr",
        "fresh graduate", "entry level", "trainee", "campus hiring",
        "campus recruitment", "no prior experience", "zero experience",
        "freshers can apply", "freshers welcome", "freshers eligible",
        "2024 passout", "2025 passout", "2026 passout",
        "2024 batch", "2025 batch", "2026 batch", "recent graduate"
    ])

    # Strict fresher ceiling: 1.0 year max across all roles and titles
    allowed_max = MAX_ALLOWED_EXPERIENCE_YEARS

    # Strict 0-1 experience check on structured metadata:
    # Candidates with 0 experience must be eligible (min_exp <= 0.5 yr)
    if min_exp is not None:
        if min_exp > 0.5:
            return False, f"Minimum experience required ({min_exp:g} yrs) exceeds fresher limit (0.5 yr / candidates with 0 experience must be eligible)"
        if max_exp is not None and max_exp > allowed_max:
            return False, f"Maximum experience ({max_exp:g} yrs) exceeds {allowed_max:g} yr limit"

    # Strict 0-1 experience check on description claims:
    description_claims = _experience_claims_from_description(desc_str)
    for claim_min, claim_max in description_claims:
        if claim_min > 0.5:
            return False, f"Description requires at least {claim_min:g} years of experience"
        if claim_max > allowed_max:
            return False, f"Description allows/requires experience up to {claim_max:g} years"

    # Positive proof check:
    # A job is only verified as a fresher role if it has:
    #   A) Verified 0-1 yr metadata (min_exp <= 0.5 and max_exp <= 1.0)
    #   B) OR an explicit fresher/junior title (has_fresher_title)
    #   C) OR an explicit fresher declaration in the description (has_fresher_desc)
    has_verified_exp = (min_exp is not None and min_exp <= 0.5 and (max_exp is None or max_exp <= allowed_max))

    if min_exp is None and not description_claims:
        if not (has_fresher_title or has_fresher_desc):
            return False, "Experience requirement missing; cannot verify fresher limit" 

    if re.search(r"\b(?:internship|project)\s+(?:experience|letter|certificate)\b|\bproject\s+experience\b|\btraining\s+(?:experience|certificate|letter)\b|\b(?:training|project)\s+completion\s+(?:letter|certificate)\b", desc_str):
        if re.search(r"\b(?:must\s+have|mandatory|required|submit|provide)\b[^.!?]{0,50}\b(?:internship|project|training)\s+(?:certificate|letter)\b", desc_str):
            return False, "Mandatory internship/project/training certificate requirement"

    # 6. Reject any unverified generic role that lacks positive proof
    if not (has_fresher_title or has_verified_exp or has_fresher_desc):
        return False, f"Generic role without explicit fresher/junior designation or verified 0-1 experience: '{title}'"

    return True, "Verified fresher role"


def is_legitimate_company(
    company_name: Optional[str],
    title: Optional[str] = None,
    description: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Ensures the employer is not a blacklisted training institute,
    deceptive coaching center, or unpaid scam scheme.
    """
    company_str = _text(company_name).lower()
    title_str = _text(title).lower()
    desc_str = _text(description).lower()

    if not company_str:
        return False, "Empty company name"

    # 1. Check company name against blacklist
    for blacklisted in COMPANY_BLACKLIST:
        if blacklisted in company_str:
            return False, f"Company '{company_name}' matched blacklist: '{blacklisted}'"

    # 2. Check for training/coaching markers in title (using word boundaries to avoid false positives like 'statutory')
    for m in ["trainer", "faculty", "instructor", "teaching faculty", "tutor"]:
        if re.search(r"\b" + re.escape(m) + r"\b", title_str):
            return False, f"Title indicates training staff rather than tech role: '{title}'" 

    # 3. Check description for scam patterns (fees, unpaid, deposit)
    for pattern in FORBIDDEN_DESCRIPTION_PATTERNS:
        if pattern in desc_str:
            return False, f"Description contains scam pattern: '{pattern}'"

    return True, "Legitimate employer"


def categorize_role(title: Optional[str], description: Optional[str] = None) -> Optional[str]:
    """
    Maps the job title/description to a recognized fresher track.
    Returns None only if the job is completely unrelated to tech/analytics/business tracks.
    """
    title_clean = _text(title).lower()
    text = f"{title_clean} {_text(description)}".lower()

    # 1. Marketing Analyst
    if "marketing" in title_clean and "analyst" in title_clean:
        return "Marketing Analyst"

    # 2. HR Analyst
    if any(k in title_clean for k in ["human resources analyst", "hr analyst", "people analyst"]):
        return "HR Analyst"

    # 3. Data Analyst / BI
    if any(k in title_clean for k in ["data analytic", "data analyst", "power bi", "tableau", "sql analyst", "business intelligence analyst", "bi analyst"]) or \
       ("data" in title_clean and "analyst" in title_clean):
        return "Data Analyst"

    # 4. Business Analyst
    if any(k in title_clean for k in ["business analytic", "business analyst", "product analyst", "operations analyst"]) or \
       ("business" in title_clean and "analyst" in title_clean):
        return "Business Analyst"

    # 5. Full Stack Developer
    if any(k in title_clean for k in ["full stack", "fullstack", "mern", "mean stack"]):
        return "Full Stack Developer"

    # 6. Web / Frontend Developer
    if any(k in title_clean for k in ["web dev", "frontend", "front-end", "front end", "react", "node", "ui developer", "python web", "web developer", "angular"]):
        return "Web Developer"

    # 7. QA / Testing / Quality Engineer
    if any(k in title_clean for k in ["qa", "quality engineer", "test engineer", "software tester", "software test", "automation tester", "manual tester", "quality analyst", "testing", "sdet"]):
        return "QA / Test Engineer"

    # 8. Software Engineering / Development
    if any(k in title_clean for k in [
        "software engineer", "software developer", "associate software engineer", "junior software engineer",
        "associate engineer", "trainee software engineer", "software developer trainee", "graduate engineer trainee",
        "get", "sde", "programmer", "application developer", "python developer", "java developer", "backend developer",
        "c++ developer", "cloud engineer", "devops engineer", "system engineer", "junior developer", "developer",
        "sw development", "sw engineer", "sw developer", "sw development engineer"
    ]):
        if any(w in text for w in ["web", "frontend", "react", "html", "ui"]):
            return "Web Developer"
        elif any(w in text for w in ["full stack", "fullstack", "mern"]):
            return "Full Stack Developer"
        return "Software Engineer"

    # 9. Generic Analyst
    if "analyst" in title_clean and not any(x in title_clean for x in ["financial analyst", "equity analyst", "market research analyst", "credit analyst"]):
        return "Analyst"

    # 10. Trainee / Graduate / Associate roles
    if any(w in title_clean for w in ["graduate trainee", "management trainee", "tech trainee", "trainee", "associate"]):
        if any(w in text for w in ["data", "analytics"]):
            return "Data Analyst"
        elif any(w in text for w in ["business", "operations"]):
            return "Business Analyst"
        elif any(w in text for w in ["qa", "test", "quality"]):
            return "QA / Test Engineer"
        elif any(w in text for w in ["web", "frontend", "react"]):
            return "Web Developer"
        elif any(w in text for w in ["software", "developer", "engineer", "programming", "java", "python"]):
            return "Software Engineer"
        return "Graduate Trainee"

    # Secondary check on full description if title is generic
    if any(w in title_clean for w in ["fresher", "trainee", "associate", "graduate", "engineer", "developer", "consultant"]):
        if "data analytic" in text or "data analyst" in text:
            return "Data Analyst"
        elif "business analyst" in text:
            return "Business Analyst"
        elif any(k in text for k in ["full stack", "fullstack", "mern"]):
            return "Full Stack Developer"
        elif any(k in text for k in ["web dev", "frontend", "react"]):
            return "Web Developer"
        elif any(k in text for k in ["software engineer", "software developer", "coding", "python", "java"]):
            return "Software Engineer"
        elif any(k in text for k in ["qa", "testing", "quality"]):
            return "QA / Test Engineer"
        elif "marketing" in text and "analyst" in text:
            return "Marketing Analyst"
        elif "hr" in text and "analyst" in text:
            return "HR Analyst"
        elif "analyst" in text:
            return "Analyst"

    return None


def enrich_experience_and_salary(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Guarantees that EVERY job has a concrete experience and salary value.
    Extracts from description text if missing from card metadata,
    and applies standard fresher market benchmarks when undisclosed.
    """
    title = _text(job.get("title"))
    desc = _text(job.get("description"))
    cat = job.get("tech_category") or categorize_role(title, desc)
    
    # -------------------------------------------------------------
    # 1. Experience Enrichment (Never Leave Blank)
    # -------------------------------------------------------------
    original_exp = _text(job.get("experience_range"))
    missing_exp = original_exp.lower() in {
        "", "not specified", "unspecified", "unverified", "none", "nan",
    }
    exp = original_exp
    experience_source = "board" if original_exp and not missing_exp else "unknown"

    if missing_exp:
        exp = ""
        # Try extracting from description text
        # e.g. "0-1 years", "1 to 2 yrs", "0 - 2 yrs"
        exp_match = re.search(r"\b([0-2])\s*(?:-|to)\s*([1-2])\s*(?:years?|yrs?)\b", desc, re.I)
        claims = _experience_claims_from_description(desc) if desc else []
        has_negative_claim = any(
            claim_min > MAX_ALLOWED_EXPERIENCE_YEARS or claim_max > MAX_ALLOWED_EXPERIENCE_YEARS
            for claim_min, claim_max in claims
        )

        if has_negative_claim:
            # The JD explicitly asks for more than the fresher ceiling.
            exp = "Not specified"
            experience_source = "job_description_conflict"
        elif exp_match:
            exp = f"{exp_match.group(1)}-{exp_match.group(2)} Yrs"
            experience_source = "job_description"
        elif claims:
            # Positive fresher/0-1 evidence in the JD.
            exp = "0-1 Yrs (JD Verified)"
            experience_source = "job_description"
        elif any(w in (title + " " + desc).lower() for w in ["fresher", "fresh graduate", "campus hiring", "2024 passout", "2025 passout", "2026 passout"]):
            exp = "0-1 Yrs (Fresher)"
            experience_source = "job_description"
        elif any(w in title.lower() for w in [
            "junior", "trainee", "associate software engineer", "associate engineer",
            "associate developer", "associate analyst", "entry level", "entry-level",
            "intern", "sde 1", "sde-1", "sde1", "graduate engineer trainee", "get",
            "graduate trainee", "associate qa", "junior qa", "associate test engineer",
            "sw development engineer 1", "sw development engineer i", "assistant",
        ]):
            exp = "0-1 Yrs (Junior / Trainee)"
            experience_source = "title_inference"
        else:
            # LinkedIn's own entry-level filter (f_E=2) is platform-level evidence.
            # If a substantial JD exists and does not contradict it, infer 0-1
            # instead of rejecting the job for a missing search-card field.
            job_level = _text(job.get("job_level")).lower()
            has_role_context = bool(re.search(
                r"\b(?:responsibilit(?:y|ies)|requirements?|qualifications?|skills?|"
                r"what you(?:'|’)ll do|who you are|about the role|job description|duties)\b",
                desc,
                re.I,
            ))
            if job_level == "entry_level" and len(desc) >= 200 and has_role_context:
                exp = "0-1 Yrs (Entry-Level Inferred)"
                experience_source = "platform_entry_level"
            else:
                exp = "Not specified"
                experience_source = "unknown"

    job["experience_range"] = str(exp).strip()
    job["experience_source"] = experience_source
    job["verification_status"] = (
        "verified" if experience_source in {"board", "job_description"}
        else "inferred" if experience_source in {"title_inference", "platform_entry_level"}
        else "unverified"
    )
    full_text = f"{title}\n{desc}"
    passouts = re.findall(r"\b(202[456]|2[456])\s*(?:passouts?|batch|graduates?)\b", full_text, re.I)
    job["eligible_passout_years"] = ", ".join(sorted({f"20{p[-2:]}" for p in passouts}))
    skill_block = re.search(r"(?:skills|required skills|technical skills|technology stack|tech stack|requirements)\s*[:\-]?\s*(.{0,600})", desc, re.I | re.S)
    job["required_skills"] = re.sub(r"\s+", " ", skill_block.group(1)).strip()[:500] if skill_block else ""
    req_exp = re.search(r"\b(?:minimum|required|at least)\s+(?:\d+\s*)?(?:months?|years?)\s+(?:of\s+)?experience\b", desc, re.I)
    no_exp = re.search(r"\b(?:no|zero)\s+(?:prior\s+)?experience\s+(?:required|needed)\b|\bfresher\b", desc, re.I)
    job["prior_experience_required"] = "Yes" if req_exp else ("No" if no_exp else "Unspecified")
    # Keep enough of the original description for company/role interview
    # research and student-facing context. A 1,200-character cap removed
    # qualifications and experience criteria that often appear near the end.
    job["job_requirement"] = desc[:16000]

    # -------------------------------------------------------------
    # 2. Salary Enrichment (Never Leave Blank)
    # -------------------------------------------------------------
    min_sal = job.get("min_amount")
    max_sal = job.get("max_amount")
    
    # Both bounds must be finite positive numbers; pandas commonly supplies NaN.
    try:
        min_value = float(min_sal)
        max_value = float(max_sal)
        has_valid_salary = (
            math.isfinite(min_value)
            and math.isfinite(max_value)
            and min_value > 0
            and max_value > 0
        )
    except Exception:
        has_valid_salary = False

    if not has_valid_salary:
        # Try extracting LPA from description: "3.5 - 5 LPA", "4 to 6 Lacs", etc.
        lpa_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lacs?|lakhs?)", desc, re.I)
        if lpa_match:
            min_sal = int(float(lpa_match.group(1)) * 100000)
            max_sal = int(float(lpa_match.group(2)) * 100000)
            job["salary_source_type"] = "Extracted from JD"
            has_valid_salary = True
        else:
            # Monthly stipend / salary: "₹25,000 - ₹35,000 / month"
            month_match = re.search(r"(?:₹|rs\.?)\s*(\d{2,3}(?:,\d{3})*)\s*(?:-|to)\s*(?:₹|rs\.?)?\s*(\d{2,3}(?:,\d{3})*)\s*(?:per\s*month|/month|pm)\b", desc, re.I)
            if month_match:
                m1 = int(month_match.group(1).replace(",", "")) * 12
                m2 = int(month_match.group(2).replace(",", "")) * 12
                min_sal = m1
                max_sal = m2
                job["salary_source_type"] = "Extracted from Monthly JD"
                has_valid_salary = True
            else:
                min_sal = "Not Mentioned"
                max_sal = "Not Mentioned"
                job["salary_source_type"] = "Not Mentioned"

    job["min_amount"] = min_sal
    job["max_amount"] = max_sal
    job["salary_display"] = (
        f"₹{int(float(min_sal)):,} - ₹{int(float(max_sal)):,}"
        if has_valid_salary
        else "Not Mentioned"
    )

    return job


def evaluate_job(job: Dict[str, Any], max_hours: Optional[int] = None) -> Dict[str, Any]:
    """
    Runs the complete evaluation suite on a single job record.
    Returns the enriched job record with validation flags.
    Enforces that all fields (title, company, location, category, experience, apply URL)
    are strictly valid and complete.
    """
    title = job.get("title")
    company = job.get("company")
    location = job.get("location")
    date_posted = job.get("date_posted")
    desc = job.get("description")
    level = job.get("job_level")

    # Run tests
    job = enrich_experience_and_salary(job)
    experience = job.get("experience_range")

    effective_max_hours = max_hours or job.get("hours_old") or MAX_HOURS_OLD
    within_freshness, date_reason = is_within_hours(date_posted, effective_max_hours)
    job["date_freshness_verified"] = within_freshness
    job["date_freshness_reason"] = date_reason

    fresher_ok, exp_reason = is_fresher_job(title, experience, desc, level)
    legit_ok, legit_reason = is_legitimate_company(company, title, desc)
    loc_ok, loc_reason = is_valid_location(location, search_city=job.get("search_city"))

    # Resolve apply URL
    apply_url = resolve_apply_url(job)
    job["apply_url"] = apply_url
    has_valid_url = bool(apply_url and apply_url.startswith("http"))

    # Strictly disallow "Not specified" / "Unspecified" experience
    has_valid_exp = bool(experience and str(experience).strip().lower() not in {"not specified", "unspecified", "none", "nan"})

    category = categorize_role(title, desc)
    has_valid_cat = bool(category)
    if not category:
        category = "Unmatched Tech Role"

    job["tech_category"] = category

    is_valid = within_freshness and fresher_ok and legit_ok and loc_ok and has_valid_cat and has_valid_url and has_valid_exp
    rejection_reasons = []

    if not within_freshness:
        rejection_reasons.append(date_reason)
    if not fresher_ok:
        rejection_reasons.append(exp_reason)
    if not legit_ok:
        rejection_reasons.append(legit_reason)
    if not loc_ok:
        rejection_reasons.append(loc_reason)
    if not has_valid_cat:
        rejection_reasons.append("Role does not match a requested category (Business/Data/Marketing/HR Analyst, Analyst, Full Stack Developer, Web Developer)")
    if not has_valid_url:
        rejection_reasons.append("Missing valid HTTP/HTTPS apply URL")
    if not has_valid_exp:
        rejection_reasons.append("Experience could not be verified as strict 0-1 years")

    # Compute a quality confidence score (0-100)
    score = 60
    if job.get("min_amount") not in {None, "", "Not Mentioned"}:
        score += 15
    if has_valid_url:
        score += 10
    if job.get("emails"):
        score += 15
    score = min(score, 100)

    job["is_valid_fresher_job"] = is_valid
    job["rejection_reason"] = " | ".join(rejection_reasons) if rejection_reasons else "None"
    job["quality_score"] = score if is_valid else 0

    return job
