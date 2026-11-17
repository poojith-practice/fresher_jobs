"""Unit Tests for Off-Campus Classification & Generic Drive Preservation."""
from models.opportunity import OpportunityType
from normalization.opportunity_classifier import classify_opportunity_type


def test_generic_off_campus_drives_classified_correctly():
    cases = [
        ("TCS National Qualifier Test 2026", OpportunityType.OFF_CAMPUS_DRIVE),
        ("Cognizant GenC Off-Campus Drive 2026", OpportunityType.OFF_CAMPUS_DRIVE),
        ("Wipro Elite National Talent Hunt Program", OpportunityType.OFF_CAMPUS_DRIVE),
        ("Infosys Off Campus Recruitment Drive for Freshers", OpportunityType.OFF_CAMPUS_DRIVE),
        ("Accenture Pan-India Graduate Hiring Drive", OpportunityType.OFF_CAMPUS_DRIVE),
        ("Walk-in Drive for Freshers - Vadodara", OpportunityType.OFF_CAMPUS_DRIVE),
    ]
    for title, expected in cases:
        assert classify_opportunity_type(title) == expected, f"Failed on {title}"


def test_individual_roles_classified_correctly():
    cases = [
        ("Junior Python Developer", OpportunityType.INDIVIDUAL_FRESHER_JOB),
        ("Full Stack Engineer (Fresher)", OpportunityType.INDIVIDUAL_FRESHER_JOB),
        ("Data Analyst Trainee", OpportunityType.INDIVIDUAL_FRESHER_JOB),
        ("Graduate Engineer Trainee - QA Testing", OpportunityType.INDIVIDUAL_FRESHER_JOB),
    ]
    for title, expected in cases:
        assert classify_opportunity_type(title) == expected, f"Failed on {title}"
