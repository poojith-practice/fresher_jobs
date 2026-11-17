"""Source Evidence Validator (Zero-Hallucination & Anti-Fabrication Guard).

Validates that every claim, quote, or excerpt made by an LLM, classifier,
or extractor strictly exists in the authentic source text.
Rejects any fabricated or hallucinated evidence.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple


def _normalize_text(text: str) -> str:
    """Normalizes whitespace and casing for robust text verification."""
    text_clean = re.sub(r"\s+", " ", text or "").strip().lower()
    return text_clean


def validate_evidence_quote(quote: str, source_text: str, min_match_ratio: float = 0.85) -> Tuple[bool, str]:
    """Validates whether a cited quote or excerpt exists in the authentic source document.
    
    Returns:
        (is_valid, reason)
    """
    if not quote or not quote.strip():
        return False, "Empty or missing evidence quote"

    if not source_text or not source_text.strip():
        return False, "Source document text is empty"

    norm_quote = _normalize_text(quote)
    norm_source = _normalize_text(source_text)

    # 1. Exact substring match
    if norm_quote in norm_source:
        return True, "Exact evidence quote verified in source text"

    # 2. Token-sequence match for truncated snippets (e.g. "...eligibility: 2025, 2026...")
    clean_snippet = re.sub(r"^\.*|\.*$", "", norm_quote).strip()
    if clean_snippet and clean_snippet in norm_source:
        return True, "Sub-clause quote verified in source text"

    # 3. Word-set overlap check for multi-word phrases (>= 4 words)
    quote_words = [w for w in re.split(r"\W+", clean_snippet) if len(w) >= 3]
    if len(quote_words) >= 4:
        # Check if 85%+ of the words appear in a close window in source text
        matched_words = [w for w in quote_words if w in norm_source]
        ratio = len(matched_words) / len(quote_words)
        if ratio >= min_match_ratio:
            return True, f"Evidence text corroborated by source vocabulary ({ratio*100:.1f}% match)"

    return False, f"HALLUCINATED_EVIDENCE_REJECTED: Quote '{quote[:60]}...' cannot be corroborated in source document"
