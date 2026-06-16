"""
Lead Mixer — Round-Robin Daily Batch Generator
================================================
Reads all "New" leads from master Google Sheet, mixes them by
category + city using round-robin rotation, and writes daily
batches to THREE tabs:

  - "Daily Mix" tab   → leads with phone (for WhatsApp/SMS outreach via n8n)
  - "Email Queue" tab  → leads with email (for automated email outreach via n8n)
  - "Call Queue" tab   → leads for cold calling (EXCLUSIVE — no WhatsApp)

Call Queue leads are EXCLUDED from Daily Mix to prevent double-outreach.
The n8n WhatsApp workflow reads from "Daily Mix" tab.
The n8n Email workflow reads from "Email Queue" tab.
The n8n Cold Call workflow reads from "Call Queue" tab.

Usage:
    python processor/lead_mixer.py                    # Default: 50 WA + 200 email + 10 call
    python processor/lead_mixer.py --batch-size 30    # Custom WA batch size
    python processor/lead_mixer.py --email-batch 150  # Custom email batch size
    python processor/lead_mixer.py --call-batch 15    # Custom call batch size
    python processor/lead_mixer.py --dry-run           # Preview without writing
    python processor/lead_mixer.py --reset             # Clear all tabs
"""

import os
import sys
import re
import logging
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from itertools import cycle

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# Fix Windows terminal Unicode
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
CALL_QUEUE_TAB = "Call Queue"
DEFAULT_BATCH_SIZE = 50
DEFAULT_EMAIL_BATCH = 200
DEFAULT_CALL_BATCH = 10


def normalize_phone_for_sort(phone_str) -> str:
    """Strip to digits for sorting (phone-first priority)."""
    if not phone_str:
        return ""
    return re.sub(r"[^\d]", "", str(phone_str).strip())


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


def get_sheet_client():
    """Authenticate and return gspread client + spreadsheet."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")

    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID not set in .env")
        sys.exit(1)
    if not Path(creds_path).exists():
        logger.error(f"Credentials not found: {creds_path}")
        sys.exit(1)

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)
    return spreadsheet


def ensure_tab(spreadsheet, tab_name):
    """Create a tab if it doesn't exist. Return the worksheet."""
    try:
        ws = spreadsheet.worksheet(tab_name)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"Creating '{tab_name}' tab...")
        ws = spreadsheet.add_worksheet(title=tab_name, rows=300, cols=20)
        return ws


def read_new_leads(master_sheet) -> tuple[list[dict], list[str]]:
    """Read all rows from master sheet where status = 'New'.

    Returns:
        (list of lead dicts, list of header column names)
    """
    all_data = master_sheet.get_all_values()
    if len(all_data) < 2:
        return [], []

    headers = all_data[0]
    data_rows = all_data[1:]

    # Find column indices
    def col_idx(name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    status_idx = col_idx("status")
    phone_idx = col_idx("phone")
    email_idx = col_idx("email")
    category_idx = col_idx("category")
    city_idx = col_idx("city")
    name_idx = col_idx("business_name")
    search_keyword_idx = col_idx("search_keyword")

    if status_idx == -1:
        logger.error("'status' column not found in master sheet")
        return [], headers

    leads = []
    for row_num, row in enumerate(data_rows, start=2):
        def cell(idx):
            if idx < 0 or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        status = cell(status_idx).lower()
        if status not in ("new", ""):
            continue

        # Build lead dict from all columns
        lead = {}
        for i, header in enumerate(headers):
            lead[header] = cell(i) if i < len(row) else ""

        # Add row_number for "Mark as Contacted" matching
        lead["row_number"] = str(row_num)

        # Add sort key: has phone = priority
        phone = cell(phone_idx)
        lead["_has_phone"] = bool(phone and len(normalize_phone_for_sort(phone)) >= 10)

        # Check if has valid email
        email = cell(email_idx) if email_idx >= 0 else ""
        lead["_has_email"] = has_valid_email(email)

        # Determine the bucket key (category + city)
        category = cell(category_idx)
        search_keyword = cell(search_keyword_idx) if search_keyword_idx >= 0 else ""
        city = cell(city_idx)

        if not category or category.lower() in ("restaurant", "business", ""):
            category = search_keyword if search_keyword else "other"

        lead["_bucket_key"] = f"{category.lower().strip()}|{city.lower().strip()}"

        leads.append(lead)

    return leads, headers


def round_robin_mix(leads: list[dict], batch_size: int) -> list[dict]:
    """Round-robin mix leads across category+city buckets.

    Within each bucket, leads with phone numbers come first.
    Picks 1 from each bucket in rotation until batch_size is reached.
    """
    if not leads:
        return []

    # Group into buckets
    buckets = defaultdict(list)
    for lead in leads:
        buckets[lead["_bucket_key"]].append(lead)

    # Sort within each bucket: phone-first
    for key in buckets:
        buckets[key].sort(key=lambda x: (not x["_has_phone"], x.get("business_name", "")))

    logger.info(f"  Buckets created: {len(buckets)}")
    for key, bucket_leads in sorted(buckets.items(), key=lambda x: -len(x[1]))[:10]:
        parts = key.split("|")
        cat = parts[0] if len(parts) > 0 else "?"
        city = parts[1] if len(parts) > 1 else "?"
        logger.info(f"    {cat:25s} | {city:15s} -> {len(bucket_leads)} leads")
    if len(buckets) > 10:
        logger.info(f"    ... and {len(buckets) - 10} more buckets")

    # Round-robin pick
    mixed = []
    bucket_iters = {key: iter(leads_list) for key, leads_list in buckets.items()}
    active_keys = list(buckets.keys())
    key_cycle = cycle(active_keys)
    exhausted_keys = set()

    while len(mixed) < batch_size and len(exhausted_keys) < len(active_keys):
        key = next(key_cycle)

        if key in exhausted_keys:
            continue

        try:
            lead = next(bucket_iters[key])
            mixed.append(lead)
        except StopIteration:
            exhausted_keys.add(key)

    return mixed


def write_to_tab(ws, tab_name, leads: list[dict], headers: list[str]):
    """APPEND new leads to tab, keeping existing unprocessed leads.

    - Reads existing rows from the tab
    - Keeps rows where status is still 'New' (not yet processed by n8n)
    - Removes rows already processed (emailed, contacted, replied, etc.)
    - Deduplicates by email/phone so no lead appears twice
    - Appends new leads after existing unprocessed ones
    - Reassigns sequential row_numbers to match actual sheet positions

    row_number = sequential sheet position (2, 3, 4...)
    master_row = original master sheet row for back-tracking
    """
    write_headers = list(headers)

    # Ensure essential columns exist in headers
    for col in ["master_row", "row_number", "email_sent_date", "follow_up_count",
                 "last_follow_up_date", "gmail_account_index", "email_subject", "has_website"]:
        if col not in write_headers:
            write_headers.append(col)

    # ── Step 1: Read existing rows from the tab ──
    existing_leads = []
    seen_keys = set()  # Track email+phone to prevent duplicates

    try:
        existing_data = ws.get_all_values()
        if len(existing_data) >= 2:
            existing_headers = existing_data[0]
            for row in existing_data[1:]:
                lead_dict = {}
                for i, h in enumerate(existing_headers):
                    lead_dict[h] = row[i] if i < len(row) else ""

                # Keep ALL leads regardless of status
                # n8n tracks emailed/replied/bounced leads in this tab
                # We only deduplicate, never drop by status

                # Build dedup key from email and phone
                email = lead_dict.get("email", "").strip().lower()
                phone = lead_dict.get("phone", "").strip()
                dedup_key = f"{email}|{phone}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                existing_leads.append(lead_dict)
    except Exception as e:
        logger.warning(f"  Could not read existing '{tab_name}' data: {e}")
        logger.info(f"  Starting with empty tab")

    logger.info(f"  Existing unprocessed leads in '{tab_name}': {len(existing_leads)}")

    # ── Step 2: Filter new leads (skip duplicates) ──
    new_leads_added = 0
    for lead in leads:
        email = lead.get("email", "").strip().lower()
        phone = lead.get("phone", "").strip()
        dedup_key = f"{email}|{phone}"

        if dedup_key in seen_keys:
            continue  # Already in the tab
        seen_keys.add(dedup_key)

        existing_leads.append(lead)
        new_leads_added += 1

    # ── Step 3: Build rows with sequential row_numbers ──
    all_combined = existing_leads
    rows = []
    for i, lead in enumerate(all_combined):
        row = []
        for h in write_headers:
            if h == "row_number":
                # Sequential row number = actual sheet row (header is row 1)
                row.append(str(i + 2))
            elif h == "master_row":
                # Original master sheet row number for back-tracking
                row.append(lead.get("row_number", lead.get("master_row", "")))
            else:
                row.append(lead.get(h, ""))
        rows.append(row)

    # ── Step 4: Clear and rewrite (with existing + new combined) ──
    ws.clear()
    all_data = [write_headers] + rows
    ws.update("A1", all_data)

    logger.info(f"  Kept {len(existing_leads) - new_leads_added} existing unprocessed leads")
    logger.info(f"  Added {new_leads_added} new leads")
    logger.info(f"  Total in '{tab_name}': {len(rows)} leads (rows 2-{len(rows) + 1})")


def mark_as_queued(master_sheet, leads: list[dict], headers: list[str]):
    """Update status to 'Queued' for selected leads in master sheet."""
    status_idx = headers.index("status") if "status" in headers else -1
    if status_idx < 0:
        logger.warning("Cannot mark as Queued — 'status' column not found")
        return

    col_letter = chr(65 + status_idx) if status_idx < 26 else None
    if not col_letter:
        logger.warning("Status column index too high, skipping batch update")
        return

    cells_to_update = []
    for lead in leads:
        row_num = lead.get("row_number", "")
        if row_num:
            cells_to_update.append({
                "range": f"{col_letter}{row_num}",
                "values": [["Queued"]]
            })

    if cells_to_update:
        for i in range(0, len(cells_to_update), 50):
            batch = cells_to_update[i:i + 50]
            master_sheet.batch_update(batch)
            logger.info(f"  Marked batch {i // 50 + 1}: {len(batch)} leads as 'Queued'")

        import time
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Lead Mixer — Round-Robin Daily Batch")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"WhatsApp batch size (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--email-batch", type=int, default=DEFAULT_EMAIL_BATCH,
                        help=f"Email batch size (default: {DEFAULT_EMAIL_BATCH})")
    parser.add_argument("--call-batch", type=int, default=DEFAULT_CALL_BATCH,
                        help=f"Cold call batch size (default: {DEFAULT_CALL_BATCH})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the batch without writing to sheet")
    parser.add_argument("--reset", action="store_true",
                        help="Clear Daily Mix, Email Queue, and Call Queue tabs and exit")
    args = parser.parse_args()

    logger.info("===========================================")
    logger.info("  LEAD MIXER — Triple-Queue Daily Batch")
    logger.info(f"  WhatsApp batch:  {args.batch_size}")
    logger.info(f"  Email batch:     {args.email_batch}")
    logger.info(f"  Call batch:      {args.call_batch}")
    logger.info(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("===========================================")

    # Connect to Google Sheets
    spreadsheet = get_sheet_client()
    master_sheet = spreadsheet.sheet1
    mix_ws = ensure_tab(spreadsheet, DAILY_MIX_TAB)
    email_ws = ensure_tab(spreadsheet, EMAIL_QUEUE_TAB)
    call_ws = ensure_tab(spreadsheet, CALL_QUEUE_TAB)

    if args.reset:
        mix_ws.clear()
        email_ws.clear()
        call_ws.clear()
        logger.info("Daily Mix, Email Queue, and Call Queue tabs cleared.")
        return

    # Step 1: Read all "New" leads
    logger.info("\n1. Reading master sheet...")
    leads, headers = read_new_leads(master_sheet)
    logger.info(f"   Found {len(leads)} leads with status 'New'")

    if not leads:
        logger.warning("No new leads available. Scrape more or check master sheet statuses.")
        return

    # Separate leads by channel
    phone_only_leads = []  # Has phone but no email → WhatsApp/SMS + Call
    email_leads = []       # Has email → Email outreach
    both_leads = []        # Has both → Email (email first strategy)

    for lead in leads:
        has_phone = lead["_has_phone"]
        has_email = lead["_has_email"]

        if has_email:
            # If has email, prioritize email channel (even if has phone)
            email_leads.append(lead)
        elif has_phone:
            phone_only_leads.append(lead)
        # Skip leads with neither phone nor email

    logger.info(f"   Phone only (WA/SMS + Call): {len(phone_only_leads)}")
    logger.info(f"   Has email (Email):          {len(email_leads)}")
    logger.info(f"   No phone or email:          {len(leads) - len(phone_only_leads) - len(email_leads)}")

    # ── Step 2: Round-robin mix for CALL QUEUE (exclusive, picked first) ──
    logger.info(f"\n2. Mixing Call leads (batch={args.call_batch})...")
    call_mixed = round_robin_mix(phone_only_leads, args.call_batch)
    logger.info(f"   Call batch: {len(call_mixed)} leads")

    # Remove call leads from phone pool so they don't also get WhatsApp
    call_lead_ids = set()
    for lead in call_mixed:
        # Use phone + business_name as unique key
        phone = lead.get("phone", "").strip()
        name = lead.get("business_name", "").strip()
        call_lead_ids.add(f"{phone}|{name}")

    wa_eligible_leads = []
    for lead in phone_only_leads:
        phone = lead.get("phone", "").strip()
        name = lead.get("business_name", "").strip()
        key = f"{phone}|{name}"
        if key not in call_lead_ids:
            wa_eligible_leads.append(lead)

    logger.info(f"   After excluding call leads: {len(wa_eligible_leads)} phone leads for WhatsApp/SMS")

    # ── Step 3: Round-robin mix for WhatsApp queue (from remaining phone leads) ──
    logger.info(f"\n3. Mixing WhatsApp/SMS leads (batch={args.batch_size})...")
    wa_mixed = round_robin_mix(wa_eligible_leads, args.batch_size)
    logger.info(f"   WhatsApp/SMS batch: {len(wa_mixed)} leads")

    # ── Step 4: Round-robin mix for Email queue ──
    logger.info(f"\n4. Mixing Email leads (batch={args.email_batch})...")
    email_mixed = round_robin_mix(email_leads, args.email_batch)
    logger.info(f"   Email batch: {len(email_mixed)} leads")

    # Print distribution
    for label, mixed in [("Call", call_mixed), ("WhatsApp/SMS", wa_mixed), ("Email", email_mixed)]:
        if mixed:
            cat_counts = defaultdict(int)
            city_counts = defaultdict(int)
            for lead in mixed:
                cat_counts[lead.get("category", lead.get("search_keyword", "other"))] += 1
                city_counts[lead.get("city", "unknown")] += 1
            logger.info(f"\n   {label} — Category distribution:")
            for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1])[:8]:
                logger.info(f"     {cat}: {count}")
            logger.info(f"   {label} — City distribution:")
            for city, count in sorted(city_counts.items(), key=lambda x: -x[1])[:8]:
                logger.info(f"     {city}: {count}")

    if args.dry_run:
        logger.info("\n   DRY RUN — no changes written to sheet.")
        return

    # ── Step 5: Write to tabs ──
    all_mixed = call_mixed + wa_mixed + email_mixed

    if call_mixed:
        logger.info(f"\n5a. Writing to '{CALL_QUEUE_TAB}' tab...")
        clean_call = []
        for lead in call_mixed:
            clean = {k: v for k, v in lead.items() if not k.startswith("_")}
            clean["status"] = "New"
            clean_call.append(clean)
        write_to_tab(call_ws, CALL_QUEUE_TAB, clean_call, headers)

    if wa_mixed:
        logger.info(f"\n5b. Writing to '{DAILY_MIX_TAB}' tab...")
        clean_wa = []
        for lead in wa_mixed:
            clean = {k: v for k, v in lead.items() if not k.startswith("_")}
            clean["status"] = "New"
            clean_wa.append(clean)
        write_to_tab(mix_ws, DAILY_MIX_TAB, clean_wa, headers)

    if email_mixed:
        logger.info(f"\n5c. Writing to '{EMAIL_QUEUE_TAB}' tab...")
        clean_email = []
        for lead in email_mixed:
            clean = {k: v for k, v in lead.items() if not k.startswith("_")}
            clean["status"] = "New"
            clean_email.append(clean)
        write_to_tab(email_ws, EMAIL_QUEUE_TAB, clean_email, headers)

    # Step 6: Mark as Queued in master sheet
    logger.info("\n6. Marking leads as 'Queued' in master sheet...")
    mark_as_queued(master_sheet, all_mixed, headers)

    # Summary
    logger.info("")
    logger.info("===========================================")
    logger.info("  MIXER COMPLETE")
    logger.info(f"  Call queue:       {len(call_mixed)} leads -> '{CALL_QUEUE_TAB}'")
    logger.info(f"  WhatsApp queue:   {len(wa_mixed)} leads -> '{DAILY_MIX_TAB}'")
    logger.info(f"  Email queue:      {len(email_mixed)} leads -> '{EMAIL_QUEUE_TAB}'")
    logger.info(f"  Total queued:     {len(all_mixed)} leads")
    logger.info(f"  Master status:    {len(all_mixed)} leads -> 'Queued'")
    logger.info("===========================================")


if __name__ == "__main__":
    main()
