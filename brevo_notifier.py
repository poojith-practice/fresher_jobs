"""
Brevo Transactional Email Notifier
==================================
Sends dynamic job alert digests to a Brevo contact list (default: #477 ITC and BNP data)
using a Brevo Transactional Template with native `{% for job in params.jobs %}` loop
(default: #379 Students JOB Alert).

Never crashes the main pipeline on API/credit errors; returns structured telemetry.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("BrevoNotifier")

BREVO_BASE_URL = "https://api.brevo.com/v3"
DEFAULT_LIST_ID = 477
DEFAULT_TEMPLATE_ID = 379
DEFAULT_SENDER_EMAIL = "sandeepjethani4@gmail.com"
DEFAULT_SENDER_NAME = "Quantum Learnings"
DEFAULT_NOTE = "Ensure your resume is updated before applying."
DEFAULT_BATCH_SIZE = 50
DEFAULT_WHATSAPP_TEMPLATE_ID = 122
DEFAULT_WHATSAPP_SENDER = "917703937183"


def _is_enabled() -> bool:
    val = os.getenv("BREVO_ENABLED", "true").strip().lower()
    return val not in {"0", "false", "no", "off"}


def _get_api_key() -> str:
    val = os.getenv("BREVO_API_KEY", "").strip().strip("\"'")
    if not val or val.startswith("YOUR_"):
        return ""
    return val


def _format_package(job: Dict[str, Any]) -> str:
    sal_disp = str(job.get("salary_display") or "").strip()
    if sal_disp and sal_disp.lower() not in {"none", "nan", "not specified", "unspecified"}:
        return sal_disp
    min_amt = str(job.get("min_amount") or "").strip()
    max_amt = str(job.get("max_amount") or "").strip()
    invalid = {"", "none", "nan", "not specified", "unspecified", "0", "0.0"}
    if min_amt.lower() not in invalid and max_amt.lower() not in invalid:
        return min_amt if min_amt == max_amt else f"{min_amt} - {max_amt}"
    if min_amt.lower() not in invalid:
        return min_amt
    if max_amt.lower() not in invalid:
        return max_amt
    return "Competitive / As per industry"


def format_jobs_for_brevo(jobs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Normalizes verified job dicts into the `params.jobs` schema expected by Brevo template #379."""
    formatted: List[Dict[str, str]] = []
    for j in jobs:
        title = " ".join(str(j.get("title") or "").split())
        company = " ".join(str(j.get("company") or "").split())
        apply_url = " ".join(
            str(j.get("apply_url") or j.get("job_url_direct") or j.get("job_url") or "").split()
        )
        if not title or not company or not apply_url.startswith("http"):
            continue
        location = str(j.get("location") or "India").strip() or "India"
        deadline = str(j.get("application_last_date") or "").strip()
        if not deadline or deadline.lower() in {"none", "nan", "null", "not specified"}:
            deadline = "Apply ASAP"
        prep_url = str(j.get("interview_doc_url") or "").strip()
        if not prep_url.startswith("http"):
            prep_url = ""

        formatted.append({
            "title": title,
            "company": company,
            "location": location,
            "package": _format_package(j),
            "deadline": deadline,
            "apply_url": apply_url,
            "prep_url": prep_url,
        })
    return formatted


def fetch_list_recipients(
    api_key: str,
    list_id: int,
    timeout: int = 20,
) -> List[Dict[str, str]]:
    """Fetches active (non-blacklisted) contacts from a Brevo list."""
    headers = {"api-key": api_key, "Accept": "application/json"}
    recipients: List[Dict[str, str]] = []
    seen_emails = set()
    offset = 0
    limit = 500

    while True:
        url = f"{BREVO_BASE_URL}/contacts/lists/{list_id}/contacts?limit={limit}&offset={offset}"
        resp = requests.get(url, headers=headers, timeout=timeout)
        if not resp.ok:
            raise RuntimeError(f"Brevo list fetch failed ({resp.status_code}): {resp.text}")
        data = resp.json() or {}
        batch = data.get("contacts", []) or []
        for contact in batch:
            if contact.get("emailBlacklisted"):
                continue
            email = str(contact.get("email") or "").strip()
            if not email or "@" not in email:
                continue
            email_key = email.casefold()
            if email_key in seen_emails:
                continue
            seen_emails.add(email_key)
            attrs = contact.get("attributes") or {}
            first_name = str(attrs.get("FIRSTNAME") or "").strip()
            last_name = str(attrs.get("LASTNAME") or "").strip()
            full_name = f"{first_name} {last_name}".strip() or "Student"
            recipients.append({"email": email, "name": full_name})

        if len(batch) < limit:
            break
        offset += limit

    return recipients


def send_job_alert_digest(
    jobs: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    list_id: Optional[int] = None,
    template_id: Optional[int] = None,
    sender_email: Optional[str] = None,
    sender_name: Optional[str] = None,
    note: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Sends a single dynamic digest email per active subscriber in the Brevo list
    for the newly added verified fresher jobs.
    """
    if not _is_enabled():
        logger.info("[*] Brevo notifications disabled via BREVO_ENABLED.")
        return {"sent": False, "reason": "disabled", "batches": 0, "recipients": 0, "jobs_count": 0}

    key = (api_key or _get_api_key()).strip()
    if not key:
        logger.info("[*] Brevo notifications skipped: BREVO_API_KEY is not configured.")
        return {"sent": False, "reason": "missing_api_key", "batches": 0, "recipients": 0, "jobs_count": 0}

    formatted_jobs = format_jobs_for_brevo(jobs)
    if not formatted_jobs:
        logger.info("[*] Brevo notifications skipped: 0 new jobs to notify.")
        return {"sent": False, "reason": "no_new_jobs", "batches": 0, "recipients": 0, "jobs_count": 0}

    resolved_list_id = int(list_id or os.getenv("BREVO_LIST_ID", str(DEFAULT_LIST_ID)))
    resolved_template_id = int(template_id or os.getenv("BREVO_TEMPLATE_ID", str(DEFAULT_TEMPLATE_ID)))
    resolved_sender_email = (sender_email or os.getenv("BREVO_SENDER_EMAIL", DEFAULT_SENDER_EMAIL)).strip()
    resolved_sender_name = (sender_name or os.getenv("BREVO_SENDER_NAME", DEFAULT_SENDER_NAME)).strip()
    resolved_note = (note or os.getenv("BREVO_NOTE", DEFAULT_NOTE)).strip()

    try:
        recipients = fetch_list_recipients(key, resolved_list_id, timeout=timeout)
    except Exception as exc:
        logger.warning("[!] Brevo recipient fetch error: %s", exc)
        return {
            "sent": False,
            "reason": "recipient_fetch_error",
            "error": str(exc),
            "batches": 0,
            "recipients": 0,
            "jobs_count": len(formatted_jobs),
        }

    if not recipients:
        logger.warning("[!] Brevo list #%d has 0 active subscribers; skipping send.", resolved_list_id)
        return {
            "sent": False,
            "reason": "no_active_recipients",
            "batches": 0,
            "recipients": 0,
            "jobs_count": len(formatted_jobs),
        }

    headers = {
        "api-key": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    endpoint = f"{BREVO_BASE_URL}/smtp/email"

    batches_sent = 0
    recipients_targeted = 0
    message_ids: List[str] = []
    errors: List[str] = []

    for start in range(0, len(recipients), max(1, batch_size)):
        chunk = recipients[start : start + max(1, batch_size)]
        payload = {
            "sender": {"name": resolved_sender_name, "email": resolved_sender_email},
            "templateId": resolved_template_id,
            "params": {
                "jobs": formatted_jobs,
                "job_count": len(formatted_jobs),
                "note": resolved_note,
            },
            "messageVersions": [
                {"to": [{"email": r["email"], "name": r["name"]}]}
                for r in chunk
            ],
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.ok:
                batches_sent += 1
                recipients_targeted += len(chunk)
                data = resp.json() if resp.text else {}
                if isinstance(data, dict):
                    if data.get("messageId"):
                        message_ids.append(str(data["messageId"]))
                    if isinstance(data.get("messageIds"), list):
                        message_ids.extend(str(m) for m in data["messageIds"])
            else:
                err_msg = f"HTTP {resp.status_code}: {resp.text}"
                logger.warning("[!] Brevo send failed for batch %d: %s", start // batch_size + 1, err_msg)
                errors.append(err_msg)
        except Exception as exc:
            err_msg = str(exc)
            logger.warning("[!] Brevo send exception for batch %d: %s", start // batch_size + 1, err_msg)
            errors.append(err_msg)

    sent_ok = batches_sent > 0 and not errors
    if sent_ok:
        logger.info(
            "[✓] Brevo Alert Sent: %d new job(s) to %d student(s) in %d batch(es) (List #%d, Template #%d).",
            len(formatted_jobs), recipients_targeted, batches_sent, resolved_list_id, resolved_template_id,
        )
    return {
        "sent": sent_ok,
        "partial": batches_sent > 0 and bool(errors),
        "reason": "ok" if sent_ok else "api_error",
        "batches": batches_sent,
        "recipients": recipients_targeted,
        "total_active_recipients": len(recipients),
        "jobs_count": len(formatted_jobs),
        "message_ids": message_ids,
        "errors": errors,
    }


def _is_whatsapp_enabled() -> bool:
    val = os.getenv("BREVO_WHATSAPP_ENABLED", "true").strip().lower()
    return val not in {"0", "false", "no", "off"}


def _normalize_whatsapp_number(raw: Any) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"91{digits[1:]}"
    if 11 <= len(digits) <= 15:
        return digits
    return ""


def format_jobs_for_whatsapp(
    jobs: List[Dict[str, Any]],
    max_slot_len: int = 130,
) -> Dict[str, str]:
    """
    Formats up to 5 jobs into JOB1..JOB5 parameters for WhatsApp template #122 (imp_job_info3).
    Caps each slot at `max_slot_len` chars so total rendered message stays <= 1,024 chars.
    """
    slots: Dict[str, str] = {}
    valid = []
    for j in jobs:
        title = " ".join(str(j.get("title") or "").split())
        company = " ".join(str(j.get("company") or "").split())
        apply_url = " ".join(
            str(j.get("apply_url") or j.get("job_url_direct") or j.get("job_url") or "").split()
        )
        if title and company and apply_url.startswith("http"):
            valid.append((title, company, apply_url))
        if len(valid) == 5:
            break

    for idx in range(5):
        key = f"JOB{idx + 1}"
        if idx >= len(valid):
            slots[key] = "Check portal for more openings"
            continue
        title, company, apply_url = valid[idx]
        prefix = f"{title} @ {company}"
        full_entry = f"{prefix} {apply_url}"
        if len(full_entry) <= max_slot_len:
            slots[key] = full_entry
        elif len(apply_url) <= max_slot_len - 16:
            avail = max_slot_len - len(apply_url) - 4
            short_prefix = prefix[:max(10, avail)].rstrip() + "..."
            slots[key] = f"{short_prefix} {apply_url}"
        else:
            clean_url = apply_url.split("?", 1)[0]
            if len(clean_url) <= max_slot_len - 16:
                avail = max_slot_len - len(clean_url) - 4
                short_prefix = prefix[:max(10, avail)].rstrip() + "..."
                slots[key] = f"{short_prefix} {clean_url}"
            else:
                slots[key] = prefix[:max_slot_len]
    return slots


def fetch_list_whatsapp_recipients(
    api_key: str,
    list_id: int,
    timeout: int = 20,
) -> List[Dict[str, str]]:
    """Fetches active WhatsApp recipients (number + FIRSTNAME) from a Brevo list."""
    headers = {"api-key": api_key, "Accept": "application/json"}
    recipients: List[Dict[str, str]] = []
    seen_numbers = set()
    offset = 0
    limit = 500

    while True:
        url = f"{BREVO_BASE_URL}/contacts/lists/{list_id}/contacts?limit={limit}&offset={offset}"
        resp = requests.get(url, headers=headers, timeout=timeout)
        if not resp.ok:
            raise RuntimeError(f"Brevo list fetch failed ({resp.status_code}): {resp.text}")
        data = resp.json() or {}
        batch = data.get("contacts", []) or []
        for contact in batch:
            if contact.get("smsBlacklisted") or contact.get("whatsappBlacklisted"):
                continue
            email = str(contact.get("email") or "").strip()
            attrs = contact.get("attributes") or {}
            number = _normalize_whatsapp_number(attrs.get("WHATSAPP") or attrs.get("SMS"))
            if not number or number in seen_numbers:
                continue
            seen_numbers.add(number)
            first_name = str(attrs.get("FIRSTNAME") or "").strip().split()[0] if str(attrs.get("FIRSTNAME") or "").strip() else "Student"
            recipients.append({"email": email, "number": number, "first_name": first_name})

        if len(batch) < limit:
            break
        offset += limit

    return recipients


def send_whatsapp_job_alert(
    jobs: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    list_id: Optional[int] = None,
    template_id: Optional[int] = None,
    sender_number: Optional[str] = None,
    recipients_override: Optional[List[Dict[str, str]]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    """
    Sends a WhatsApp job alert (top 5 jobs) using Brevo template #122 (`imp_job_info3`)
    to all active WhatsApp contacts in the configured Brevo list.
    """
    if not _is_whatsapp_enabled():
        logger.info("[*] Brevo WhatsApp notifications disabled via BREVO_WHATSAPP_ENABLED.")
        return {"sent": False, "reason": "disabled", "sent_count": 0, "failed_count": 0, "jobs_count": 0}

    key = (api_key or _get_api_key()).strip()
    if not key:
        logger.info("[*] Brevo WhatsApp skipped: BREVO_API_KEY is not configured.")
        return {"sent": False, "reason": "missing_api_key", "sent_count": 0, "failed_count": 0, "jobs_count": 0}

    valid_jobs = format_jobs_for_brevo(jobs)
    if not valid_jobs:
        logger.info("[*] Brevo WhatsApp skipped: 0 new jobs to notify.")
        return {"sent": False, "reason": "no_new_jobs", "sent_count": 0, "failed_count": 0, "jobs_count": 0}

    job_slots = format_jobs_for_whatsapp(jobs)
    resolved_list_id = int(list_id or os.getenv("BREVO_LIST_ID", str(DEFAULT_LIST_ID)))
    resolved_template_id = int(template_id or os.getenv("BREVO_WHATSAPP_TEMPLATE_ID", str(DEFAULT_WHATSAPP_TEMPLATE_ID)))
    resolved_sender = _normalize_whatsapp_number(
        sender_number or os.getenv("BREVO_WHATSAPP_SENDER", DEFAULT_WHATSAPP_SENDER)
    ) or DEFAULT_WHATSAPP_SENDER

    if recipients_override is not None:
        recipients = recipients_override
    else:
        try:
            recipients = fetch_list_whatsapp_recipients(key, resolved_list_id, timeout=timeout)
        except Exception as exc:
            logger.warning("[!] Brevo WhatsApp recipient fetch error: %s", exc)
            return {
                "sent": False,
                "reason": "recipient_fetch_error",
                "error": str(exc),
                "sent_count": 0,
                "failed_count": 0,
                "jobs_count": min(5, len(valid_jobs)),
            }

    if not recipients:
        logger.warning("[!] Brevo list #%d has 0 active WhatsApp numbers; skipping.", resolved_list_id)
        return {
            "sent": False,
            "reason": "no_active_recipients",
            "sent_count": 0,
            "failed_count": 0,
            "jobs_count": min(5, len(valid_jobs)),
        }

    headers = {
        "api-key": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Brevo WhatsApp templates bound to Contact Attributes (JOB1..JOB5, FIRSTNAME)
    # read values from each contact's CRM attributes, so batch-update JOB1..JOB5 first.
    emails_to_update = [r["email"] for r in recipients if r.get("email")]
    if emails_to_update:
        batch_url = f"{BREVO_BASE_URL}/contacts/batch"
        for start in range(0, len(emails_to_update), 100):
            email_chunk = emails_to_update[start : start + 100]
            try:
                b_resp = requests.post(
                    batch_url,
                    headers=headers,
                    json={"contacts": [{"email": em, "attributes": job_slots} for em in email_chunk]},
                    timeout=timeout,
                )
                if not b_resp.ok:
                    logger.warning("[!] Brevo WhatsApp attribute batch update failed (%s): %s", b_resp.status_code, b_resp.text)
            except Exception as exc:
                logger.warning("[!] Brevo WhatsApp attribute batch update error: %s", exc)

    endpoint = f"{BREVO_BASE_URL}/whatsapp/sendMessage"

    sent_count = 0
    failed_count = 0
    message_ids: List[str] = []
    errors: List[str] = []

    numbers = [r["number"] for r in recipients if r.get("number")]
    for start in range(0, len(numbers), 50):
        chunk = numbers[start : start + 50]
        payload = {
            "senderNumber": resolved_sender,
            "contactNumbers": chunk,
            "templateId": resolved_template_id,
            "params": {
                "FIRSTNAME": "Student",
                **job_slots,
            },
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if resp.ok:
                sent_count += len(chunk)
                data = resp.json() if resp.text else {}
                if isinstance(data, dict) and data.get("messageId"):
                    message_ids.append(str(data["messageId"]))
            else:
                failed_count += len(chunk)
                errors.append(f"Batch {start // 50 + 1}: HTTP {resp.status_code}: {resp.text}")
        except Exception as exc:
            failed_count += len(chunk)
            errors.append(f"Batch {start // 50 + 1}: {exc}")

    sent_ok = sent_count > 0 and failed_count == 0
    if sent_count > 0:
        logger.info(
            "[✓] Brevo WhatsApp Alert Sent: %d job(s) to %d/%d student(s) (List #%d, Template #%d).",
            min(5, len(valid_jobs)), sent_count, len(recipients), resolved_list_id, resolved_template_id,
        )
    return {
        "sent": sent_ok,
        "partial": sent_count > 0 and failed_count > 0,
        "reason": "ok" if sent_ok else ("partial_error" if sent_count > 0 else "api_error"),
        "sent_count": sent_count,
        "failed_count": failed_count,
        "total_recipients": len(recipients),
        "jobs_count": min(5, len(valid_jobs)),
        "message_ids": message_ids,
        "errors": errors[:10],
    }
