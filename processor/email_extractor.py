"""
Email Extractor
================
Visits business websites from the master Google Sheet and extracts
email addresses from the page content, mailto: links, and common
contact pages (/contact, /about, etc.).

Updates the 'email' column in the master sheet with found emails.

Usage:
    python processor/email_extractor.py                    # Process all leads without email
    python processor/email_extractor.py --limit 100        # Process only 100 leads
    python processor/email_extractor.py --dry-run           # Preview without updating sheet
    python processor/email_extractor.py --city Jaipur       # Only Jaipur leads
"""

import os
import sys
import re
import time
import random
import logging
import argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4 lxml")
    sys.exit(1)

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

# ─── Email Validation ────────────────────────────────────
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

# Emails to skip (generic / useless for outreach)
SKIP_EMAIL_PATTERNS = [
    r"^noreply@",
    r"^no-reply@",
    r"^donotreply@",
    r"^support@",
    r"^help@",
    r"^abuse@",
    r"^postmaster@",
    r"^webmaster@",
    r"^mailer-daemon@",
    r"^admin@(?:google|facebook|instagram|twitter)",
    r"@example\.",
    r"@sentry\.",
    r"@wixpress\.",
    r"@test\.",
    r"\.png$",
    r"\.jpg$",
    r"\.gif$",
    r"\.svg$",
]

# Domains that are not business email providers
SKIP_EMAIL_DOMAINS = {
    "example.com", "test.com", "sentry.io", "wixpress.com",
    "w3.org", "schema.org", "googleapis.com", "googleusercontent.com",
    "facebook.com", "instagram.com", "twitter.com", "youtube.com",
    "wordpress.com", "wordpress.org", "squarespace.com",
    "wix.com", "godaddy.com", "hostgator.com", "bluehost.com",
}

# Social media / not real website URLs (reuse from mixer)
NOT_WEBSITE = [
    "instagram.com", "facebook.com", "fb.com", "wa.me",
    "api.whatsapp.com", "whatsapp.com", "youtube.com", "youtu.be",
    "twitter.com", "x.com", "linkedin.com", "tiktok.com",
    "linktr.ee", "linktree.com", "bit.ly", "g.page",
    "maps.google.com", "goo.gl", "maps.app.goo.gl",
    "zomato.com", "swiggy.com", "justdial.com",
    "play.google.com", "apps.apple.com",
]

# Contact page paths to check
CONTACT_PATHS = [
    "/contact", "/contact-us", "/contactus", "/contact.html",
    "/about", "/about-us", "/aboutus", "/about.html",
    "/reach-us", "/get-in-touch",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def is_real_website(url: str) -> bool:
    """Check if URL is a real business website (not social media)."""
    if not url or url.strip() in ("", "None", "none", "N/A"):
        return False
    lower = url.lower().strip()
    if len(lower) < 5:
        return False
    for pattern in NOT_WEBSITE:
        if pattern in lower:
            return False
    return True


def validate_email(email: str) -> bool:
    """Validate that an email is useful for outreach."""
    email = email.strip().lower()

    # Basic format check
    if not EMAIL_REGEX.fullmatch(email):
        return False

    # Check length
    if len(email) < 6 or len(email) > 254:
        return False

    # Check skip patterns
    for pattern in SKIP_EMAIL_PATTERNS:
        if re.search(pattern, email, re.IGNORECASE):
            return False

    # Check skip domains
    domain = email.split("@")[1] if "@" in email else ""
    if domain in SKIP_EMAIL_DOMAINS:
        return False

    # Must have valid TLD
    tld = domain.split(".")[-1] if "." in domain else ""
    if len(tld) < 2:
        return False

    return True


def extract_emails_from_html(html: str) -> set:
    """Extract email addresses from raw HTML content."""
    found = set()

    # Method 1: Regex on raw HTML
    raw_emails = EMAIL_REGEX.findall(html)
    for e in raw_emails:
        if validate_email(e):
            found.add(e.strip().lower())

    # Method 2: Parse with BeautifulSoup for mailto: links
    try:
        soup = BeautifulSoup(html, "lxml")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href.startswith("mailto:"):
                email = href.replace("mailto:", "").split("?")[0].strip()
                if validate_email(email):
                    found.add(email.lower())
    except Exception:
        pass

    return found


def scrape_website_emails(page, base_url: str) -> list[str]:
    """Visit a website and extract emails from main page + contact pages."""
    all_emails = set()

    # Normalize URL
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url

    # Visit main page
    try:
        page.goto(base_url, timeout=15000, wait_until="domcontentloaded")
        time.sleep(1)
        html = page.content()
        emails = extract_emails_from_html(html)
        all_emails.update(emails)
    except Exception as e:
        logger.debug(f"    Failed to load {base_url}: {e}")
        # Try with http if https fails
        if base_url.startswith("https://"):
            try:
                http_url = base_url.replace("https://", "http://")
                page.goto(http_url, timeout=10000, wait_until="domcontentloaded")
                time.sleep(1)
                html = page.content()
                emails = extract_emails_from_html(html)
                all_emails.update(emails)
            except Exception:
                return list(all_emails)

    # If no email found on main page, check contact/about pages
    if not all_emails:
        for path in CONTACT_PATHS:
            try:
                contact_url = urljoin(base_url, path)
                page.goto(contact_url, timeout=10000, wait_until="domcontentloaded")
                time.sleep(0.5)

                # Check if page actually loaded (not 404)
                if page.title() and "404" not in page.title().lower():
                    html = page.content()
                    emails = extract_emails_from_html(html)
                    all_emails.update(emails)

                    if all_emails:
                        break  # Found email, stop checking more pages
            except Exception:
                continue

    return list(all_emails)


def append_to_email_queue(spreadsheet, updates, leads_by_row, headers):
    """Directly append leads with found emails to Email Queue tab.

    This ensures emails discovered by the extractor immediately become
    available for the n8n email outreach workflow, without waiting for
    the daily mixer (which may have already marked them as 'Queued').

    Returns:
        int: Number of new leads added to Email Queue
    """
    EMAIL_QUEUE_TAB = "Email Queue"

    # Ensure tab exists
    try:
        eq_ws = spreadsheet.worksheet(EMAIL_QUEUE_TAB)
    except gspread.exceptions.WorksheetNotFound:
        logger.info(f"  Creating '{EMAIL_QUEUE_TAB}' tab...")
        eq_ws = spreadsheet.add_worksheet(title=EMAIL_QUEUE_TAB, rows=500, cols=25)

    # Build Email Queue headers (master headers + extra tracking columns)
    eq_headers = list(headers)
    extra_cols = [
        "master_row", "row_number", "email_sent_date", "follow_up_count",
        "last_follow_up_date", "gmail_account_index", "email_subject", "has_website",
    ]
    for col in extra_cols:
        if col not in eq_headers:
            eq_headers.append(col)

    # Read existing Email Queue for dedup
    existing_keys = set()
    existing_rows = []
    try:
        eq_data = eq_ws.get_all_values()
        if len(eq_data) >= 2:
            existing_eq_headers = eq_data[0]
            for row in eq_data[1:]:
                row_dict = {}
                for i, h in enumerate(existing_eq_headers):
                    row_dict[h] = row[i] if i < len(row) else ""

                email_val = row_dict.get("email", "").strip().lower()
                phone_val = row_dict.get("phone", "").strip()
                dedup_key = f"{email_val}|{phone_val}"

                if dedup_key not in existing_keys:
                    existing_keys.add(dedup_key)
                    existing_rows.append(row_dict)
    except Exception as e:
        logger.warning(f"  Could not read Email Queue: {e}")

    logger.info(f"  Existing Email Queue leads: {len(existing_rows)}")

    # Add new leads with found emails
    new_count = 0
    for row_num, found_email in updates:
        lead_data = leads_by_row.get(row_num)
        if not lead_data:
            continue

        all_data = lead_data.get("all_data", {})
        phone = all_data.get("phone", "").strip()
        dedup_key = f"{found_email.lower()}|{phone}"

        if dedup_key in existing_keys:
            continue  # Already in Email Queue

        existing_keys.add(dedup_key)

        # Build the Email Queue entry with all master sheet columns
        new_lead = dict(all_data)
        new_lead["email"] = found_email
        new_lead["status"] = "New"
        new_lead["master_row"] = str(row_num)
        new_lead["has_website"] = "YES" if is_real_website(all_data.get("website", "")) else "NO"
        new_lead.setdefault("email_sent_date", "")
        new_lead.setdefault("follow_up_count", "")
        new_lead.setdefault("last_follow_up_date", "")
        new_lead.setdefault("gmail_account_index", "")
        new_lead.setdefault("email_subject", "")

        existing_rows.append(new_lead)
        new_count += 1

    if new_count == 0:
        logger.info("  No new leads to add to Email Queue (all already present)")
        return 0

    # Rebuild and write all rows with sequential row_numbers
    all_sheet_rows = [eq_headers]
    for i, lead in enumerate(existing_rows):
        row = []
        for h in eq_headers:
            if h == "row_number":
                row.append(str(i + 2))  # Sequential: row 2, 3, 4...
            else:
                row.append(lead.get(h, ""))
        all_sheet_rows.append(row)

    eq_ws.clear()
    eq_ws.update("A1", all_sheet_rows)
    logger.info(f"  Added {new_count} new leads to Email Queue (total: {len(existing_rows)})")

    return new_count


def get_sheet_client():
    """Authenticate and return gspread spreadsheet."""
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
    return gc.open_by_key(sheet_id)


def get_leads_needing_email(master_sheet, city_filter=None, limit=None) -> tuple:
    """Get leads that have a website but no email.

    Returns:
        (leads_list, headers, email_col_idx, website_col_idx)
    """
    all_data = master_sheet.get_all_values()
    if len(all_data) < 2:
        return [], [], -1, -1

    headers = all_data[0]

    def col_idx(name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    email_idx = col_idx("email")
    website_idx = col_idx("website")
    city_idx = col_idx("city")
    name_idx = col_idx("business_name")
    status_idx = col_idx("status")

    if website_idx == -1:
        logger.error("'website' column not found in sheet")
        return [], headers, -1, -1

    # If email column doesn't exist, we'll need to add it
    if email_idx == -1:
        logger.info("'email' column not found — it will be created")
        email_idx = len(headers)
        headers.append("email")

    leads = []
    for row_num, row in enumerate(all_data[1:], start=2):
        def cell(idx):
            if idx < 0 or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        # Skip if already has email
        existing_email = cell(email_idx)
        if existing_email and "@" in existing_email:
            continue

        # Skip non-New statuses (don't re-process contacted/converted leads)
        status = cell(status_idx).lower() if status_idx >= 0 else "new"
        if status in ("contacted", "converted", "replied", "not_interested"):
            continue

        # Must have a real website
        website = cell(website_idx)
        if not is_real_website(website):
            continue

        # City filter
        if city_filter:
            city = cell(city_idx).lower()
            if city_filter.lower() not in city:
                continue

        # Store all column data for Email Queue population
        all_cols = {}
        for j in range(len(headers)):
            all_cols[headers[j]] = cell(j)

        leads.append({
            "row_num": row_num,
            "business_name": cell(name_idx),
            "website": website,
            "city": cell(city_idx) if city_idx >= 0 else "",
            "all_data": all_cols,
        })

    # Apply limit
    if limit and len(leads) > limit:
        leads = leads[:limit]

    return leads, headers, email_idx, website_idx


def main():
    parser = argparse.ArgumentParser(description="Email Extractor — Scrape emails from business websites")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of leads to process")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without updating sheet")
    parser.add_argument("--city", type=str, default=None,
                        help="Filter by city name")
    parser.add_argument("--test-url", type=str, default=None,
                        help="Test extraction on a single URL (no Google Sheet needed)")
    args = parser.parse_args()

    # ─── Quick Test Mode ──────────────────────────────────
    if args.test_url:
        logger.info("═══════════════════════════════════════════")
        logger.info("  EMAIL EXTRACTOR — Test Mode")
        logger.info(f"  URL: {args.test_url}")
        logger.info("═══════════════════════════════════════════")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )
            context.route("**/*.{png,jpg,jpeg,gif,svg,mp4,webm,woff,woff2,ttf}", lambda route: route.abort())
            page = context.new_page()

            logger.info("\nScraping main page + contact pages...")
            emails = scrape_website_emails(page, args.test_url)
            browser.close()

        if emails:
            logger.info(f"\n  Emails found: {len(emails)}")
            for e in emails:
                logger.info(f"    -> {e}")
        else:
            logger.info("\n  No emails found on this website.")

        logger.info("═══════════════════════════════════════════")
        return

    logger.info("═══════════════════════════════════════════")
    logger.info("  EMAIL EXTRACTOR — Scrape from Websites")
    logger.info(f"  Limit: {args.limit or 'all'}")
    logger.info(f"  City filter: {args.city or 'none'}")
    logger.info("═══════════════════════════════════════════")

    # Connect to Google Sheets
    spreadsheet = get_sheet_client()
    master_sheet = spreadsheet.sheet1

    # Get leads needing email extraction
    logger.info("\n1. Reading leads that need email extraction...")
    leads, headers, email_idx, website_idx = get_leads_needing_email(
        master_sheet, city_filter=args.city, limit=args.limit
    )
    logger.info(f"   Found {len(leads)} leads with website but no email")

    if not leads:
        logger.info("No leads to process. Either all have emails or no websites found.")
        return

    # Launch Playwright
    logger.info(f"\n2. Launching browser and extracting emails...")
    found_count = 0
    failed_count = 0
    updates = []  # (row_num, email)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        # Block images/media for speed
        context.route("**/*.{png,jpg,jpeg,gif,svg,mp4,webm,woff,woff2,ttf}", lambda route: route.abort())
        page = context.new_page()

        for i, lead in enumerate(leads, 1):
            name = lead["business_name"][:30]
            website = lead["website"]

            try:
                emails = scrape_website_emails(page, website)

                if emails:
                    # Pick best email: prefer info@/contact@/owner names over generic
                    best_email = emails[0]
                    for e in emails:
                        local = e.split("@")[0]
                        if local in ("info", "contact", "hello", "enquiry", "enquiries", "booking", "bookings"):
                            best_email = e
                            break

                    found_count += 1
                    updates.append((lead["row_num"], best_email))
                    logger.info(f"   [{i}/{len(leads)}] {name:30s} -> {best_email}")
                else:
                    failed_count += 1
                    logger.info(f"   [{i}/{len(leads)}] {name:30s} -> no email found")

            except Exception as e:
                failed_count += 1
                logger.debug(f"   [{i}/{len(leads)}] {name:30s} -> ERROR: {e}")

            # Random delay between visits (anti-bot)
            delay = random.uniform(2.0, 5.0)
            time.sleep(delay)

            # Progress update every 50 leads
            if i % 50 == 0:
                logger.info(f"   --- Progress: {i}/{len(leads)} processed, {found_count} emails found ---")

        browser.close()

    # Summary before writing
    logger.info(f"\n3. Extraction complete:")
    logger.info(f"   Processed: {len(leads)}")
    logger.info(f"   Emails found: {found_count}")
    logger.info(f"   No email: {failed_count}")
    logger.info(f"   Hit rate: {found_count / len(leads) * 100:.1f}%")

    if args.dry_run:
        logger.info("\n   DRY RUN — no changes written to sheet.")
        if updates:
            logger.info("   Emails that would be written:")
            for row_num, email in updates[:20]:
                logger.info(f"     Row {row_num}: {email}")
            if len(updates) > 20:
                logger.info(f"     ... and {len(updates) - 20} more")
        return

    # Write emails back to Google Sheet
    if updates:
        logger.info(f"\n4. Writing {len(updates)} emails to Google Sheet...")
        email_col_letter = chr(65 + email_idx) if email_idx < 26 else None

        if not email_col_letter:
            # Multi-letter column (AA, AB, etc.)
            if email_idx < 52:
                email_col_letter = "A" + chr(65 + email_idx - 26)
            else:
                logger.error("Email column index too high")
                return

        # Batch update in chunks of 50
        for i in range(0, len(updates), 50):
            batch = updates[i:i + 50]
            cells = [
                {"range": f"{email_col_letter}{row_num}", "values": [[email]]}
                for row_num, email in batch
            ]
            try:
                master_sheet.batch_update(cells)
                logger.info(f"   Batch {i // 50 + 1}: updated {len(batch)} emails")
            except Exception as e:
                logger.error(f"   Batch {i // 50 + 1} failed: {e}")
                time.sleep(3)
                try:
                    master_sheet.batch_update(cells)
                    logger.info(f"   Batch {i // 50 + 1}: retry successful")
                except Exception as e2:
                    logger.error(f"   Batch {i // 50 + 1}: retry also failed: {e2}")

            time.sleep(1)  # Rate limit

    # 5. Add found emails to Email Queue directly
    eq_added = 0
    if updates:
        logger.info(f"\n5. Adding {len(updates)} leads to Email Queue...")
        leads_by_row = {lead["row_num"]: lead for lead in leads}
        eq_added = append_to_email_queue(spreadsheet, updates, leads_by_row, headers)

    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info("  EMAIL EXTRACTOR COMPLETE")
    logger.info(f"  Websites checked:  {len(leads)}")
    logger.info(f"  Emails found:      {found_count}")
    logger.info(f"  Hit rate:          {found_count / len(leads) * 100:.1f}%")
    logger.info(f"  Sheet1 updated:    {len(updates)} rows")
    logger.info(f"  Email Queue added: {eq_added} leads")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
