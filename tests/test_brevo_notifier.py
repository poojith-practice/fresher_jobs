from unittest.mock import MagicMock, patch

from brevo_notifier import (
    fetch_list_recipients,
    fetch_list_whatsapp_recipients,
    format_jobs_for_brevo,
    format_jobs_for_whatsapp,
    send_job_alert_digest,
    send_whatsapp_job_alert,
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


def test_format_jobs_for_whatsapp_caps_slots_and_pads_to_5():
    jobs = [
        {"title": "Software Engineer", "company": "Qualcomm", "apply_url": "https://careers.qualcomm.com/job/1"},
        {"title": "Very Long Job Title That Needs Truncation For WhatsApp Limit", "company": "Oracle Cloud Systems India Pvt Ltd", "apply_url": "https://ejgk.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3/job/30051984/?keyword=analyst"},
    ]
    slots = format_jobs_for_whatsapp(jobs, max_slot_len=130)
    assert set(slots.keys()) == {"JOB1", "JOB2", "JOB3", "JOB4", "JOB5"}
    assert all(len(v) <= 130 for v in slots.values())
    assert slots["JOB3"] == "Check portal for more openings"
    assert slots["JOB5"] == "Check portal for more openings"


def test_send_whatsapp_job_alert_sends_5_jobs_to_active_contacts():
    get_resp = MagicMock()
    get_resp.ok = True
    get_resp.json.return_value = {
        "contacts": [
            {"email": "a@example.com", "smsBlacklisted": False, "attributes": {"FIRSTNAME": "Aafiya Shaikh", "WHATSAPP": "9000326016"}},
            {"email": "b@example.com", "smsBlacklisted": True, "attributes": {"FIRSTNAME": "OptedOut", "WHATSAPP": "919999999999"}},
            {"email": "c@example.com", "smsBlacklisted": False, "attributes": {"FIRSTNAME": "", "SMS": "+91 98335 23711"}},
        ]
    }
    post_resp = MagicMock()
    post_resp.ok = True
    post_resp.text = '{"messageId": "wa-msg-1"}'
    post_resp.json.return_value = {"messageId": "wa-msg-1"}

    jobs = [
        {"title": f"Role {i}", "company": f"Comp {i}", "apply_url": f"https://example.com/j/{i}"}
        for i in range(1, 7)
    ]
    with patch("brevo_notifier.requests.get", return_value=get_resp), \
         patch("brevo_notifier.requests.post", return_value=post_resp) as mock_post:
        res = send_whatsapp_job_alert(
            jobs,
            api_key="xkeysib-test",
            list_id=477,
            template_id=122,
            sender_number="917703937183",
        )

    assert res["sent"] is True
    assert res["sent_count"] == 2
    assert res["jobs_count"] == 5
    # 1st POST is /contacts/batch (JOB1..JOB5 attribute sync), 2nd POST is /whatsapp/sendMessage
    assert mock_post.call_count == 2
    batch_call = mock_post.call_args_list[0]
    assert "/contacts/batch" in batch_call.args[0]
    assert len(batch_call.kwargs["json"]["contacts"]) == 2
    assert "Role 1 @ Comp 1" in batch_call.kwargs["json"]["contacts"][0]["attributes"]["JOB1"]

    wa_call = mock_post.call_args_list[1]
    assert "/whatsapp/sendMessage" in wa_call.args[0]
    p1 = wa_call.kwargs["json"]
    assert p1["senderNumber"] == "917703937183"
    assert p1["contactNumbers"] == ["919000326016", "919833523711"]
    assert p1["templateId"] == 122
    assert "Role 1 @ Comp 1" in p1["params"]["JOB1"]
