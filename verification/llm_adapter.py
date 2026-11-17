"""
Fail-Closed LLM Verification Adapter
====================================
Integrates multi-provider LLM models (Groq, OpenRouter) with strict JSON output schemas,
dual-mode handling (individual fresher job vs collective drive), and fail-closed security.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core.models import (
    Opportunity,
    OpportunityType,
    LLMStatus,
)

logger = logging.getLogger("verification.llm_adapter")


class LLMDecisionSchema(BaseModel):
    """Pydantic schema enforcing structured LLM verification response."""
    opportunity_type: OpportunityType = OpportunityType.INDIVIDUAL_FRESHER_JOB
    is_fresher_eligible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    eligible_batches: List[str] = Field(default_factory=list)
    experience_assessment: str
    has_experience_contradiction: bool
    supporting_evidence: List[str] = Field(default_factory=list)
    contradictory_evidence: List[str] = Field(default_factory=list)
    decision: str  # 'ACCEPT', 'REJECT', 'MANUAL_REVIEW'
    rejection_reasons: List[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You are a Technical Recruitment Auditor and Verification Gatekeeper for Indian Fresher Hiring.

Your mission is to audit job listings and campus recruitment drives to verify entry-level eligibility for 2025, 2026, and 2027 graduates.

CRITICAL RULES:
1. Differentiate INDIVIDUAL_FRESHER_JOB from OFF_CAMPUS_DRIVE.
   - An off-campus drive (e.g. TCS NQT, Cognizant GenC, Wipro Elite, generic graduate recruitment) must NOT be rejected merely because it covers multiple roles or lacks a specific tech stack title.
2. Contradiction Detection:
   - If a listing invites 2025/2026/2027 batches but demands 2+ years of commercial/professional experience, REJECT immediately.
3. Missing Experience Information:
   - Missing experience info in a genuine campus/graduate recruitment drive must NOT trigger automatic rejection.
   - However, a senior role with missing experience must NOT be approved.
4. Software & Technology Discipline Rule:
   - The role MUST be a software engineering, software development, data, IT, cloud, DevOps, QA/testing, systems, or technical engineering role.
   - Non-technical roles (such as BPO, Process Executive, Operations Executive, Customer Support, KYC, Audio/Content Evaluation, Accounting, Finance/FP&A, Sales, HR, Culinary/Hotel staff, Manufacturing, Pharma production) MUST BE REJECTED (decision: 'REJECT', rejection_reasons: ['Non-technical role / Not software engineering']). Never approve a non-tech role even if freshers are eligible.
5. Fail-closed: Never hallucinate facts not present in the excerpt.
6. Strict JSON response only matching this schema:
{
  "opportunity_type": "INDIVIDUAL_FRESHER_JOB" or "OFF_CAMPUS_DRIVE",
  "is_fresher_eligible": true or false,
  "confidence": 0.0 to 1.0,
  "eligible_batches": ["2025", "2026", "2027"],
  "experience_assessment": "0-1 years" or "2+ years required",
  "has_experience_contradiction": true or false,
  "supporting_evidence": ["Evidence 1"],
  "contradictory_evidence": ["Conflict 1"],
  "decision": "ACCEPT" or "REJECT" or "MANUAL_REVIEW",
  "rejection_reasons": []
}
"""

USER_TEMPLATE = """AUDIT THIS OPPORTUNITY:
Title: {title}
Company: {company}
Opportunity Type: {opp_type}
Eligible Batches: {batches}
Description Excerpt:
{description}

Analyze and return strictly JSON.
"""


class LLMVerifierAdapter:
    """Fail-closed LLM verification client supporting Groq and OpenRouter key rotation."""

    def __init__(self):
        from dotenv import load_dotenv
        # Ensure environment variables are loaded
        load_dotenv(os.path.join(os.getcwd(), ".env"))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fresher_job_scraper", ".env"))

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

    def has_active_keys(self) -> bool:
        return bool(self.groq_keys or self.openrouter_keys)

    def verify_opportunity(self, opp: Opportunity) -> Tuple[LLMStatus, bool, Optional[str], List[str]]:
        """Executes LLM verification.
        
        Returns:
            (llm_status, is_approved, reasoning, rejection_reasons)
        """
        if not self.has_active_keys():
            logger.warning("[llm_adapter] No active LLM credentials configured. Failing closed.")
            return LLMStatus.UNAVAILABLE, False, "No active LLM credentials configured; fail-closed rule enforced", ["LLM verifier unavailable"]

        prompt = USER_TEMPLATE.format(
            title=opp.title,
            company=opp.company,
            opp_type=opp.opportunity_type.value,
            batches=", ".join(str(b) for b in opp.eligible_graduation_batches) if opp.eligible_graduation_batches else "Not specified",
            description=opp.description[:1500] if opp.description else "(No description available)",
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # 1. Try Groq keys
        groq_models = [os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), "openai/gpt-oss-20b"]
        for key in self.groq_keys:
            for g_model in groq_models:
                try:
                    from openai import OpenAI
                    client = OpenAI(
                        api_key=key,
                        base_url="https://api.groq.com/openai/v1",
                        timeout=15,
                    )
                    resp = client.chat.completions.create(
                        model=g_model,
                        messages=messages,
                        temperature=0.0,
                        max_tokens=1500,
                        response_format={"type": "json_object"},
                    )
                    raw_content = resp.choices[0].message.content or ""
                    parsed = self._parse_json(raw_content)
                    if parsed:
                        return self._process_schema(parsed)
                except Exception as exc:
                    logger.warning("[llm_adapter] Groq key request with model %s failed: %s", g_model, exc)

        # 2. Try OpenRouter keys
        for key in self.openrouter_keys:
            try:
                from openai import OpenAI
                client = OpenAI(
                    api_key=key,
                    base_url="https://openrouter.ai/api/v1",
                    timeout=15,
                    default_headers={
                        "HTTP-Referer": "https://github.com/placement-prep/fresher-job-scraper",
                        "X-Title": "Fresher Job Intelligence Coverage Lab",
                    },
                )
                resp = client.chat.completions.create(
                    model=os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free"),
                    messages=messages,
                    temperature=0.0,
                    max_tokens=1500,
                )
                raw_content = resp.choices[0].message.content or ""
                parsed = self._parse_json(raw_content)
                if parsed:
                    return self._process_schema(parsed)
            except Exception as exc:
                logger.warning("[llm_adapter] OpenRouter key request failed: %s", exc)

        return LLMStatus.UNAVAILABLE, False, "All configured LLM providers failed", ["LLM execution error"]

    def _process_schema(self, data: Dict[str, Any]) -> Tuple[LLMStatus, bool, Optional[str], List[str]]:
        try:
            decision_obj = LLMDecisionSchema(**data)
            if decision_obj.decision == "ACCEPT" and decision_obj.is_fresher_eligible:
                reasoning = f"Approved by LLM (confidence: {decision_obj.confidence:.2f}): {'; '.join(decision_obj.supporting_evidence)}"
                return LLMStatus.APPROVED, True, reasoning, []
            elif decision_obj.decision == "MANUAL_REVIEW":
                return LLMStatus.MANUAL_REVIEW, False, "Flagged for manual review by LLM", ["Manual review required by LLM"]
            else:
                reasons = decision_obj.rejection_reasons or decision_obj.contradictory_evidence or ["Rejected by LLM guardrail"]
                return LLMStatus.REJECTED, False, f"Rejected by LLM: {'; '.join(reasons)}", reasons
        except Exception as exc:
            logger.warning("[llm_adapter] Failed to validate LLM response against schema: %s", exc)
            return LLMStatus.REJECTED, False, "Invalid response schema from LLM", ["Schema validation failed"]

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
