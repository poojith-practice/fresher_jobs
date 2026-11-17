"""Unit Tests for Experience Gating and Contradiction Detection."""
from verification.experience_verifier import verify_experience


def test_standard_fresher_passes():
    ok, summary, sup, cont = verify_experience(
        title="Associate Software Engineer",
        description="Freshers welcome. 0-1 years experience required.",
    )
    assert ok is True
    assert "Fresher Eligible" in summary


def test_experience_contradiction_fails_case_2():
    # CASE 2: "2026 batch eligible, minimum 2 years of professional experience required."
    ok, summary, sup, cont = verify_experience(
        title="Software Engineer - 2026 Batch",
        description="2026 batch candidates eligible. Minimum 3 years of commercial experience required.",
        batches=["2026"],
    )
    assert ok is False
    assert any("exceeds fresher ceiling" in c for c in cont)
    assert any("Contradictory requirement" in c for c in cont)


def test_missing_experience_graduate_trainee_passes_case_3():
    # CASE 3: Graduate trainee position with no explicit experience field targeting university grads
    ok, summary, sup, cont = verify_experience(
        title="Graduate Engineer Trainee",
        description="Campus hiring program for engineering graduates.",
        batches=["2026"],
    )
    assert ok is True
    assert any("graduate cohort verified" in s.lower() or "entry-level title" in s.lower() for s in sup)


def test_senior_role_without_experience_rejected_case_4():
    # CASE 4: Senior software engineer position with no experience information
    ok, summary, sup, cont = verify_experience(
        title="Senior Software Architect",
        description="Lead cloud infrastructure team.",
    )
    assert ok is False
    assert any("Seniority conflict in title" in c for c in cont)


def test_non_internship_experience_rejected():
    # Tests that 1+ years of non-internship experience is strictly rejected
    ok, summary, sup, cont = verify_experience(
        title="Software Dev Engineer I FTC",
        description="Basic Qualifications:\n- 1+ years of non-internship professional software development experience\n- Experience programming with at least one software programming language",
    )
    assert ok is False
    assert "Commercial Experience Required" in summary
    assert any("non-internship" in c.lower() for c in cont)

