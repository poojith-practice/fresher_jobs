"""Unit Tests for Extraction Utilities and Auxiliary Modules."""
from bs4 import BeautifulSoup
from extraction.listing_extractor import ListingExtractor
from extraction.detail_extractor import DetailExtractor
from extraction.apply_link_resolver import ApplyLinkResolver
from verification.fresher_eligibility import verify_fresher_eligibility
from models.opportunity import Opportunity, OpportunityType
from evaluation.manual_review import ManualReviewQueue
from evaluation.source_comparison import generate_source_comparison_report


def test_listing_extractor_clean_text_and_link():
    html = """<div><a href="/jobs/123">   Software   Engineer  </a></div>"""
    soup = BeautifulSoup(html, "lxml")
    a_tag = soup.find("a")
    text = ListingExtractor.clean_text(a_tag)
    assert text == "Software Engineer"
    
    link = ListingExtractor.extract_link(a_tag, base_url="https://example.com")
    assert link == "https://example.com/jobs/123"


def test_detail_extractor_full_text():
    html = """
    <html>
        <body>
            <header>Ignore Header</header>
            <article class="job-description">
                <h1>Python Developer</h1>
                <p>We are seeking a 2026 batch fresher for Python and SQL development.</p>
                <a href="https://careers.google.com/apply">Apply Now</a>
            </article>
            <footer>Ignore Footer</footer>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    text = DetailExtractor.extract_full_text(soup)
    assert "Python Developer" in text
    assert "2026 batch fresher" in text
    assert "Ignore Header" not in text

    apply_link = DetailExtractor.extract_direct_apply_link(soup)
    assert apply_link == "https://careers.google.com/apply"


def test_unified_fresher_eligibility_verifier():
    opp = Opportunity(
        id="test-fresher-1",
        opportunity_type=OpportunityType.INDIVIDUAL_FRESHER_JOB,
        title="Associate Software Engineer",
        normalized_title="Associate Software Engineer",
        company="Acme Corp",
        location="Bengaluru",
        description="Inviting 2026 batch engineering graduates. 0 years experience required.",
        source_id="test",
        listing_url="https://acme.com/jobs/1",
        apply_url="https://acme.com/jobs/1",
        eligible_batches=["2026"],
        provenance=["test"],
        discovered_at="2026-11-17T00:00:00",
    )
    audit = verify_fresher_eligibility(opp)
    assert audit.is_fresher_eligible is True
    assert "2026" in audit.detected_batches
    assert audit.confidence >= 0.85


def test_source_comparison_report_structure():
    report = generate_source_comparison_report()
    assert "sources" in report
    assert "overall" in report
    assert report["overall"]["total_opportunities"] >= 0
