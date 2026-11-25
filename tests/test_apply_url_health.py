from unittest.mock import MagicMock, patch

from scraper import check_apply_url_alive


def test_check_apply_url_alive_rejects_soft_404_redirect_and_404_status():
    soft_404_resp = MagicMock()
    soft_404_resp.status_code = 200
    soft_404_resp.url = "https://careers.bankofamerica.com/en-us/errors/404"
    soft_404_resp.text = "<html><body>We're Sorry. The page you are looking for cannot be found.</body></html>"

    with patch("requests.get", return_value=soft_404_resp):
        alive, reason = check_apply_url_alive(
            "https://careers.bankofamerica.com/en-us/job-detail/26043633/software-engineer-multiple-locations"
        )
    assert alive is False
    assert "error page" in reason or "soft-404" in reason

    http_404 = MagicMock()
    http_404.status_code = 404
    http_404.url = "https://careers.example.com/job/999"
    with patch("requests.get", return_value=http_404):
        alive_404, _ = check_apply_url_alive("https://careers.example.com/job/999")
    assert alive_404 is False


def test_check_apply_url_alive_skips_boards_and_fails_open_on_403_or_timeout():
    # Known anti-bot job boards must never trigger HTTP probes
    with patch("requests.get") as mock_get:
        alive_li, note_li = check_apply_url_alive("https://www.linkedin.com/jobs/view/4414951714")
    mock_get.assert_not_called()
    assert alive_li is True
    assert note_li == "SKIPPED_BOARD_URL"

    # Anti-bot 403 / timeout on external corporate ATS fails open
    blocked_resp = MagicMock()
    blocked_resp.status_code = 403
    blocked_resp.url = "https://jobs.tetrapak.com/job/123"
    with patch("requests.get", return_value=blocked_resp):
        alive_403, _ = check_apply_url_alive("https://jobs.tetrapak.com/job/123")
    assert alive_403 is True

    with patch("requests.get", side_effect=TimeoutError("timed out")):
        alive_to, _ = check_apply_url_alive("https://careers.qualcomm.com/job/123")
    assert alive_to is True


def test_check_apply_url_alive_accepts_healthy_external_ats():
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.url = "https://jobs.tetrapak.com/job/Future-Talent-Junior-IT-Analyst/100383-en_GB"
    ok_resp.text = "<html><body><h1>Future Talent - Junior IT Analyst</h1><button>Apply now</button></body></html>"
    with patch("requests.get", return_value=ok_resp):
        alive, note = check_apply_url_alive(ok_resp.url)
    assert alive is True
    assert note == "VERIFIED_ACTIVE"
