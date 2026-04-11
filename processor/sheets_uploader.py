"""
Google Sheets Uploader
======================
Uploads clean leads CSV to a Google Sheet, appending only NEW rows
(deduplicates against existing data in the sheet).

Setup:
    1. Create a Google Cloud project with Sheets API + Drive API enabled
    2. Create a Service Account and download the JSON key
    3. Save as config/credentials.json
    4. Create a Google Sheet and share it with the service account email
    5. Set GOOGLE_SHEET_ID in .env

Usage:
    python processor/sheets_uploader.py
"""

import os
import sys
import logging
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# Fix Windows terminal Unicode (cp1252 can't display emojis)
_console = logging.StreamHandler(stream=sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console],
)
logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

CLEAN_CSV = "output/leads_clean.csv"


def upload_to_sheets() -> int:
    """Upload clean leads to Google Sheets, appending only new rows.
    
    Returns the count of new rows uploaded.
    """
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")

    if not sheet_id:
        logger.error("❌ GOOGLE_SHEET_ID not set in .env — cannot upload")
        logger.info("   Set it in .env: GOOGLE_SHEET_ID=your_sheet_id_here")
        return 0

    if not Path(creds_path).exists():
        logger.error(f"❌ Credentials file not found: {creds_path}")
        logger.info("   Download from Google Cloud Console → Service Account → Keys")
        return 0

    if not Path(CLEAN_CSV).exists():
        logger.error("❌ Clean CSV not found. Run `python processor/cleaner.py` first.")
        return 0

    # Load clean data
    df = pd.read_csv(CLEAN_CSV, dtype=str).fillna("")
    logger.info(f"📂 Loaded {len(df)} clean leads from CSV")

    if df.empty:
        logger.info("No leads to upload — CSV is empty")
        return 0

    try:
        # Authenticate with Google
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(sheet_id).sheet1
        logger.info("🔗 Connected to Google Sheets")

        # Get existing data from sheet
        existing = sheet.get_all_records()
        logger.info(f"📊 Existing rows in sheet: {len(existing)}")

        # Build sets of existing identifiers for dedup
        existing_phones = set()
        existing_emails = set()
        for record in existing:
            phone = str(record.get("phone", "")).strip()
            email = str(record.get("email", "")).strip().lower()
            if phone:
                existing_phones.add(phone)
            if email:
                existing_emails.add(email)

        # Filter to only new rows
        new_rows = []
        for _, row in df.iterrows():
            phone = str(row.get("phone", "")).strip()
            email = str(row.get("email", "")).strip().lower()

            is_duplicate = False
            if phone and phone in existing_phones:
                is_duplicate = True
            if email and email in existing_emails:
                is_duplicate = True

            if not is_duplicate:
                new_rows.append(row.tolist())

        if not new_rows:
            logger.info("✅ No new leads to upload (all already in sheet)")
            return 0

        # If sheet is empty (no existing data), write headers first
        if not existing:
            headers = df.columns.tolist()
            sheet.update("A1", [headers])
            logger.info("📝 Added column headers to sheet")

        # Batch upload new rows (100 at a time to avoid API limits)
        batch_size = 100
        uploaded = 0
        for i in range(0, len(new_rows), batch_size):
            batch = new_rows[i:i + batch_size]
            try:
                sheet.append_rows(batch, value_input_option="RAW")
                uploaded += len(batch)
                logger.info(f"  📤 Batch {i // batch_size + 1}: uploaded {len(batch)} rows")
            except Exception as e:
                logger.error(f"  ❌ Batch {i // batch_size + 1} failed: {e}")
                # Wait and retry once
                import time
                time.sleep(5)
                try:
                    sheet.append_rows(batch, value_input_option="RAW")
                    uploaded += len(batch)
                    logger.info(f"  ✅ Batch {i // batch_size + 1}: retry successful")
                except Exception as e2:
                    logger.error(f"  ❌ Batch {i // batch_size + 1}: retry also failed: {e2}")

        logger.info("")
        logger.info("═══════════════════════════════════════════")
        logger.info(f"🎯 UPLOAD COMPLETE")
        logger.info(f"   New leads uploaded: {uploaded}")
        logger.info(f"   Existing (skipped): {len(df) - uploaded}")
        logger.info(f"   Total in sheet now: {len(existing) + uploaded}")
        logger.info("═══════════════════════════════════════════")

        return uploaded

    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(f"❌ Spreadsheet not found with ID: {sheet_id}")
        logger.info("   Make sure the sheet is shared with your service account email")
        return 0
    except Exception as e:
        logger.error(f"🚨 Upload failed: {e}")
        return 0


if __name__ == "__main__":
    upload_to_sheets()
