"""
Production Script: Sync RocketReach HR Details to Google Sheets Sheet1
======================================================================
Requirements:
1. Add dedicated 'HR Details' column to Sheet1 (Column N / 14th column).
2. For latest 10 rows (Rows 45-54): Reuse the locally fetched & verified results from latest_10_hr_results.json (0 duplicate API calls).
3. For existing rows (Rows 2-44): Fetch HR details via RocketReachClient (cached by company to avoid duplicate calls).
4. If not found, record 'Not found from RocketReach'.
5. Batch update Google Sheets to preserve rate limits and maintain 100% data integrity.
"""

import os
import sys
import json
import logging
from typing import Dict, Any, List
import gspread

# Ensure local imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rocketreach_client import RocketReachClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SyncHRDetails")

CREDENTIALS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "credentials.json"))
SPREADSHEET_ID = "1RikU9Gtm7Kx96-jARPj7xnnNTKoN5Y3GhFuT9nJudWs"
WORKSHEET_NAME = "Sheet1"

LOCAL_TESTED_RESULTS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "job_experiments", "rocketreach_hr", "latest_10_hr_results.json")
)

def run_sync():
    logger.info("Connecting to Google Sheets...")
    gc = gspread.service_account(filename=CREDENTIALS_PATH)
    ss = gc.open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet(WORKSHEET_NAME)
    
    all_rows = ws.get_all_values()
    headers = all_rows[0]
    data_rows = all_rows[1:]
    total_data_rows = len(data_rows)
    logger.info(f"Retrieved {len(all_rows)} total rows ({total_data_rows} data rows) from {WORKSHEET_NAME}")
    
    # 1. Ensure Column N header is 'HR Details'
    if len(headers) < 14 or headers[13] != "HR Details":
        logger.info("Setting Column N (14) header to 'HR Details'...")
        ws.update_acell("N1", "HR Details")
    
    # 2. Load locally tested results for the latest 10 rows
    local_results_by_row = {}
    if os.path.exists(LOCAL_TESTED_RESULTS_PATH):
        with open(LOCAL_TESTED_RESULTS_PATH, "r", encoding="utf-8") as f:
            local_data = json.load(f)
            for item in local_data:
                row_idx = item.get("sheet_row")
                disp = item.get("rocketreach", {}).get("display_text") or "Not found from RocketReach"
                local_results_by_row[row_idx] = disp
        logger.info(f"Loaded {len(local_results_by_row)} pre-tested local results for latest 10 rows")
    else:
        logger.warning(f"Local results file not found at {LOCAL_TESTED_RESULTS_PATH}")

    # 3. Initialize RocketReachClient for earlier rows (Rows 2 to 44)
    client = RocketReachClient()
    
    # Pre-populate client cache with results from the 10 tested companies
    if os.path.exists(LOCAL_TESTED_RESULTS_PATH):
        with open(LOCAL_TESTED_RESULTS_PATH, "r", encoding="utf-8") as f:
            for item in json.load(f):
                comp_key = item.get("company", "").strip().casefold()
                rr = item.get("rocketreach", {})
                client._cache[comp_key] = {
                    "company": item.get("company"),
                    "status": rr.get("status"),
                    "matched_employer": item.get("company"),
                    "hr_name": rr.get("name"),
                    "hr_title": rr.get("title"),
                    "hr_email": rr.get("email"),
                    "hr_phone": rr.get("phone"),
                    "hr_linkedin": rr.get("linkedin"),
                    "display_text": rr.get("display_text") or "Not found from RocketReach",
                }

    cutoff_row_num = total_data_rows - 10 + 2  # 1-based row number where latest 10 starts (e.g. 45)
    logger.info(f"Processing earlier rows (Rows 2 to {cutoff_row_num - 1}) via RocketReach...")
    
    hr_column_values = []
    
    for i, row in enumerate(data_rows):
        sheet_row_num = i + 2
        company = row[1].strip() if len(row) > 1 else ""
        
        # If this is one of the latest 10 rows, REUSE local verified results
        if sheet_row_num in local_results_by_row:
            hr_text = local_results_by_row[sheet_row_num]
            logger.info(f"[Row {sheet_row_num}] {company} (Reusing Local Result) -> {hr_text[:40]}...")
        else:
            # Check if existing row already has a valid HR Details text
            existing_hr = row[13].strip() if len(row) > 13 else ""
            if existing_hr and existing_hr != "Not found from RocketReach":
                hr_text = existing_hr
                logger.info(f"[Row {sheet_row_num}] {company} (Existing in Sheet) -> {hr_text[:40]}...")
            elif company:
                logger.info(f"[Row {sheet_row_num}] Querying RocketReach for '{company}'...")
                res = client.enrich_company_hr(company)
                hr_text = res.get("display_text") or "Not found from RocketReach"
                logger.info(f"   -> Result: {hr_text[:50]}...")
            else:
                hr_text = "Not found from RocketReach"
                
        hr_column_values.append([hr_text])
        
    # 4. Batch update Column N (N2:N{total_data_rows+1})
    update_range = f"N2:N{len(hr_column_values) + 1}"
    logger.info(f"Batch updating Column N ({update_range}) with {len(hr_column_values)} HR detail cells...")
    ws.update(values=hr_column_values, range_name=update_range)
    logger.info("Successfully updated Google Sheet with HR Details!")

if __name__ == "__main__":
    run_sync()
