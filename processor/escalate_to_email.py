"""
Escalate to Email — Staggered Multi-Channel Outreach
======================================================
Runs daily AFTER the WhatsApp outreach has processed leads.

Reads the "Daily Mix" tab for leads that have been contacted via
WhatsApp (status = "contacted" or "call_routed") AND have a valid
email address. Adds them to the "Email Queue" tab so the email
workflow sends them a follow-up email the next day.

This creates a natural stagger:
  Day 1: WhatsApp (via Daily Mix → n8n)
  Day 2: Email (via this script → Email Queue → n8n)

Usage:
    python processor/escalate_to_email.py              # Run it
    python processor/escalate_to_email.py --dry-run     # Preview only
"""

import os
import sys
import re
import logging
import argparse
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(stream=sys.stdout)],
)
logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

DAILY_MIX_TAB = "Daily Mix"
EMAIL_QUEUE_TAB = "Email Queue"

# Statuses that mean "WhatsApp was attempted" — ready for email escalation
ESCALATION_STATUSES = {"contacted", "call_routed"}


def has_valid_email(email_str) -> bool:
    """Check if lead has a usable email address."""
    if not email_str:
        return False
    email = str(email_str).strip().lower()
    if not email or email in ("", "none", "n/a", "na"):
        return False
    if "@" not in email or "." not in email:
        return False
    return True


def is_real_website(url):
    """Check if URL is a real business website."""
    if not url or url.strip() in ("", "None", "none", "N/A"):
        return False
    return "." in url.lower().strip() and len(url.strip()) >= 5


def main():
    parser = argparse.ArgumentParser(description="Escalate WhatsApp leads to Email Queue")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    logger.info("═══════════════════════════════════════════")
    logger.info("  ESCALATE TO EMAIL — Multi-Channel Step 2")
    logger.info("═══════════════════════════════════════════")

    # Connect
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")
    if not sheet_id or not Path(creds_path).exists():
        logger.error("Missing GOOGLE_SHEET_ID or credentials file")
        sys.exit(1)

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)

    # ── Step 1: Read Daily Mix tab ──
    logger.info("\n1. Reading Daily Mix tab...")
    try:
        mix_ws = spreadsheet.worksheet(DAILY_MIX_TAB)
    except gspread.exceptions.WorksheetNotFound:
        logger.info("   Daily Mix tab not found. Nothing to escalate.")
        return

    mix_data = mix_ws.get_all_values()
    if len(mix_data) < 2:
        logger.info("   Daily Mix is empty. Nothing to escalate.")
        return

    mix_headers = mix_data[0]

    def col_idx(headers, name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    status_idx = col_idx(mix_headers, "status")
    email_idx = col_idx(mix_headers, "email")
    phone_idx = col_idx(mix_headers, "phone")

    if status_idx == -1:
        logger.error("   'status' column not found in Daily Mix")
        return

    # Find leads ready for email escalation
    escalation_candidates = []
    for row in mix_data[1:]:
        def cell(idx):
            if idx < 0 or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        status = cell(status_idx).lower()
        email = cell(email_idx) if email_idx >= 0 else ""

        # Must be contacted/call_routed AND have a valid email
        if status not in ESCALATION_STATUSES:
            continue
        if not has_valid_email(email):
            continue

        # Build lead dict with all columns
        lead = {}
        for i, h in enumerate(mix_headers):
            lead[h] = cell(i)

        escalation_candidates.append(lead)

    logger.info(f"   Found {len(escalation_candidates)} leads ready for email escalation")
    logger.info(f"   (status = 'contacted' or 'call_routed' AND has valid email)")

    if not escalation_candidates:
        logger.info("   Nothing to escalate. WhatsApp leads either have no email or are not yet contacted.")
        return

    # ── Step 2: Read existing Email Queue for dedup ──
    logger.info("\n2. Reading Email Queue for dedup...")
    try:
        eq_ws = spreadsheet.worksheet(EMAIL_QUEUE_TAB)
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"   Creating '{EMAIL_QUEUE_TAB}' tab...")
        eq_ws = spreadsheet.add_worksheet(title=EMAIL_QUEUE_TAB, rows=500, cols=25)

    existing_keys = set()
    existing_rows = []
    eq_existing_headers = []

    try:
        eq_data = eq_ws.get_all_values()
        if len(eq_data) >= 2:
            eq_existing_headers = eq_data[0]
            for row in eq_data[1:]:
                row_dict = {}
                for i, h in enumerate(eq_existing_headers):
                    row_dict[h] = row[i] if i < len(row) else ""

                email_val = row_dict.get("email", "").strip().lower()
                phone_val = row_dict.get("phone", "").strip()
                dedup_key = f"{email_val}|{phone_val}"

                if dedup_key not in existing_keys:
                    existing_keys.add(dedup_key)
                    existing_rows.append(row_dict)
    except Exception as e:
        logger.warning(f"   Could not read Email Queue: {e}")

    logger.info(f"   Existing Email Queue leads: {len(existing_rows)}")

    # ── Step 3: Add new leads (dedup) ──
    new_count = 0
    for lead in escalation_candidates:
        email = lead.get("email", "").strip().lower()
        phone = lead.get("phone", "").strip()
        dedup_key = f"{email}|{phone}"

        if dedup_key in existing_keys:
            continue  # Already in Email Queue

        existing_keys.add(dedup_key)

        # Build Email Queue entry
        new_lead = dict(lead)
        new_lead["status"] = "New"  # Reset status so n8n picks it up
        new_lead["has_website"] = "YES" if is_real_website(lead.get("website", "")) else "NO"
        new_lead.setdefault("email_sent_date", "")
        new_lead.setdefault("follow_up_count", "")
        new_lead.setdefault("last_follow_up_date", "")
        new_lead.setdefault("gmail_account_index", "")
        new_lead.setdefault("email_subject", "")
        new_lead.setdefault("master_row", lead.get("master_row", ""))

        existing_rows.append(new_lead)
        new_count += 1

    logger.info(f"\n3. Escalation results:")
    logger.info(f"   Already in Email Queue: {len(escalation_candidates) - new_count}")
    logger.info(f"   NEW leads to escalate:  {new_count}")

    if new_count == 0:
        logger.info("   All eligible leads already in Email Queue. Nothing to do.")
        return

    if args.dry_run:
        logger.info("\n   DRY RUN — no changes written.")
        for lead in existing_rows[-min(new_count, 10):]:
            name = lead.get("business_name", "?")[:30]
            email = lead.get("email", "?")
            logger.info(f"     {name:30s} → {email}")
        if new_count > 10:
            logger.info(f"     ... and {new_count - 10} more")
        return

    # ── Step 4: Write updated Email Queue ──
    # Build headers (use existing Email Queue headers or master headers)
    if eq_existing_headers:
        write_headers = list(eq_existing_headers)
    else:
        write_headers = list(mix_headers)

    extra_cols = [
        "master_row", "row_number", "email_sent_date", "follow_up_count",
        "last_follow_up_date", "gmail_account_index", "email_subject", "has_website",
    ]
    for col in extra_cols:
        if col not in write_headers:
            write_headers.append(col)

    logger.info(f"\n4. Writing {len(existing_rows)} leads to Email Queue...")
    all_sheet_rows = [write_headers]
    for i, lead in enumerate(existing_rows):
        row = []
        for h in write_headers:
            if h == "row_number":
                row.append(str(i + 2))
            else:
                row.append(lead.get(h, ""))
        all_sheet_rows.append(row)

    eq_ws.clear()
    eq_ws.update(values=all_sheet_rows, range_name="A1")

    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info("  ESCALATION COMPLETE")
    logger.info(f"  WhatsApp leads with email: {len(escalation_candidates)}")
    logger.info(f"  Already in Email Queue:    {len(escalation_candidates) - new_count}")
    logger.info(f"  NEW leads escalated:       {new_count}")
    logger.info(f"  Total Email Queue:         {len(existing_rows)}")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
