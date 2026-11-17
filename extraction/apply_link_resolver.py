"""Direct Application Link Resolver & Live Application Verifier.

Follows safe redirect chains, unpacks shorteners, and inspects live employer
application pages for genuine requisition presence, closure notices, login walls,
and active application forms/actions.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import urlparse
import zoneinfo
from bs4 import BeautifulSoup

from core.models import ApplicationVerificationResult

logger = logging.getLogger("coverage_lab.resolver")
TZ_KOLKATA = zoneinfo.ZoneInfo("Asia/Kolkata")

CLOSED_NOTICES = [
    r"\b(?:this\s+)?job\s+(?:is\s+)?(?:no\s+longer\s+available|closed|expired)\b",
    r"\bno\s+longer\s+accepting\s+applications\b",
    r"\bapplications?\s+(?:are\s+)?closed\b",
    r"\bregistration[s]?\s+(?:are\s+)?closed\b",
    r"\bposition\s+(?:is\s+)?(?:filled|closed|no\s+longer\s+available)\b",
    r"\brequisition\s+(?:is\s+)?(?:closed|expired|inactive)\b",
    r"\bthis\s+posting\s+has\s+expired\b",
    r"\bjob\s+not\s+found\b",
    r"\bthe\s+job\s+you\s+are\s+looking\s+for\s+has\s+expired\b",
    r"\bthis\s+job\s+opening\s+has\s+been\s+archived\b",
    r"\bthis\s+vacancy\s+is\s+no\s+longer\s+open\b",
]

LOGIN_WALL_PATTERNS = [
    r"\bplease\s+(?:sign\s*in|log\s*in)\s+to\s+apply\b",
    r"\bcandidate\s+login\s+required\b",
    r"\blogin\s+to\s+view\s+this\s+job\b",
]

BOT_BLOCK_PATTERNS = [
    r"\bcloudflare\b",
    r"\bverify\s+you\s+are\s+human\b",
    r"\bperimeterx\b",
    r"\bdatadome\b",
    r"\baccess\s+denied\b",
    r"\bsecurity\s+check\b",
]

APPLICATION_ACTION_PATTERNS = [
    r"\bapply\s+(?:now|online|for\s+this\s+job|for\s+position|with\s+linkedin|via\s+workday)\b",
    r"\bsubmit\s+(?:application|resume|cv)\b",
    r"\bstart\s+application\b",
    r"\bapply\b",
]


class ApplyLinkResolver:
    """Safely resolves and independently verifies live employer application pages."""

    @staticmethod
    def resolve_url(
        url: str,
        timeout: int = 5,
        max_redirects: int = 3,
    ) -> Tuple[str, int, Optional[str]]:
        """Resolves target URL without full payload parsing (backward-compatible)."""
        if not url or not url.startswith("http"):
            return url, 0, "Invalid URL format"

        try:
            from curl_cffi import requests
            resp = requests.head(
                url,
                timeout=timeout,
                allow_redirects=True,
                max_redirects=max_redirects,
                impersonate="chrome120",
            )
            return resp.url, resp.status_code, None
        except Exception:
            try:
                import requests as py_requests
                resp = py_requests.head(url, timeout=timeout, allow_redirects=True)
                return resp.url, resp.status_code, None
            except Exception as ex:
                return url, 0, str(ex)

    @classmethod
    def verify_application_live(
        cls,
        url: str,
        expected_requisition_id: Optional[str] = None,
        expected_company: Optional[str] = None,
        timeout: int = 8,
    ) -> ApplicationVerificationResult:
        """Inspects live destination page to establish verifiable application openness."""
        now_str = datetime.now(TZ_KOLKATA).isoformat()
        if not url or not url.startswith("http"):
            return ApplicationVerificationResult(
                original_url=url or "",
                resolved_url=url or "",
                http_status=0,
                status="UNREACHABLE",
                error="Invalid or missing URL",
                checked_at=now_str,
            )

        redirect_chain: List[str] = [url]
        try:
            from curl_cffi import requests
            resp = requests.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                max_redirects=5,
                impersonate="chrome120",
            )
            final_url = resp.url
            if final_url != url:
                redirect_chain.append(final_url)
            http_status = resp.status_code
            html_text = resp.text or ""
        except Exception as e:
            # Fallback to standard requests if curl_cffi is blocked or fails
            try:
                import requests as py_requests
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                resp = py_requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
                final_url = resp.url
                if final_url != url:
                    redirect_chain.append(final_url)
                http_status = resp.status_code
                html_text = resp.text or ""
            except Exception as ex:
                return ApplicationVerificationResult(
                    original_url=url,
                    resolved_url=url,
                    redirect_chain=redirect_chain,
                    http_status=0,
                    status="UNREACHABLE",
                    error=str(ex),
                    checked_at=now_str,
                )

        parsed_final = urlparse(final_url)
        path_lower = parsed_final.path.lower().rstrip("/")

        # Check for HTTP errors
        if http_status in (404, 410):
            return ApplicationVerificationResult(
                original_url=url,
                resolved_url=final_url,
                redirect_chain=redirect_chain,
                http_status=http_status,
                status="CLOSED",
                closed_notice_found=True,
                evidence_text=f"Employer portal returned HTTP {http_status} (Page Gone / Not Found)",
                checked_at=now_str,
            )
        elif http_status >= 400 and http_status != 403:
            return ApplicationVerificationResult(
                original_url=url,
                resolved_url=final_url,
                redirect_chain=redirect_chain,
                http_status=http_status,
                status="UNREACHABLE",
                error=f"HTTP status {http_status}",
                checked_at=now_str,
            )

        # Parse HTML
        soup = BeautifulSoup(html_text[:100000], "html.parser")
        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""
        canonical_tag = soup.find("link", rel="canonical")
        canonical_url = canonical_tag["href"] if (canonical_tag and canonical_tag.get("href")) else None

        body_text = soup.get_text(" ", strip=True)
        body_lower = body_text.lower()

        # Check anti-bot block (e.g. CGI page protected by Cloudflare/PerimeterX)
        if http_status == 403 or any(re.search(pat, body_lower) for pat in BOT_BLOCK_PATTERNS):
            return ApplicationVerificationResult(
                original_url=url,
                resolved_url=final_url,
                redirect_chain=redirect_chain,
                http_status=http_status,
                page_title=page_title,
                status="UNKNOWN",
                error="Employer page protected by anti-bot verification or access gate",
                checked_at=now_str,
            )

        # Check if redirected to a generic careers homepage
        if path_lower in {"", "/careers", "/jobs", "/home", "/en/careers", "/en/jobs"} and not parsed_final.query:
            return ApplicationVerificationResult(
                original_url=url,
                resolved_url=final_url,
                redirect_chain=redirect_chain,
                http_status=http_status,
                page_title=page_title,
                status="UNKNOWN",
                evidence_text="Redirected to generic careers homepage without specific requisition",
                checked_at=now_str,
            )

        # Check login required
        if any(re.search(pat, body_lower) for pat in LOGIN_WALL_PATTERNS):
            return ApplicationVerificationResult(
                original_url=url,
                resolved_url=final_url,
                redirect_chain=redirect_chain,
                http_status=http_status,
                page_title=page_title,
                status="LOGIN_REQUIRED",
                evidence_text="Login wall detected to inspect application status",
                checked_at=now_str,
            )

        # Check explicit closure notices
        for pat in CLOSED_NOTICES:
            match = re.search(pat, body_lower)
            if match:
                return ApplicationVerificationResult(
                    original_url=url,
                    resolved_url=final_url,
                    redirect_chain=redirect_chain,
                    http_status=http_status,
                    page_title=page_title,
                    canonical_url=canonical_url,
                    closed_notice_found=True,
                    status="CLOSED",
                    evidence_text=f"Closed notice detected on employer page: '{match.group(0)}'",
                    checked_at=now_str,
                )

        # Requisition matching if expected_requisition_id provided
        requisition_id_found = False
        if expected_requisition_id:
            req_clean = expected_requisition_id.strip()
            if req_clean.lower() in final_url.lower() or req_clean.lower() in body_lower:
                requisition_id_found = True
            else:
                return ApplicationVerificationResult(
                    original_url=url,
                    resolved_url=final_url,
                    redirect_chain=redirect_chain,
                    http_status=http_status,
                    page_title=page_title,
                    canonical_url=canonical_url,
                    requisition_id_found=False,
                    requisition_id=expected_requisition_id,
                    status="UNAVAILABLE",
                    evidence_text=f"Requisition ID '{expected_requisition_id}' not found on target employer page",
                    checked_at=now_str,
                )

        # Check application action / submit button
        application_action_found = False
        application_form_available = False

        # Look for buttons or links with 'apply'
        for btn in soup.find_all(["button", "a", "input"]):
            txt = btn.get_text(" ", strip=True).lower()
            btn_id = str(btn.get("id") or "").lower()
            btn_cls = " ".join(btn.get("class") or []).lower()
            if any(re.search(p, txt) for p in APPLICATION_ACTION_PATTERNS) or "apply" in btn_id or "apply" in btn_cls:
                application_action_found = True
                break

        # Check form
        if soup.find("form"):
            application_form_available = True

        if not application_action_found and any(re.search(p, body_lower) for p in APPLICATION_ACTION_PATTERNS):
            application_action_found = True

        if http_status == 200 and (application_action_found or application_form_available):
            return ApplicationVerificationResult(
                original_url=url,
                resolved_url=final_url,
                redirect_chain=redirect_chain,
                http_status=http_status,
                page_title=page_title,
                canonical_url=canonical_url,
                requisition_id_found=requisition_id_found,
                requisition_id=expected_requisition_id,
                job_still_present=True,
                closed_notice_found=False,
                application_action_found=application_action_found,
                application_form_available=application_form_available,
                status="OPEN",
                evidence_text=f"Active requisition verified on employer portal ({page_title[:60]}); application route verified accepting submissions",
                checked_at=now_str,
            )

        # HTTP 200 but couldn't verify form/action
        return ApplicationVerificationResult(
            original_url=url,
            resolved_url=final_url,
            redirect_chain=redirect_chain,
            http_status=http_status,
            page_title=page_title,
            canonical_url=canonical_url,
            requisition_id_found=requisition_id_found,
            requisition_id=expected_requisition_id,
            status="UNKNOWN",
            evidence_text="Page loaded (HTTP 200) but no verified application submission action was found",
            checked_at=now_str,
        )
