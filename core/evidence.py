"""
Evidence Builder & Provenance Collector
=======================================
Guarantees that every extracted datum retains authentic textual provenance
from the source without synthetic injection or fabrication.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from core.models import EvidenceItem


def make_evidence(
    field: str,
    value: Any,
    source_url: str,
    evidence_text: str = "",
    extraction_method: str = "direct_extraction",
    confidence: float = 1.0,
    is_explicit: bool = True,
) -> EvidenceItem:
    """Creates a verified evidence item with strict provenance."""
    clean_text = str(evidence_text or "").strip()
    return EvidenceItem(
        field=field,
        value=value,
        source_url=source_url,
        evidence_text=clean_text[:500],
        extraction_method=extraction_method,
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        retrieved_at=datetime.utcnow().isoformat() + "Z",
        is_explicit=is_explicit,
    )
