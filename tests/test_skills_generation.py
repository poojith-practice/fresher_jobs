"""Unit Tests for Dynamic Skills Generation."""
from models.opportunity import OpportunityType
from normalization.skills_generator import generate_skills


def test_python_developer_inferred_skills():
    explicit, inferred = generate_skills(
        title="Python Developer",
        description="Looking for fresh graduates with strong problem-solving skills.",
        opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
    )
    assert "Python" in explicit or "Python" in inferred
    assert any("Data Structures" in s or "OOP" in s or "SQL" in s for s in inferred)


def test_data_analyst_inferred_skills():
    explicit, inferred = generate_skills(
        title="Junior Data Analyst",
        description="Entry level analytics role.",
        opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
    )
    assert any("SQL" in s or "Excel" in s or "Statistics" in s for s in inferred)


def test_generic_off_campus_drive_does_not_fabricate_tech_skills():
    explicit, inferred = generate_skills(
        title="TCS National Qualifier Test 2026",
        description="Pan-India recruitment for engineering graduates across multiple business units.",
        opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
    )
    # Must NOT fabricate React, Python, or Docker when none is mentioned
    assert "React" not in explicit and "React" not in inferred
    assert "Docker" not in explicit and "Docker" not in inferred
    assert any("Aptitude" in s or "Analytical" in s for s in inferred)
