"""
Isolated HTTP Client with Host Throttling & Fault Tolerance
===========================================================
Provides robust, rate-limited HTTP retrieval with per-host backoff,
TLS impersonation fallback, and structured outcome tracking.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Dict, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

logger = logging.getLogger("core.http_client")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


class HTTPOutcome:
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    BLOCKED = "BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    PARSER_FAILURE = "PARSER_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    UNSUPPORTED = "UNSUPPORTED"


class SafeHTTPClient:
    """Rate-limited HTTP client with host pacing and failure tracking."""

    def __init__(self, min_delay_per_host: float = 1.0, timeout: int = 20):
        self.min_delay_per_host = min_delay_per_host
        self.timeout = timeout
        self._last_request_time: Dict[str, float] = {}
        self.host_outcomes: Dict[str, str] = {}

    def _throttle(self, url: str) -> None:
        """Enforces minimum interval between consecutive requests to the same host."""
        host = urllib.parse.urlparse(url).netloc.lower()
        now = time.time()
        last = self._last_request_time.get(host, 0.0)
        elapsed = now - last
        if elapsed < self.min_delay_per_host:
            sleep_needed = self.min_delay_per_host - elapsed
            time.sleep(sleep_needed)
        self._last_request_time[host] = time.time()

    def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> Tuple[Optional[str], int, str]:
        """
        Executes a GET request returning (content, status_code, outcome).
        Never throws unhandled exceptions; safely records outcome state.
        """
        self._throttle(url)
        req_headers = {**DEFAULT_HEADERS, **(headers or {})}
        req_timeout = timeout or self.timeout
        host = urllib.parse.urlparse(url).netloc.lower()

        for attempt in range(max_retries + 1):
            try:
                if HAS_CURL_CFFI:
                    resp = curl_requests.get(
                        url,
                        headers=req_headers,
                        timeout=req_timeout,
                        impersonate="chrome120",
                        allow_redirects=True,
                    )
                    status = resp.status_code
                    if status == 200:
                        self.host_outcomes[host] = HTTPOutcome.SUCCESS
                        return resp.text, 200, HTTPOutcome.SUCCESS
                    elif status == 429:
                        self.host_outcomes[host] = HTTPOutcome.RATE_LIMITED
                        logger.warning("[%s] HTTP 429 Rate limited on %s", host, url)
                        return None, 429, HTTPOutcome.RATE_LIMITED
                    elif status in (401, 403):
                        self.host_outcomes[host] = HTTPOutcome.BLOCKED
                        logger.warning("[%s] HTTP %d Blocked/Gated on %s", host, status, url)
                        return None, status, HTTPOutcome.BLOCKED
                    elif 500 <= status < 600 and attempt < max_retries:
                        time.sleep(2.0 * (attempt + 1))
                        continue
                    else:
                        self.host_outcomes[host] = HTTPOutcome.NETWORK_FAILURE
                        return None, status, HTTPOutcome.NETWORK_FAILURE

                else:
                    # Fallback standard urllib
                    req = Request(url, headers=req_headers)
                    with urlopen(req, timeout=req_timeout) as resp:
                        status = resp.status
                        body = resp.read().decode("utf-8", errors="replace")
                        self.host_outcomes[host] = HTTPOutcome.SUCCESS
                        return body, status, HTTPOutcome.SUCCESS

            except HTTPError as http_err:
                status = http_err.code
                if status == 429:
                    self.host_outcomes[host] = HTTPOutcome.RATE_LIMITED
                    return None, 429, HTTPOutcome.RATE_LIMITED
                elif status in (401, 403):
                    self.host_outcomes[host] = HTTPOutcome.BLOCKED
                    return None, status, HTTPOutcome.BLOCKED
                elif 500 <= status < 600 and attempt < max_retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                else:
                    self.host_outcomes[host] = HTTPOutcome.NETWORK_FAILURE
                    return None, status, HTTPOutcome.NETWORK_FAILURE

            except Exception as exc:
                logger.debug("[%s] Request failed on attempt %d: %s", host, attempt + 1, exc)
                if attempt < max_retries:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    self.host_outcomes[host] = HTTPOutcome.NETWORK_FAILURE
                    return None, 0, HTTPOutcome.NETWORK_FAILURE

    def post(
        self,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[Optional[str], int, str]:
        """Performs throttled POST request."""
        self._throttle(url)
        req_headers = dict(DEFAULT_HEADERS)
        if headers:
            req_headers.update(headers)
        req_timeout = timeout or self.timeout
        host = urllib.parse.urlparse(url).netloc.lower()

        try:
            if HAS_CURL_CFFI:
                resp = curl_requests.post(
                    url,
                    data=data,
                    headers=req_headers,
                    timeout=req_timeout,
                    impersonate="chrome120",
                    allow_redirects=True,
                )
                status = resp.status_code
                if status == 200:
                    self.host_outcomes[host] = HTTPOutcome.SUCCESS
                    return resp.text, 200, HTTPOutcome.SUCCESS
                return None, status, HTTPOutcome.NETWORK_FAILURE
            else:
                post_data = urllib.parse.urlencode(data).encode("utf-8") if data else None
                req = Request(url, data=post_data, headers=req_headers)
                with urlopen(req, timeout=req_timeout) as resp:
                    status = resp.status
                    body = resp.read().decode("utf-8", errors="replace")
                    self.host_outcomes[host] = HTTPOutcome.SUCCESS
                    return body, status, HTTPOutcome.SUCCESS
        except Exception as exc:
            logger.debug("[%s] POST request failed: %s", host, exc)
            return None, 0, HTTPOutcome.NETWORK_FAILURE


# Default singleton instance
http_client = SafeHTTPClient()
