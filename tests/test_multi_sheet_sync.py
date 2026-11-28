from unittest.mock import patch

from google_sheets_sync import (
    get_configured_spreadsheet_ids,
    sync_configured_google_sheet,
)


def test_get_configured_spreadsheet_ids_supports_primary_and_secondary(monkeypatch):
    monkeypatch.setenv("GOOGLE_SPREADSHEET_ID", "sheet_1, sheet_2")
    monkeypatch.setenv("GOOGLE_SPREADSHEET_ID_2", "sheet_3")
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID_2", raising=False)
    assert get_configured_spreadsheet_ids() == ["sheet_1", "sheet_2", "sheet_3"]


def test_sync_configured_google_sheet_syncs_both_and_only_tracks_new_on_primary(monkeypatch):
    monkeypatch.setenv("GOOGLE_SPREADSHEET_ID", "sheet_primary")
    monkeypatch.setenv("GOOGLE_SPREADSHEET_ID_2", "sheet_secondary")
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID_2", raising=False)

    calls = []

    def fake_sync(sid, **kwargs):
        calls.append((sid, kwargs.get("newly_added_out")))
        return True

    newly_out = []
    with patch("google_sheets_sync.sync_to_live_google_sheet", side_effect=fake_sync):
        ok = sync_configured_google_sheet([{"title": "SWE"}], newly_added_out=newly_out)

    assert ok is True
    assert calls[0] == ("sheet_primary", newly_out)
    assert calls[1] == ("sheet_secondary", None)
