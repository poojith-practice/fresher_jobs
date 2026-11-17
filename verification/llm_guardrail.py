"""LLM Guardrail & Verification Gate for Coverage Lab.

Strict, fail-closed LLM evaluator distinguishing individual fresher jobs
from off-campus recruitment drives, extracting verifiable evidence without hallucination.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from models.opportunity import Opportunity, OpportunityType

logger = logging.getLogger("coverage_lab.llm_guardrail")


class LLMVerificationSchema(BaseModel):
    """Strict Pydantic output schema expected from LLM."""
    opportunity_type: OpportunityType
    is_fresher_eligible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    eligible_batches: List[str] = Field(default_factory=list)
    excluded_batches: List[str] = Field(default_factory=list)
    experience_assessment: str
    has_experience_contradiction: bool
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    decision: str  # 'ACCEPT', 'REJECT', 'MANUAL_REVIEW'
    rejection_reasons: List[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You are an expert Technical Recruitment Auditor and Verification Gatekeeper for Fresher Hiring in India.

Your mission is to strictly audit job listings and off-campus recruitment drives to verify genuine entry-level (fresher) eligibility for 2025, 2026, and 2027 graduates.

CRITICAL RULES:
1. Differentiate INDIVIDUAL_FRESHER_JOB from OFF_CAMPUS_DRIVE.
   - An off-campus drive (e.g. TCS NQT, Cognizant GenC, Wipro Elite, generic graduate hiring campaigns) must NOT be rejected merely because it covers multiple roles or lacks a specific tech stack title.
2. Contradiction Detection:
   - If a listing mentions 2026/2027 batch but explicitly demands 2+ years of professional commercial experience, REJECT immediately.
3. Missing Experience Information:
   - Missing experience info in a genuine campus/graduate recruitment drive must NOT trigger automatic rejection.
   - However, a senior role with missing experience must NOT be approved.
4. Fail-closed: Never hallucinate facts not present in the excerpt.

Output MUST be strictly valid JSON matching this schema:
{
  "opportunity_type": "INDIVIDUAL_FRESHER_JOB" or "OFF_CAMPUS_DRIVE",
  "is_fresher_eligible": true or false,
  "confidence": 0.0 to 1.0,
  "eligible_batches": ["2025", "2026", "2027"],
  "excluded_batches": [],
  "experience_assessment": "0-1 years" or "2+ years required",
  "has_experience_contradiction": true or false,
  "supporting_evidence": ["Evidence point 1"],
  "contradictory_evidence": ["Conflict point 1"],
  "decision": "ACCEPT" or "REJECT" or "MANUAL_REVIEW",
  "rejection_reasons": []
}
"""

USER_TEMPLATE = """AUDIT THIS OPPORTUNITY:
Title: {title}
Company: {company}
Opportunity Type: {opp_type}
Stated Batches: {batches}
Stated Experience: {experience}
Description Excerpt:
{description}

Analyze and return strictly JSON.
"""


class LLMGuardrail:
    """Isolated LLM evaluator using multi-key rotation."""

    def __init__(self):
        self.groq_keys = [
            os.getenv("GROQ_API_KEY_1"),
            os.getenv("GROQ_API_KEY_2"),
            os.getenv("GROQ_API_KEY_3"),
            os.getenv("GROQ_API_KEY"),
        ]
        self.groq_keys = [k for k in self.groq_keys if k and k.startswith("gsk_")]

        self.openrouter_keys = [
            os.getenv("OPENROUTER_API_KEY_1"),
            os.getenv("OPENROUTER_API_KEY_2"),
            os.getenv("OPENROUTER_API_KEY_3"),
            os.getenv("OPENROUTER_API_KEY"),
        ]
        self.openrouter_keys = [
            k.lstrip("#").strip()
            for k in self.openrouter_keys
            if k and k.lstrip("#").strip().startswith("sk-or-v1-")
        ]

    def has_keys(self) -> bool:
        return bool(self.groq_keys or self.openrouter_keys)

    def verify_opportunity(self, opp: Opportunity) -> Optional[LLMVerificationSchema]:
        """Invokes LLM with fail-closed guarantee."""
        if not self.has_keys():
            logger.warning("[llm_guardrail] No active LLM keys configured; skipping LLM layer")
            return None

        prompt = USER_TEMPLATE.format(
            title=opp.title,
            company=opp.company,
            opp_type=opp.opportunity_type.value,
            batches=", ".join(opp.eligible_batches) if opp.eligible_batches else "Not specified",
            experience=opp.experience_required or "Not specified",
            description=opp.description[:1500] if opp.description else "(No description provided)",
        )

        from langchain_core.messages import SystemMessage, HumanMessage
        from langchain_openai import ChatOpenAI

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        # 1. Try Groq keys
        for key in self.groq_keys:
            try:
                client = ChatOpenAI(
                    api_key=key,
                    base_url="https://api.groq.com/openai/v1",
                    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                    temperature=0.0,
                    max_tokens=600,
                )
                resp = client.invoke(messages)
                parsed = self._parse_json(str(resp.content or ""))
                if parsed:
                    return LLMVerificationSchema(**parsed)
            except Exception as exc:
                logger.warning("[llm_guardrail] Groq key failed: %s", exc)

        # 2. Try OpenRouter keys
        for key in self.openrouter_keys:
            try:
                client = ChatOpenAI(
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    model=os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free"),
                    temperature=0.0,
                    max_tokens=600,
                    default_headers={
                        "HTTP-Referer": "https://github.com/placement-prep/fresher-job-scraper",
                        "X-Title": "Fresher Job Intelligence Scraper",
                    },
                )
                resp = client.invoke(messages)
                parsed = self._parse_json(str(resp.content or ""))
                if parsed:
                    return LLMVerificationSchema(**parsed)
            except Exception as exc:
                logger.warning("[llm_guardrail] OpenRouter key failed: %s", exc)

        return None

    def _parse_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        text = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = m.group(0) if m else text
        try:
            return json.loads(candidate)
        except Exception:
            try:
                import json_repair
                return json_repair.loads(candidate)
            except Exception:
                return None
