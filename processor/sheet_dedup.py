"""
Sheet Deduplicator (FAST)
=========================
Reads all data from Google Sheet, removes duplicates locally,
clears the sheet, and writes back only unique rows.

Much faster than deleting rows one by one.

Usage:
    python processor/sheet_dedup.py
"""

import os
import sys
import re
import logging
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def normalize_phone(phone_str):
    """Strip everything except digits, normalize to 91XXXXXXXXXX."""
    if not phone_str:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone_str).strip())
    if digits.startswith("0") and len(digits) == 11:
        digits = "91" + digits[1:]
    elif len(digits) == 10 and digits and digits[0] in "6789":
        digits = "91" + digits
    return digits


def dedup_sheet():
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")

    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID not set in .env")
        return
    if not Path(creds_path).exists():
        logger.error(f"Credentials not found: {creds_path}")
        return

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id).sheet1

    # Read everything
    all_rows = sheet.get_all_values()
    if len(all_rows) < 2:
        logger.info("Sheet is empty or only has headers")
        return

    headers = all_rows[0]
    data_rows = all_rows[1:]
    total_before = len(data_rows)
    logger.info(f"Total rows in sheet: {total_before}")

    # Find column indices
    def col_index(name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    phone_idx = col_index("phone")
    name_idx = col_index("business_name")
    city_idx = col_index("city")
    maps_idx = col_index("google_maps_url")

    logger.info(f"Columns - phone:{phone_idx}, name:{name_idx}, city:{city_idx}, maps:{maps_idx}")

    # Deduplicate locally
    seen_phones = set()
    seen_names_cities = set()
    seen_maps = set()
    unique_rows = []
    dupes_removed = 0

    for row in data_rows:
        phone = normalize_phone(row[phone_idx]) if phone_idx >= 0 and phone_idx < len(row) else ""
        name = (row[name_idx].strip().lower()) if name_idx >= 0 and name_idx < len(row) else ""
        city = (row[city_idx].strip().lower()) if city_idx >= 0 and city_idx < len(row) else ""
        maps_url = (row[maps_idx].strip().lower()) if maps_idx >= 0 and maps_idx < len(row) else ""

        is_dup = False

        # Check phone
        if phone and len(phone) >= 10:
            if phone in seen_phones:
                is_dup = True
            else:
                seen_phones.add(phone)

        # Check name+city
        if not is_dup and name and city:
            key = f"{name}|{city}"
            if key in seen_names_cities:
                is_dup = True
            else:
                seen_names_cities.add(key)

        # Check maps URL
        if not is_dup and maps_url and maps_url not in ("", "none", "n/a"):
            if maps_url in seen_maps:
                is_dup = True
            else:
                seen_maps.add(maps_url)

        if is_dup:
            dupes_removed += 1
        else:
            unique_rows.append(row)

    logger.info(f"Duplicates found: {dupes_removed}")
    logger.info(f"Unique rows: {len(unique_rows)}")

    if dupes_removed == 0:
        logger.info("No duplicates found. Sheet is clean.")
        return

    # Clear only data rows (keep header row which may be protected)
    last_row = total_before + 1  # +1 for header
    end_col = chr(64 + len(headers)) if len(headers) <= 26 else "Z"
    data_range = f"A2:{end_col}{last_row + 100}"  # +100 buffer to clear any stragglers
    logger.info(f"Clearing data range {data_range}...")
    try:
        sheet.batch_clear([data_range])
    except Exception as e:
        logger.error(f"batch_clear failed: {e}, trying delete_rows...")
        # Fallback: delete all rows from 2 onwards
        try:
            sheet.delete_rows(2, last_row)
        except Exception as e2:
            logger.error(f"delete_rows also failed: {e2}")
            logger.error("Please remove sheet protection and try again.")
            return

    # Write unique rows in batches
    batch_size = 500
    for i in range(0, len(unique_rows), batch_size):
        batch = unique_rows[i:i + batch_size]
        start_row = i + 2  # +1 header, +1 for 1-based
        end_row = start_row + len(batch) - 1
        end_col = chr(64 + len(headers)) if len(headers) <= 26 else "Z"
        cell_range = f"A{start_row}:{end_col}{end_row}"

        try:
            sheet.update(cell_range, batch)
            logger.info(f"  Wrote batch {i // batch_size + 1}: rows {start_row}-{end_row}")
        except Exception as e:
            logger.error(f"  Batch write failed: {e}")
            # Fallback: append rows
            try:
                sheet.append_rows(batch, value_input_option="RAW")
                logger.info(f"  Fallback append succeeded for batch {i // batch_size + 1}")
            except Exception as e2:
                logger.error(f"  Fallback also failed: {e2}")

        import time
        time.sleep(1)

    logger.info("")
    logger.info("=" * 45)
    logger.info("DEDUP COMPLETE")
    logger.info(f"  Rows before:       {total_before}")
    logger.info(f"  Duplicates removed: {dupes_removed}")
    logger.info(f"  Rows after:        {len(unique_rows)}")
    logger.info("=" * 45)


if __name__ == "__main__":
    dedup_sheet()
