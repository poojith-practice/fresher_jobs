"""Unit Tests for Company Authenticity & Scam Screening."""
from models.verification_result import CompanyAuthenticity
from verification.company_verifier import verify_company_authenticity


def test_official_corporate_domain():
    auth, sup, flags = verify_company_authenticity(
        company="Amazon",
        apply_url="https://www.amazon.jobs/en/jobs/12345/sde",
    )
    assert auth == CompanyAuthenticity.VERIFIED_OFFICIAL
    assert len(flags) == 0


def test_reputable_aggregator_domain():
    auth, sup, flags = verify_company_authenticity(
        company="MountBlue",
        apply_url="https://www.elitmus.com/jobs/33235",
    )
    assert auth == CompanyAuthenticity.REPUTABLE_AGGREGATOR


def test_registration_fee_scam_rejected_case_6():
    # CASE 6: Fee-charging training scam masquerading as fresher drive
    auth, sup, flags = verify_company_authenticity(
        company="Apex Careers",
        apply_url="https://apexcareers.example.com/apply",
        text_content="Mandatory registration fee of Rs 1500 required before interview.",
    )
    assert auth == CompanyAuthenticity.FRAUDULENT
    assert any("registration fee" in f.lower() for f in flags)
