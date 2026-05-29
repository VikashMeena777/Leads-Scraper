"""
Lead Mixer — Round-Robin Daily Batch Generator
================================================
Reads all "New" leads from master Google Sheet, mixes them by
category + city using round-robin rotation, and writes a daily
batch to the "Daily Mix" tab in the same sheet.

The n8n WhatsApp Outreach workflow reads from "Daily Mix" tab
instead of the master sheet, ensuring varied outreach every day.

Usage:
    python processor/lead_mixer.py                    # Default: 50 leads
    python processor/lead_mixer.py --batch-size 30    # Custom batch size
    python processor/lead_mixer.py --dry-run           # Preview without writing
    python processor/lead_mixer.py --reset             # Clear Daily Mix tab
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
DEFAULT_BATCH_SIZE = 50


def normalize_phone_for_sort(phone_str) -> str:
    """Strip to digits for sorting (phone-first priority)."""
    if not phone_str:
        return ""
    return re.sub(r"[^\d]", "", str(phone_str).strip())


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


def ensure_daily_mix_tab(spreadsheet):
    """Create the 'Daily Mix' tab if it doesn't exist. Return the worksheet."""
    try:
        ws = spreadsheet.worksheet(DAILY_MIX_TAB)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"Creating '{DAILY_MIX_TAB}' tab...")
        ws = spreadsheet.add_worksheet(title=DAILY_MIX_TAB, rows=100, cols=20)
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
    category_idx = col_idx("category")
    city_idx = col_idx("city")
    name_idx = col_idx("business_name")
    search_keyword_idx = col_idx("search_keyword")

    if status_idx == -1:
        logger.error("'status' column not found in master sheet")
        return [], headers

    leads = []
    for row_num, row in enumerate(data_rows, start=2):  # row_num = sheet row (1-indexed, +1 for header)
        # Safely get cell value
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

        # Determine the bucket key (category + city)
        # Use search_keyword as fallback for category (Google Maps category can be vague)
        category = cell(category_idx)
        search_keyword = cell(search_keyword_idx) if search_keyword_idx >= 0 else ""
        city = cell(city_idx)

        # Normalize category: use search_keyword if category is too generic or empty
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
        logger.info(f"    {cat:25s} | {city:15s} → {len(bucket_leads)} leads")
    if len(buckets) > 10:
        logger.info(f"    ... and {len(buckets) - 10} more buckets")

    # Round-robin pick
    mixed = []
    # Create iterators for each bucket
    bucket_iters = {key: iter(leads_list) for key, leads_list in buckets.items()}
    # Cycle through bucket keys
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


def write_to_daily_mix(mix_ws, leads: list[dict], headers: list[str]):
    """Clear the Daily Mix tab and write the mixed batch."""
    # Determine columns to write (same as master sheet + row_number)
    write_headers = list(headers)
    if "row_number" not in write_headers:
        write_headers.append("row_number")

    # Build rows
    rows = []
    for lead in leads:
        row = []
        for h in write_headers:
            val = lead.get(h, "")
            row.append(val)
        rows.append(row)

    # Clear entire tab
    mix_ws.clear()

    # Write headers + data
    all_data = [write_headers] + rows
    mix_ws.update(f"A1", all_data)

    logger.info(f"  Written {len(rows)} leads to '{DAILY_MIX_TAB}' tab")


def mark_as_queued(master_sheet, leads: list[dict], headers: list[str]):
    """Update status to 'Queued' for selected leads in master sheet."""
    status_idx = headers.index("status") if "status" in headers else -1
    if status_idx < 0:
        logger.warning("Cannot mark as Queued — 'status' column not found")
        return

    # Batch update: collect all cells to update
    cells_to_update = []
    col_letter = chr(65 + status_idx) if status_idx < 26 else None
    if not col_letter:
        logger.warning("Status column index too high, skipping batch update")
        return

    for lead in leads:
        row_num = lead.get("row_number", "")
        if row_num:
            cells_to_update.append({
                "range": f"{col_letter}{row_num}",
                "values": [["Queued"]]
            })

    if cells_to_update:
        # Batch update in chunks of 50
        for i in range(0, len(cells_to_update), 50):
            batch = cells_to_update[i:i + 50]
            master_sheet.batch_update(batch)
            logger.info(f"  Marked batch {i // 50 + 1}: {len(batch)} leads as 'Queued'")

        import time
        time.sleep(1)  # Rate limit


def main():
    parser = argparse.ArgumentParser(description="Lead Mixer — Round-Robin Daily Batch")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Number of leads per daily batch (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the batch without writing to sheet")
    parser.add_argument("--reset", action="store_true",
                        help="Clear the Daily Mix tab and exit")
    args = parser.parse_args()

    logger.info("═══════════════════════════════════════════")
    logger.info("  LEAD MIXER — Round-Robin Daily Batch")
    logger.info(f"  Batch size: {args.batch_size}")
    logger.info(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("═══════════════════════════════════════════")

    # Connect to Google Sheets
    spreadsheet = get_sheet_client()
    master_sheet = spreadsheet.sheet1
    mix_ws = ensure_daily_mix_tab(spreadsheet)

    if args.reset:
        mix_ws.clear()
        logger.info("Daily Mix tab cleared.")
        return

    # Step 1: Read all "New" leads from master sheet
    logger.info("\n1. Reading master sheet...")
    leads, headers = read_new_leads(master_sheet)
    logger.info(f"   Found {len(leads)} leads with status 'New'")

    if not leads:
        logger.warning("No new leads available. Scrape more or check master sheet statuses.")
        return

    # Count leads with phone
    phone_count = sum(1 for l in leads if l["_has_phone"])
    logger.info(f"   With phone number: {phone_count}")
    logger.info(f"   Without phone: {len(leads) - phone_count}")

    # Step 2: Round-robin mix
    logger.info(f"\n2. Mixing leads (round-robin, batch={args.batch_size})...")
    mixed = round_robin_mix(leads, args.batch_size)
    logger.info(f"   Mixed batch: {len(mixed)} leads")

    # Print preview
    logger.info("\n3. Batch preview:")
    logger.info(f"   {'#':>3}  {'Category':25s}  {'City':15s}  {'Business':35s}  {'Phone':5s}")
    logger.info(f"   {'—' * 90}")
    for i, lead in enumerate(mixed, 1):
        cat = lead.get("category", lead.get("search_keyword", "?"))[:25]
        city = lead.get("city", "?")[:15]
        name = lead.get("business_name", "?")[:35]
        has_ph = "Yes" if lead["_has_phone"] else "No"
        logger.info(f"   {i:>3}  {cat:25s}  {city:15s}  {name:35s}  {has_ph:5s}")

    # Category distribution
    cat_counts = defaultdict(int)
    city_counts = defaultdict(int)
    for lead in mixed:
        cat_counts[lead.get("category", lead.get("search_keyword", "other"))] += 1
        city_counts[lead.get("city", "unknown")] += 1

    logger.info(f"\n   Category distribution:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        logger.info(f"     {cat}: {count}")
    logger.info(f"\n   City distribution:")
    for city, count in sorted(city_counts.items(), key=lambda x: -x[1]):
        logger.info(f"     {city}: {count}")

    if args.dry_run:
        logger.info("\n   DRY RUN — no changes written to sheet.")
        return

    # Step 3: Write to Daily Mix tab
    logger.info(f"\n4. Writing to '{DAILY_MIX_TAB}' tab...")
    # Remove internal keys before writing
    clean_mixed = []
    for lead in mixed:
        clean = {k: v for k, v in lead.items() if not k.startswith("_")}
        # Set status to "New" in Daily Mix so n8n's filter picks them up
        clean["status"] = "New"
        clean_mixed.append(clean)

    write_to_daily_mix(mix_ws, clean_mixed, headers)

    # Step 4: Mark as Queued in master sheet
    logger.info("\n5. Marking leads as 'Queued' in master sheet...")
    mark_as_queued(master_sheet, mixed, headers)

    # Summary
    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info("  MIXER COMPLETE")
    logger.info(f"  Leads mixed:      {len(mixed)}")
    logger.info(f"  Categories:       {len(cat_counts)}")
    logger.info(f"  Cities:           {len(city_counts)}")
    logger.info(f"  Written to:       '{DAILY_MIX_TAB}' tab")
    logger.info(f"  Master status:    {len(mixed)} leads → 'Queued'")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
