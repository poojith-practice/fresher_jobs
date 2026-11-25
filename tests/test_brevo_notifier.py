from unittest.mock import MagicMock, patch

from brevo_notifier import (
    fetch_list_recipients,
    format_jobs_for_brevo,
    send_job_alert_digest,
)


def test_format_jobs_for_brevo_extracts_dynamic_loop_fields():
    jobs = [
        {
            "title": "Graduate Engineer Trainee",
            "company": "Qualcomm",
            "location": "Bangalore",
            "min_amount": "12 LPA",
            "max_amount": "14 LPA",
            "application_last_date": "2026-12-05",
            "apply_url": "https://careers.qualcomm.com/job/123",
            "interview_doc_url": "https://drive.google.com/file/d/abc/view",
        },
        {
            "title": "Junior Analyst",
            "company": "EY",
            "location": "Mumbai",
            "min_amount": "Not Specified",
            "max_amount": "Not Specified",
            "job_url": "https://eyglobal.yello.co/job/456",
        },
        {
            "title": "Invalid No URL",
            "company": "SkipMe",
            "location": "Pune",
            "apply_url": "",
        },
    ]
    formatted = format_jobs_for_brevo(jobs)
    assert len(formatted) == 2
    assert formatted[0] == {
        "title": "Graduate Engineer Trainee",
        "company": "Qualcomm",
        "location": "Bangalore",
        "package": "12 LPA - 14 LPA",
        "deadline": "2026-12-05",
        "apply_url": "https://careers.qualcomm.com/job/123",
        "prep_url": "https://drive.google.com/file/d/abc/view",
    }
    assert formatted[1]["package"] == "Competitive / As per industry"
    assert formatted[1]["deadline"] == "Apply ASAP"
    assert formatted[1]["prep_url"] == ""


def test_fetch_list_recipients_skips_blacklisted_and_dedups():
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "contacts": [
            {"email": "a@example.com", "emailBlacklisted": False, "attributes": {"FIRSTNAME": "Ayan", "LASTNAME": "J"}},
            {"email": "A@example.com", "emailBlacklisted": False, "attributes": {"FIRSTNAME": "Dup"}},
            {"email": "blocked@example.com", "emailBlacklisted": True, "attributes": {"FIRSTNAME": "Blocked"}},
            {"email": "b@example.com", "emailBlacklisted": False, "attributes": {}},
        ]
    }
    with patch("brevo_notifier.requests.get", return_value=mock_resp) as mock_get:
        recipients = fetch_list_recipients("test-key", 477)
    mock_get.assert_called_once()
    assert recipients == [
        {"email": "a@example.com", "name": "Ayan J"},
        {"email": "b@example.com", "name": "Student"},
    ]


def test_send_job_alert_digest_sends_batched_template_payload():
    get_resp = MagicMock()
    get_resp.ok = True
    get_resp.json.return_value = {
        "contacts": [
            {"email": "s1@example.com", "emailBlacklisted": False, "attributes": {"FIRSTNAME": "S1"}},
            {"email": "s2@example.com", "emailBlacklisted": False, "attributes": {"FIRSTNAME": "S2"}},
            {"email": "s3@example.com", "emailBlacklisted": False, "attributes": {"FIRSTNAME": "S3"}},
        ]
    }
    post_resp = MagicMock()
    post_resp.ok = True
    post_resp.text = '{"messageIds": ["msg-1", "msg-2"]}'
    post_resp.json.return_value = {"messageIds": ["msg-1", "msg-2"]}

    jobs = [
        {
            "title": "Software Engineer",
            "company": "Proofpoint",
            "location": "Bengaluru",
            "apply_url": "https://www.linkedin.com/jobs/view/4414951714",
        }
    ]
    with patch("brevo_notifier.requests.get", return_value=get_resp), \
         patch("brevo_notifier.requests.post", return_value=post_resp) as mock_post:
        res = send_job_alert_digest(
            jobs,
            api_key="xkeysib-test",
            list_id=477,
            template_id=379,
            sender_email="sandeepjethani4@gmail.com",
            sender_name="Quantum Learnings",
            batch_size=2,
        )

    assert res["sent"] is True
    assert res["batches"] == 2
    assert res["recipients"] == 3
    assert res["jobs_count"] == 1
    assert mock_post.call_count == 2
    first_payload = mock_post.call_args_list[0].kwargs["json"]
    assert first_payload["templateId"] == 379
    assert first_payload["sender"] == {"name": "Quantum Learnings", "email": "sandeepjethani4@gmail.com"}
    assert first_payload["params"]["job_count"] == 1
    assert len(first_payload["params"]["jobs"]) == 1
    assert len(first_payload["messageVersions"]) == 2


def test_send_job_alert_digest_handles_missing_key_and_api_errors_gracefully(monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    res_no_key = send_job_alert_digest([{"title": "SWE", "company": "X", "apply_url": "https://x.com"}])
    assert res_no_key["sent"] is False
    assert res_no_key["reason"] == "missing_api_key"

    get_resp = MagicMock()
    get_resp.ok = True
    get_resp.json.return_value = {"contacts": [{"email": "s1@example.com", "emailBlacklisted": False, "attributes": {}}]}
    post_resp = MagicMock()
    post_resp.ok = False
    post_resp.status_code = 402
    post_resp.text = '{"code":"not_enough_credits","message":"Not enough credits"}'

    with patch("brevo_notifier.requests.get", return_value=get_resp), \
         patch("brevo_notifier.requests.post", return_value=post_resp):
        res_err = send_job_alert_digest(
            [{"title": "SWE", "company": "X", "apply_url": "https://x.com"}],
            api_key="xkeysib-test",
        )
    assert res_err["sent"] is False
    assert res_err["reason"] == "api_error"
    assert "402" in res_err["errors"][0]
