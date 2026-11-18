"""Config package combining legacy root configuration with coverage lab settings."""
import os
import sys

# Re-export settings from config.settings
from config.settings import (
    LAB_DIR,
    DATA_DIR,
    RAW_DATA_DIR,
    NORMALIZED_DATA_DIR,
    VERIFIED_DATA_DIR,
    REJECTED_DATA_DIR,
    MANUAL_REVIEW_DATA_DIR,
    REPORTS_DIR,
    LOGS_DIR,
    EXPERIMENTAL_DB_PATH,
    PERMITTED_BATCHES,
    CURRENT_TARGET_BATCHES,
    MAX_FRESHER_EXPERIENCE_YEARS,
    TIMEZONE,
    TARGET_ROLE_CATEGORIES,
    REQUEST_HEADERS,
)
from config.sources import SOURCES_CONFIG

# Also import and re-export legacy config attributes for backwards compatibility
MAX_HOURS_OLD = 6
TARGET_SITES = ["naukri", "indeed", "linkedin", "monsterindia"]
UNSUPPORTED_SITES = []
DEFAULT_LOCATIONS = ["Mumbai", "Hyderabad"]
INDEED_COUNTRY = "india"
RESULTS_PER_QUERY = 25
QUERY_DELAY_SECONDS = 1.0
QUERY_CONCURRENCY = 3
JOBSPY_PROXIES = []
MAX_ALLOWED_EXPERIENCE_YEARS = 1.0

ROLE_QUERIES = {
    "Business Analyst": ["business analyst", "junior business analyst", "business analyst fresher"],
    "Data Analyst": ["data analyst", "junior data analyst", "data analyst fresher"],
    "Marketing Analyst": ["marketing analyst", "junior marketing analyst", "marketing analyst fresher"],
    "HR Analyst": ["HR analyst", "junior HR analyst", "HR analyst fresher"],
    "Analyst": ["analyst", "junior analyst", "trainee analyst", "analyst fresher"],
    "Full Stack Developer": ["full stack developer", "junior full stack developer", "full stack developer fresher", "associate software engineer", "software engineer trainee"],
    "Web Developer": ["web developer", "junior web developer", "web developer fresher", "frontend developer fresher", "react developer fresher"],
}

FORBIDDEN_TITLE_KEYWORDS = [
    "senior", "sr", "lead", "leader", "principal", "architect",
    "manager", "head", "director", "vp", "vice president", "specialist",
    "chief", "staff engineer", "expert", "consultant 2", "mid-level",
    "mid level", "level 2", "level 3", "2+", "3+", "4+", "5+", "6+", "7+",
    "8+", "9+", "10+", "years experience"
]

FORBIDDEN_JOB_LEVELS = ["mid_senior", "director", "executive", "associate_director"]

COMPANY_BLACKLIST = [
    "internshala", "unacademy", "byjus", "byju's", "whitehat jr", "vedantu",
    "toppr", "upgrad", "upgrade", "simplilearn", "edureka", "intellipaat",
    "great learning", "scaler", "newton school", "alma better", "almabetter",
    "masai school", "coding ninjas", "geekster", "acciojob", "crio.do",
    "qspiders", "jspiders", "pyspiders", "naresh i technologies", "naresh it",
    "durga software", "durga soft", "besant technologies", "apponix",
    "ethnus", "kelly technologies", "sla consultants", "croma campus",
    "sevenmentor", "fita academy", "cetpa", "actalent training",
    "training institute", "coaching institute", "it academy",
    "learning solutions", "skills academy", "training center",
    "training centre", "finishing school", "placement guarantee",
    "job guarantee", "hire and train", "train and hire",
    "edtech", "edutech"
]

FORBIDDEN_DESCRIPTION_PATTERNS = [
    "registration fee", "training fee", "security deposit",
    "pay after placement", "unpaid internship", "unpaid intern",
    "no stipend", "commission only", "earn from home data entry",
    "sms sending job", "part time form filling", "captcha typing"
]
