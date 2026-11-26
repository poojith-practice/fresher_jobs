import pytest
from llm_verifier import (
    extract_requirements_and_skills_context,
    verify_fresher_and_curate_skills,
)

def test_extract_requirements_and_skills_context():
    sample = """
    About Our Company
    We are a leading enterprise with 10,000 employees globally.
    Equal Opportunity Employer. All qualified applicants will receive consideration.

    ### Key Responsibilities
    - Build scalable backend microservices.
    - Write clean code in Python and Go.
    - Design and optimize relational databases.

    ### Qualifications and Skills
    - B.Tech or B.E. in Computer Science.
    - Strong understanding of SQL, Git, and Docker.
    - Freshers eligible (0-1 years experience).

    Benefits:
    - Health insurance, 401k, gym membership.
    """
    context = extract_requirements_and_skills_context(sample)
    assert "Build scalable backend microservices" in context
    assert "Python and Go" in context
    assert "SQL, Git, and Docker" in context
    # Boilerplate / EEO stripped
    assert "Equal Opportunity Employer" not in context


def test_verify_fresher_mock_pass():
    class MockLLMPass:
        def invoke(self, messages):
            class Resp:
                content = '{"is_fresher_eligible": true, "experience_detected": "0-1 years", "rejection_reason": null, "curated_skills": "Python, Go, SQL, Docker"}'
            return Resp()

    res = verify_fresher_and_curate_skills(
        "Responsibilities: Build apps. Skills: Python, Go, SQL, Docker. Experience: 0-1 years.",
        title="Software Engineer Trainee",
        company="TechCorp",
        llm=MockLLMPass()
    )
    assert res["is_fresher_eligible"] is True
    assert "Python, Go, SQL, Docker" in res["curated_skills"]


def test_verify_fresher_mock_fail_experienced():
    class MockLLMFail:
        def invoke(self, messages):
            class Resp:
                content = '{"is_fresher_eligible": false, "experience_detected": "3+ years", "rejection_reason": "Requires 3+ years experience in production", "curated_skills": "React, Redux"}'
            return Resp()

    res = verify_fresher_and_curate_skills(
        "Responsibilities: Frontend apps. Requirements: 3+ years experience in production. Skills: React, Redux.",
        title="Web Developer",
        company="TechCorp",
        llm=MockLLMFail()
    )
    assert res["is_fresher_eligible"] is False
    assert "3+ years" in res["rejection_reason"]


LONG_FRESHER_JD = (
    "Responsibilities: Build dashboards and reports. Requirements: Freshers welcome. "
    "0-1 years experience. Skills: SQL, Excel, Power BI, Python, data analysis."
)

LONG_SPECIALIST_JD = (
    "Requirements: Proficiency in SAP Analytics Cloud (SAC), with additional knowledge of SAP BW. "
    "Experience in developing complex dashboards and reports. Experience in financial controlling "
    "is a plus. Strong collaboration skills, with experience working in cross-functional teams."
)


def test_gate_fails_closed_without_llm(monkeypatch):
    import llm_verifier

    monkeypatch.setattr(llm_verifier, "get_llm", lambda: None)
    res = llm_verifier.verify_fresher_and_curate_skills(
        LONG_FRESHER_JD, title="Data Analyst", company="Acme"
    )
    assert res["is_fresher_eligible"] is False
    assert res["llm_verified"] is False
    assert "unavailable" in res["rejection_reason"].lower()


def test_gate_fails_closed_when_llm_raises():
    class ExplodingLLM:
        def invoke(self, messages):
            raise RuntimeError("network down")

    res = verify_fresher_and_curate_skills(
        LONG_FRESHER_JD, title="Data Analyst", company="Acme", llm=ExplodingLLM()
    )
    assert res["is_fresher_eligible"] is False
    assert res["llm_verified"] is False


def test_gate_fails_closed_on_short_description():
    res = verify_fresher_and_curate_skills(
        "Data analyst job.", title="Data Analyst", company="Acme",
        llm=object(),
    )
    assert res["is_fresher_eligible"] is False
    assert res["llm_verified"] is False


def test_gate_parses_string_false_and_missing_key():
    class StringFalseLLM:
        def invoke(self, messages):
            class Resp:
                content = '{"is_fresher_eligible": "false", "rejection_reason": "Needs SAP experience", "curated_skills": "SAP SAC"}'
            return Resp()

    res = verify_fresher_and_curate_skills(
        LONG_SPECIALIST_JD, title="Data Analyst - SAC", company="Lufthansa", llm=StringFalseLLM()
    )
    assert res["is_fresher_eligible"] is False
    assert res["llm_verified"] is True
    assert "SAP" in res["rejection_reason"]

    class MissingKeyLLM:
        def invoke(self, messages):
            class Resp:
                content = '{"curated_skills": "SQL, Excel"}'
            return Resp()

    res2 = verify_fresher_and_curate_skills(
        LONG_FRESHER_JD, title="Data Analyst", company="Acme", llm=MissingKeyLLM()
    )
    assert res2["is_fresher_eligible"] is False  # missing verdict must not default to True
    assert res2["llm_verified"] is True


def test_sheet_gate_requires_llm_approval():
    from google_sheets_sync import format_jobs_rows

    base = {
        "title": "Data Analyst",
        "company": "Acme",
        "location": "Mumbai, India",
        "tech_category": "Data Analyst",
        "date_posted": "2026-11-14",
        "experience_range": "0-1 Yrs",
        "min_amount": 300000,
        "max_amount": 450000,
        "apply_url": "https://example.com/job/1",
        "site": "linkedin",
        "skills_requirements": "SQL, Excel",
    }
    approved = dict(base, llm_verified=True, llm_eligible=True)
    rule_only = dict(base, apply_url="https://example.com/job/2")
    llm_rejected = dict(base, apply_url="https://example.com/job/3", llm_verified=True, llm_eligible=False)

    rows = format_jobs_rows([approved, rule_only, llm_rejected])
    assert len(rows) == 1
    assert rows[0][8] == "https://example.com/job/1"


def _clear_llm_env(monkeypatch):
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"GROQ_API_KEY{i}", raising=False)
        monkeypatch.delenv(f"GROQ_API_KEY_{i}", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def test_rotating_llm_key_failover(monkeypatch):
    from llm_verifier import RotatingLLM

    # Clear OpenRouter keys to test pure Groq failover
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY1", "key_fail_1")
    monkeypatch.setenv("GROQ_API_KEY2", "key_success_2")

    call_history = []

    class MockChatOpenAI:
        def __init__(self, api_key, **kwargs):
            self.api_key = api_key

        def invoke(self, messages):
            call_history.append(self.api_key)
            if self.api_key == "key_fail_1":
                raise RuntimeError("429 Rate limit exceeded: tokens per minute limit reached")
            class Resp:
                content = '{"is_fresher_eligible": true, "curated_skills": "Python, SQL"}'
            return Resp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", MockChatOpenAI)

    rotator = RotatingLLM()
    assert len(rotator.groq_keys) == 2
    res = rotator.invoke("test")
    assert "is_fresher_eligible" in res.content
    # Verified it tried key 1 first, failed on 429, then succeeded on key 2!
    assert call_history == ["key_fail_1", "key_success_2"]
    assert rotator.active_groq_idx == 0

    # Next call should directly use key 2 (since key 1 is in cooldown) without repeating key 1!
    rotator.invoke("second call")
    assert call_history == ["key_fail_1", "key_success_2", "key_success_2"]


def test_rotating_llm_openrouter_first_and_failover(monkeypatch):
    from llm_verifier import RotatingLLM

    # Set up 2 OpenRouter keys and 1 Groq key
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY1", "sk-or-v1-router_fail_1")
    monkeypatch.setenv("OPENROUTER_API_KEY2", "sk-or-v1-router_success_2")
    monkeypatch.setenv("GROQ_API_KEY1", "gsk_groq_fallback_1")

    call_history = []

    class MockChatOpenAI:
        def __init__(self, api_key, **kwargs):
            self.api_key = api_key

        def invoke(self, messages):
            call_history.append(self.api_key)
            if self.api_key == "sk-or-v1-router_fail_1":
                raise RuntimeError("429 Rate limit exceeded: free model quota reached")
            class Resp:
                content = '{"is_fresher_eligible": true, "curated_skills": "Python, SQL"}'
            return Resp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", MockChatOpenAI)

    rotator = RotatingLLM()
    assert len(rotator.openrouter_keys) == 2
    assert len(rotator.groq_keys) == 1
    res = rotator.invoke("test")
    assert "is_fresher_eligible" in res.content
    # Verified it tried OpenRouter Key 1 first, failed on 429, then succeeded on OpenRouter Key 2!
    assert call_history == ["sk-or-v1-router_fail_1", "sk-or-v1-router_success_2"]
    assert rotator.active_openrouter_idx == 0

    # Next call should directly use OpenRouter Key 2 without repeating Key 1!
    rotator.invoke("second call")
    assert call_history == ["sk-or-v1-router_fail_1", "sk-or-v1-router_success_2", "sk-or-v1-router_success_2"]


def test_rotating_llm_falls_back_to_groq_when_openrouter_exhausted(monkeypatch):
    from llm_verifier import RotatingLLM

    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY1", "sk-or-v1-router_fail_all")
    monkeypatch.setenv("GROQ_API_KEY1", "gsk_groq_success_1")

    call_history = []

    class MockChatOpenAI:
        def __init__(self, api_key, **kwargs):
            self.api_key = api_key

        def invoke(self, messages):
            call_history.append(self.api_key)
            if self.api_key == "sk-or-v1-router_fail_all":
                raise RuntimeError("429 Rate limit exceeded")
            class Resp:
                content = '{"is_fresher_eligible": true, "curated_skills": "Python, SQL"}'
            return Resp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", MockChatOpenAI)

    rotator = RotatingLLM()
    res = rotator.invoke("test")
    assert "is_fresher_eligible" in res.content
    assert call_history == ["sk-or-v1-router_fail_all", "gsk_groq_success_1"]


def test_rotating_llm_recovers_openrouter_after_cooldown(monkeypatch):
    import time
    from llm_verifier import RotatingLLM

    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY1", "sk-or-v1-router_1")
    monkeypatch.setenv("GROQ_API_KEY1", "gsk_groq_1")

    should_fail_or = {"flag": True}
    used = []

    class MockChatOpenAI:
        def __init__(self, api_key, model="", **kwargs):
            self.api_key = api_key
            self.model = model

        def invoke(self, messages):
            used.append((self.api_key, self.model))
            if self.api_key.startswith("sk-or-") and should_fail_or["flag"]:
                raise RuntimeError("429 Too Many Requests")
            class Resp:
                content = '{"ok": true}'
            return Resp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", MockChatOpenAI)

    rotator = RotatingLLM(cooldown_seconds=0.05, max_cooldown_wait=0.0)
    # 1st call: OpenRouter 429s -> falls back to Groq, OpenRouter NOT permanently exhausted
    rotator.invoke("msg1")
    assert rotator.openrouter_exhausted is False
    assert used[-1][0] == "gsk_groq_1"

    # Wait past cooldown and clear OpenRouter error
    time.sleep(0.08)
    should_fail_or["flag"] = False
    rotator.invoke("msg2")
    assert used[-1][0] == "sk-or-v1-router_1"


def test_rotating_llm_groq_large_output_uses_high_otpm_model(monkeypatch):
    from llm_verifier import RotatingLLM

    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY1", "gsk_groq_1")
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")

    models_tried = []

    class MockChatOpenAI:
        def __init__(self, api_key, model="", **kwargs):
            self.model = model

        def invoke(self, messages):
            models_tried.append(self.model)
            class Resp:
                content = '{"questions": []}'
            return Resp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", MockChatOpenAI)

    rotator = RotatingLLM(max_cooldown_wait=0.0)
    rotator.invoke("generate 20 questions", max_tokens=4500)
    assert models_tried == ["openai/gpt-oss-120b"]


def test_rotating_llm_discovers_all_12_keys_and_round_robins(monkeypatch):
    from llm_verifier import RotatingLLM, get_groq_keys, get_openrouter_keys

    for i in range(1, 7):
        monkeypatch.setenv(f"OPENROUTER_API_KEY{i}", f"sk-or-v1-key{i}")
        monkeypatch.setenv(f"GROQ_API_KEY{i}", f"gsk_key{i}")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert len(get_openrouter_keys()) == 6
    assert len(get_groq_keys()) == 6

    used_keys = []

    class MockChatOpenAI:
        def __init__(self, api_key, **kwargs):
            self.api_key = api_key

        def invoke(self, messages):
            used_keys.append(self.api_key)
            class Resp:
                content = '{"ok": true}'
            return Resp()

    monkeypatch.setattr("langchain_openai.ChatOpenAI", MockChatOpenAI)

    rotator = RotatingLLM(max_cooldown_wait=0.0)
    for _ in range(6):
        rotator.invoke("test")

    assert used_keys == [f"sk-or-v1-key{i}" for i in range(1, 7)]
