"""Experimental Lab Configuration & Settings.

Strictly isolated to fresher_job_scraper_coverage_lab/
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base lab directory
LAB_DIR = Path(__file__).resolve().parent.parent

# Load local lab .env if present
load_dotenv(LAB_DIR / ".env")

# Isolated Data Directories
DATA_DIR = LAB_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
NORMALIZED_DATA_DIR = DATA_DIR / "normalized"
VERIFIED_DATA_DIR = DATA_DIR / "verified"
REJECTED_DATA_DIR = DATA_DIR / "rejected"
MANUAL_REVIEW_DATA_DIR = DATA_DIR / "manual_review"
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DATA_DIR = REPORTS_DIR
LOGS_DIR = LAB_DIR / "logs"

# Ensure all subdirectories exist
for d in [RAW_DATA_DIR, NORMALIZED_DATA_DIR, VERIFIED_DATA_DIR, REJECTED_DATA_DIR, MANUAL_REVIEW_DATA_DIR, REPORTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Isolated Experimental SQLite DB
EXPERIMENTAL_DB_PATH = DATA_DIR / "experimental_history.db"

# Recruitment Policies
PERMITTED_BATCHES = ["2024", "2025", "2026", "2027", "2028"]
CURRENT_TARGET_BATCHES = ["2025", "2026", "2027"]
MAX_FRESHER_EXPERIENCE_YEARS = 1.0
TIMEZONE = "Asia/Kolkata"

# Default Target Role Categories for Individual Jobs
TARGET_ROLE_CATEGORIES = [
    "Software Engineer",
    "Full Stack Developer",
    "Python Developer",
    "Java Developer",
    "Backend Developer",
    "Frontend Developer",
    "Web Developer",
    "Data Analyst",
    "Business Analyst",
    "Analyst",
    "Marketing Analyst",
    "HR Analyst",
    "Data Scientist",
    "Machine Learning Engineer",
    "Graduate Engineer Trainee",
    "Associate Software Engineer",
]

# Standard HTTP Headers
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
REQUEST_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
