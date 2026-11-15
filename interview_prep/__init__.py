"""Interview Prep Document Generator.

Builds a subtle, student-friendly A4 interview-preparation PDF for every
verified fresher job that reached the Google Sheet. This package is fully
self-contained: it does NOT import from ``company_search`` so the legacy
agentic dossier pipeline can be retired later without breaking this one.

Modules
-------
- ``sources``      : public-web question scraping (no API keys / logins)
- ``curator``      : LLM curation of the question pack (fails closed)
- ``pdf_renderer`` : minimal A4 PDF renderer (reportlab)
- ``drive``        : placeholders for a future Google Drive upload
- ``runner``       : orchestration, caching, fail-closed per-job execution
"""

from interview_prep.runner import run_interview_docs

__all__ = ["run_interview_docs"]
