"""Unit Tests for Isolated Storage and Provenance Merging."""
import tempfile
from pathlib import Path
from models.opportunity import Opportunity, OpportunityType
from storage.experimental_store import ExperimentalStore


def test_storage_and_provenance_deduplication():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_store.db"
        store = ExperimentalStore(db_path=db_path)

        opp1 = Opportunity(
            id="opp-1",
            opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
            title="TCS NQT 2026",
            normalized_title="TCS NQT 2026",
            company="TCS",
            location="Pan India",
            description="TCS National Qualifier Test",
            source_id="campusdrive",
            listing_url="https://campusdrive.in/tcs",
            apply_url="https://campusdrive.in/tcs",
            provenance=["campusdrive"],
            discovered_at="2026-11-17T00:00:00",
        )
        saved1 = store.save_opportunity(opp1)
        assert saved1.provenance == ["campusdrive"]

        # Same opportunity discovered later via another source (Saarthi)
        opp2 = Opportunity(
            id="opp-2",
            opportunity_type=OpportunityType.OFF_CAMPUS_DRIVE,
            title="TCS NQT 2026",
            normalized_title="TCS NQT 2026",
            company="TCS",
            location="Pan India",
            description="TCS NQT duplicate from Saarthi",
            source_id="saarthi_drives",
            listing_url="https://joinsaarthi.com/tcs",
            apply_url="https://campusdrive.in/tcs",  # matching normalized identity
            provenance=["saarthi_drives"],
            discovered_at="2026-11-17T01:00:00",
        )
        saved2 = store.save_opportunity(opp2)
        # Verify provenance was merged and ID preserved
        assert saved2.id == saved1.id
        assert "campusdrive" in saved2.provenance
        assert "saarthi_drives" in saved2.provenance
