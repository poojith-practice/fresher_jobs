"""Google Drive upload integration for interview-prep PDFs.

Supports both:
1. Google Apps Script Web App (Recommended — executes as user, bypasses service account storage quota limits)
2. Service Account Google Drive API v3 (for Google Workspace Shared Drives)

Sets public reader permissions and returns the shareable webViewLink for the Google Sheet's 'Interview QnA doc' column.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("interview_prep.drive")

GDRIVE_UPLOAD_URL_ENV = "GDRIVE_UPLOAD_URL"
GDRIVE_SERVICE_ACCOUNT_ENV = "GDRIVE_SERVICE_ACCOUNT_FILE"
GDRIVE_FOLDER_ID_ENV = "GDRIVE_FOLDER_ID"
DEFAULT_FOLDER_ID = "10VvfeWYKf0fTVuihc8nWYSpeipVZwSiz"


def get_drive_credentials_path() -> Optional[str]:
    """Finds existing service account JSON credentials path."""
    path = os.getenv(GDRIVE_SERVICE_ACCOUNT_ENV) or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "credentials.json"
    if not os.path.isabs(path):
        candidate1 = Path(__file__).resolve().parent.parent / path
        if candidate1.exists():
            return str(candidate1)
        candidate2 = Path.cwd() / path
        if candidate2.exists():
            return str(candidate2)
    elif os.path.exists(path):
        return path
    return None


def drive_configured() -> bool:
    """True when either Web App upload URL or Drive credentials + folder are available."""
    upload_url = os.getenv(GDRIVE_UPLOAD_URL_ENV, "").strip()
    if upload_url.startswith("http"):
        return True
    folder = os.getenv(GDRIVE_FOLDER_ID_ENV, "").strip()
    creds_path = get_drive_credentials_path()
    return bool(folder and creds_path and not folder.startswith("YOUR_"))


def upload_pdf(pdf_path: Path) -> Dict[str, Any]:
    """Uploads a finished PDF to Google Drive and sets public reader permissions.

    Returns a status dict:
    - drive_file_id: The Google Drive file ID
    - drive_url: The shareable webViewLink
    - drive_status: 'uploaded', 'not_configured', or 'error'
    """
    if not drive_configured():
        logger.warning("Google Drive upload not configured (missing GDRIVE_UPLOAD_URL or GDRIVE_FOLDER_ID).")
        return {"drive_file_id": None, "drive_url": None, "drive_status": "not_configured"}

    folder_id = os.getenv(GDRIVE_FOLDER_ID_ENV, DEFAULT_FOLDER_ID).strip()
    upload_url = os.getenv(GDRIVE_UPLOAD_URL_ENV, "").strip()

    # 1. Primary & Recommended: Google Apps Script Web App (runs as user, zero quota issues)
    if upload_url.startswith("http"):
        import requests
        with open(pdf_path, "rb") as f:
            b64_content = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "folderId": folder_id,
            "fileName": pdf_path.name,
            "mimeType": "application/pdf",
            "base64": b64_content,
        }

        for attempt in range(1, 4):
            try:
                logger.info("Uploading %s to Google Drive via Apps Script Web App (attempt %d/3)...", pdf_path.name, attempt)
                resp = requests.post(upload_url, json=payload, timeout=90)
                if resp.status_code == 200:
                    data = resp.json()
                    file_id = data.get("drive_file_id")
                    drive_url = data.get("drive_url")
                    if file_id and drive_url:
                        logger.info("Successfully uploaded %s to Google Drive: %s", pdf_path.name, drive_url)
                        return {
                            "drive_file_id": file_id,
                            "drive_url": drive_url,
                            "drive_status": "uploaded",
                        }
                logger.warning("Apps Script attempt %d returned HTTP %d: %s", attempt, resp.status_code, resp.text[:200])
            except Exception as exc:
                logger.warning("Apps Script upload attempt %d failed: %s", attempt, exc)

    # 2. Fallback: Service Account Google Drive API v3 (for Shared Drives)
    creds_path = get_drive_credentials_path()
    if creds_path and folder_id:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            creds = service_account.Credentials.from_service_account_file(
                creds_path,
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            service = build("drive", "v3", credentials=creds)

            file_metadata = {
                "name": pdf_path.name,
                "parents": [folder_id],
            }
            media = MediaFileUpload(str(pdf_path), mimetype="application/pdf", resumable=True)

            logger.info("Uploading %s via Service Account to Google Drive folder %s...", pdf_path.name, folder_id)
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id, webViewLink, webContentLink",
                supportsAllDrives=True,
            ).execute()

            file_id = file.get("id")
            drive_url = file.get("webViewLink")

            try:
                service.permissions().create(
                    fileId=file_id,
                    body={"type": "anyone", "role": "reader"},
                    supportsAllDrives=True,
                ).execute()
            except Exception as perm_err:
                logger.warning("Could not set public permission on %s: %s", file_id, perm_err)

            logger.info("Successfully uploaded %s to Google Drive: %s", pdf_path.name, drive_url)
            return {
                "drive_file_id": file_id,
                "drive_url": drive_url,
                "drive_status": "uploaded",
            }
        except Exception as exc:
            logger.error("Service Account Drive upload failed for %s: %s", pdf_path, exc)

    return {"drive_file_id": None, "drive_url": None, "drive_status": "error"}


def sheet_doc_cell(drive_url: Optional[str], local_pdf: Optional[Path] = None) -> str:
    """Value for the sheet's 'Interview QnA doc' column (column M)."""
    if drive_url:
        return str(drive_url)
    return ""
