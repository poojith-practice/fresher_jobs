"""Source Metadata and Health Metrics Models."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class SourceHealth(BaseModel):
    source_id: str
    name: str
    url: str
    status_code: int = 0
    is_healthy: bool = True
    anti_bot_detected: bool = False
    last_checked_at: Optional[str] = None
    total_discovered: int = 0
    total_verified: int = 0
    total_rejected: int = 0
    total_manual_review: int = 0
    error_message: Optional[str] = None
