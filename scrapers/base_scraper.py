"""Base Scraper Class for Coverage Lab.

Implements polite network fetching with browser TLS impersonation,
session pooling, rate-limiting, and standard error handling.
"""
from __future__ import annotations

import abc
import logging
import time
from typing import Any, Dict, List, Optional
from curl_cffi import requests as cffi_requests
from config.settings import REQUEST_HEADERS

logger = logging.getLogger("coverage_lab.scraper")


class BaseScraper(abc.ABC):
    """Abstract base scraper defining common interface and network behaviors."""

    def __init__(
        self,
        source_id: str,
        name: str,
        base_url: str,
        rate_limit_seconds: float = 2.0,
    ):
        self.source_id = source_id
        self.name = name
        self.base_url = base_url
        self.rate_limit_seconds = rate_limit_seconds
        self.last_request_time = 0.0

    def _wait_rate_limit(self) -> None:
        """Enforces polite inter-request delay."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self.last_request_time = time.time()

    def fetch_html(self, url: str, timeout: int = 15) -> Optional[str]:
        """Fetches page content with Chrome 124 TLS impersonation."""
        self._wait_rate_limit()
        logger.debug("[%s] Fetching %s...", self.source_id, url)
        try:
            resp = cffi_requests.get(
                url,
                headers=REQUEST_HEADERS,
                impersonate="chrome124",
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning("[%s] HTTP %d for %s", self.source_id, resp.status_code, url)
            return None
        except Exception as exc:
            logger.warning("[%s] Fetch error on %s: %s", self.source_id, url, exc)
            return None

    def fetch_json(self, url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
        """Fetches and parses a JSON endpoint."""
        self._wait_rate_limit()
        logger.debug("[%s] Fetching JSON %s...", self.source_id, url)
        try:
            resp = cffi_requests.get(
                url,
                headers=REQUEST_HEADERS,
                impersonate="chrome124",
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("[%s] HTTP %d for %s", self.source_id, resp.status_code, url)
            return None
        except Exception as exc:
            logger.warning("[%s] JSON fetch error on %s: %s", self.source_id, url, exc)
            return None

    @abc.abstractmethod
    def scrape(self, max_items: int = 20) -> List[Dict[str, Any]]:
        """Collects raw opportunity listings from this source."""
        raise NotImplementedError
