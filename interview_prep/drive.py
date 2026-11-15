"""Placeholders for a future Google Drive upload of interview-prep PDFs.

The live sheet has an "Interview QnA doc" column (index 12 / column M). A
Google service account cannot upload into a personal Drive without a Shared
Drive or Workspace delegation, so the actual upload is deferred. These
placeholders define the integration surface so the runner, the CLI, and the
sheet sync can already reference a stable API.

To enable later:
  1. Create a dedicated service account with Drive access.
  2. Set GDRIVE_SERVICE_ACCOUNT_FILE to its JSON key path.
  3. Set GDRIVE_FOLDER_ID to the target Drive folder ID.
  4. Implement the marked TODO in upload_pdf(); nothing else needs to change.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("interview_prep.drive")

GDRIVE_SERVICE_ACCOUNT_ENV = "GDRIVE_SERVICE_ACCOUNT_FILE"
GDRIVE_FOLDER_ID_ENV = "GDRIVE_FOLDER_ID"


def drive_configured() -> bool:
    """True when both placeholder env vars are present."""
    folder = os.getenv(GDRIVE_FOLDER_ID_ENV, "").strip()
    key = os.getenv(GDRIVE_SERVICE_ACCOUNT_ENV, "").strip()
    return bool(folder and key and not folder.startswith("YOUR_"))


def upload_pdf(pdf_path: Path) -> Dict[str, Any]:
    """Upload a finished PDF to Drive (NOT implemented yet - placeholder).

    Returns a status dict that the runner stores in ``meta.json``:

    - ``not_configured``: placeholder env vars absent (normal today).
    - ``error``: env vars present but upload failed.
    """
    if not drive_configured():
        return {"drive_file_id": None, "drive_url": None, "drive_status": "not_configured"}

    # TODO: implement with googleapiclient.discovery.build("drive", "v3", ...)
    # using the service account at os.getenv(GDRIVE_SERVICE_ACCOUNT_ENV),
    # uploading into folder os.getenv(GDRIVE_FOLDER_ID_ENV), and returning
    # the webViewLink. Keep this signature unchanged.
    logger.warning("Drive upload requested but not implemented yet; skipping.")
    return {"drive_file_id": None, "drive_url": None, "drive_status": "error"}


def sheet_doc_cell(drive_url: Optional[str], local_pdf: Optional[Path] = None) -> str:
    """Value for the sheet's 'Interview QnA doc' column (column M).

    Until Drive upload lands, this yields an empty string so the merge logic
    in google_sheets_sync keeps whatever is already in the sheet.
    """
    if drive_url:
        return str(drive_url)
    return ""
