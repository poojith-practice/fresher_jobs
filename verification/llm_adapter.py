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

Your mission is to audit job listings and campus recruitment drives to verify entry-level eligibility for recent engineering graduates.

CRITICAL RULES:
1. Differentiate INDIVIDUAL_FRESHER_JOB from OFF_CAMPUS_DRIVE.
   - An off-campus drive (e.g. TCS NQT, Cognizant GenC, Wipro Elite, generic graduate recruitment) must NOT be rejected merely because it covers multiple roles or lacks a specific tech stack title.
2. Contradiction Detection:
   - If a listing invites university graduates but demands 1+ years of non-internship professional experience or multi-year commercial experience, REJECT immediately.
3. Missing Experience Information:
   - If experience is NOT stated in the source text, do NOT assume or invent 0 years. Record status as 'NOT_SPECIFIED' and decision as 'MANUAL_REVIEW'.
4. Batch Eligibility:
   - Do NOT assume or invent eligible batches. Only report batches that are explicitly stated in the source text.
5. Software & Technology Discipline Rule:
   - The role MUST be a software engineering, software development, data, IT, cloud, DevOps, QA/testing, systems, or technical engineering role.
   - Non-technical roles (such as BPO, Process Executive, Operations Executive, Customer Support, KYC, Audio/Content Evaluation, Accounting, Finance/FP&A, Sales, HR, Culinary/Hotel staff, Manufacturing, Pharma production) MUST BE REJECTED (decision: 'REJECT', rejection_reasons: ['Non-technical role / Not software engineering']). Never approve a non-tech role even if freshers are eligible.
6. Zero-Hallucination & Evidence Quotes:
   - Every claim must cite an exact excerpt from the provided text. Never fabricate quotes.
7. Strict JSON response only matching this schema:
{
  "opportunity_type": "INDIVIDUAL_FRESHER_JOB" or "OFF_CAMPUS_DRIVE",
  "is_fresher_eligible": true or false,
  "confidence": 0.0 to 1.0,
  "eligible_batches": [],
  "experience_assessment": "FRESHER_ELIGIBLE" or "COMMERCIAL_EXPERIENCE_REQUIRED" or "NOT_SPECIFIED",
  "experience_quote": "exact quote from text or empty",
  "batch_quote": "exact quote from text or empty",
  "has_experience_contradiction": true or false,
  "supporting_evidence": ["Exact excerpt 1"],
  "contradictory_evidence": ["Exact conflict 1"],
  "decision": "ACCEPT" or "REJECT" or "MANUAL_REVIEW",
  "rejection_reasons": []
}
"""

USER_TEMPLATE = """AUDIT THIS OPPORTUNITY:
Title: {title}
Company: {company}
Requisition ID: {requisition_id}
Application URL: {apply_url}
Live Application Status: {application_status}
Application Evidence: {application_evidence}
Opportunity Type: {opp_type}
Candidate Batches Stated: {batches}
Description Excerpt:
{description}

Analyze and return strictly JSON without markdown wrappers.
"""


class LLMVerifierAdapter:
    """Fail-closed LLM verification client supporting Groq and OpenRouter key rotation."""

    def __init__(self):
        from dotenv import load_dotenv
        # Explicit lab environment configuration only (no crawling into parent/production paths)
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)

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
            requisition_id=opp.opportunity_id or "Not specified",
            apply_url=opp.apply_url or opp.source_detail_url or "Not specified",
            application_status=opp.application_status.value if opp.application_status else "UNKNOWN",
            application_evidence=opp.application_status_evidence or "None",
            opp_type=opp.opportunity_type.value,
            batches=", ".join(str(b) for b in opp.eligible_graduation_batches) if opp.eligible_graduation_batches else "Not specified",
            description=opp.description[:2000] if opp.description else "(No description available)",
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        source_text = f"{opp.title} {opp.company} {opp.description or ''}"

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
                        return self._process_schema(parsed, source_text=source_text)
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
                    return self._process_schema(parsed, source_text=source_text)
            except Exception as exc:
                logger.warning("[llm_adapter] OpenRouter key request failed: %s", exc)

        return LLMStatus.UNAVAILABLE, False, "All configured LLM providers failed", ["LLM execution error"]

    def _process_schema(self, data: Dict[str, Any], source_text: str = "") -> Tuple[LLMStatus, bool, Optional[str], List[str]]:
        try:
            from verification.evidence_validator import validate_evidence_quote
            # Anti-hallucination guard: validate supporting evidence quotes
            for quote in data.get("supporting_evidence", []):
                if quote and len(quote.strip()) > 10:
                    valid, reason = validate_evidence_quote(quote, source_text)
                    if not valid:
                        return LLMStatus.REJECTED, False, f"LLM evidence fabrication: {reason}", [reason]

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
