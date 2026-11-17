"""Deterministic Unit Tests for Scraper Adapters using Mocks."""
from unittest.mock import patch
from scrapers.saarthi_scraper import SaarthiScraper
from scrapers.campusdrive_scraper import CampusDriveScraper
from scrapers.elitmus_scraper import ELitmusScraper
from scrapers.amazon_scraper import AmazonJobsScraper
from tests.fixtures.mock_responses import (
    MOCK_SAARTHI_HTML,
    MOCK_CAMPUSDRIVE_HTML,
    MOCK_ELITMUS_HTML,
    MOCK_AMAZON_JSON,
)


def test_saarthi_scraper_parses_next_data():
    scraper = SaarthiScraper()
    with patch.object(scraper, "fetch_html", return_value=MOCK_SAARTHI_HTML):
        items = scraper.scrape(max_items=10)
        assert len(items) == 2
        first = items[0]
        assert "Amazon" in first["company"]
        assert first["deadline_status"] == "OPEN"
        assert "2026" in first["batches"]
        assert first["min_salary"] == 1400000

        second = items[1]
        assert second["deadline_status"] == "CLOSED"


def test_campusdrive_scraper_parses_cards():
    scraper = CampusDriveScraper()
    with patch.object(scraper, "fetch_html", return_value=MOCK_CAMPUSDRIVE_HTML):
        items = scraper.scrape(max_items=10)
        assert len(items) == 1
        job = items[0]
        assert "Tata Communications" in job["company"]
        assert "2026" in job["batches"]
        assert "Pan India" in job["location"]


def test_elitmus_scraper_parses_listings():
    scraper = ELitmusScraper()
    with patch.object(scraper, "fetch_html", return_value=MOCK_ELITMUS_HTML):
        items = scraper.scrape(max_items=10)
        assert len(items) == 1
        job = items[0]
        assert "Software Developer" in job["title"]
        assert job["salary_raw"] == "6.0 LPA"


def test_amazon_scraper_parses_json():
    scraper = AmazonJobsScraper()
    with patch.object(scraper, "fetch_json", return_value=MOCK_AMAZON_JSON):
        items = scraper.scrape(max_items=10)
        assert len(items) == 1
        job = items[0]
        assert job["company"] == "Amazon"
        assert "Software Development Engineer" in job["title"]
        assert "Hyderabad" in job["location"]
