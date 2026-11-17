"""Direct Application Link Resolver.

Follows safe redirect chains, unpacks shorteners (bit.ly, tinyurl),
and extracts canonical employer career URLs.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple
from urllib.parse import urlparse
from curl_cffi import requests

logger = logging.getLogger("coverage_lab.resolver")


class ApplyLinkResolver:
    """Safely resolves intermediate aggregator redirect URLs into final canonical targets."""

    @staticmethod
    def resolve_url(
        url: str,
        timeout: int = 5,
        max_redirects: int = 3,
    ) -> Tuple[str, int, Optional[str]]:
        """Resolves target URL without executing external browser downloads.
        
        Returns:
            (resolved_url, http_status, error_message)
        """
        if not url or not url.startswith("http"):
            return url, 0, "Invalid URL format"

        try:
            resp = requests.head(
                url,
                timeout=timeout,
                allow_redirects=True,
                max_redirects=max_redirects,
                impersonate="chrome120",
            )
            return resp.url, resp.status_code, None
        except Exception as e:
            # Fallback to GET with stream to avoid full payload download
            try:
                resp = requests.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    max_redirects=max_redirects,
                    impersonate="chrome120",
                    stream=True,
                )
                return resp.url, resp.status_code, None
            except Exception as ex:
                return url, 0, str(ex)
