"""
Google Search Results Scraper
==============================
Scrapes Google Search results to find emails, phone numbers, and LinkedIn profiles
for target businesses and social media managers.

Uses Google Dork techniques to extract contact info from public web pages.
No login required for any platform — all data comes from Google's public index.

Usage:
    python scrapers/google_search_scraper.py                   # Full run
    python scrapers/google_search_scraper.py --headful         # Visible browser
    python scrapers/google_search_scraper.py --city Jaipur     # Single city
    python scrapers/google_search_scraper.py --smm-only        # Only search for Social Media Managers
    python scrapers/google_search_scraper.py --deep            # Also visit result pages for contact extraction
"""

import os
import sys
import re
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# Fix Windows terminal Unicode (cp1252 can't display emojis)
Path("output").mkdir(parents=True, exist_ok=True)
_console = logging.StreamHandler(stream=sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_file_handler = logging.FileHandler("output/google_search_scraper.log", mode="a", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console, _file_handler],
)
logger = logging.getLogger(__name__)

# ─── Regex Patterns ──────────────────────────────────────
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"(?:\+91[\-\s]?)?(?:0)?[6-9]\d{4}[\-\s]?\d{5}"

# Domains to skip when extracting emails (common false positives)
SKIP_EMAIL_DOMAINS = {
    "example.com", "test.com", "domain.com", "email.com", "sentry.io",
    "wixpress.com", "w3.org", "schema.org", "googleapis.com", "gstatic.com",
    "facebook.com", "twitter.com", "instagram.com", "google.com",
}

# Domains to skip when visiting pages for deep scraping
SKIP_VISIT_DOMAINS = {
    "google.com", "facebook.com", "twitter.com", "youtube.com", "wikipedia.org",
    "instagram.com", "linkedin.com", "amazon.com", "flipkart.com", "quora.com",
    "reddit.com", "pinterest.com",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

OUTPUT_CSV = "output/google_search_raw.csv"
STATE_FILE = Path("output/state.json")
CITIES_CONFIG = "config/cities.json"
QUERIES_CONFIG = "config/search_queries.json"


# ─── State Management ───────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"completed": [], "last_run": None}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def random_delay(min_sec: float = 3, max_sec: float = 7):
    time.sleep(random.uniform(min_sec, max_sec))


def append_to_csv(row: dict, filepath: str):
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists() and path.stat().st_size > 0:
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)


def apply_stealth(page):
    """Apply stealth patches (fallback for old API)."""
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        return
    except (ImportError, TypeError, AttributeError):
        pass

    logger.info("Applying manual stealth patches")
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'hi'] });
        window.chrome = { runtime: {} };
        const origQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(parameters);
    """)


def _get_playwright_context_manager():
    """Return a Stealth-wrapped or plain sync_playwright context manager."""
    try:
        from playwright_stealth import Stealth
        logger.info("🛡️ Using playwright-stealth v2")
        return Stealth().use_sync(sync_playwright())
    except (ImportError, TypeError, AttributeError):
        return sync_playwright()


# ─── Email & Phone Extraction ───────────────────────────
def extract_emails(text: str) -> list[str]:
    """Extract valid email addresses from text, filtering out fakes."""
    if not text:
        return []
    emails = re.findall(EMAIL_REGEX, text)
    filtered = []
    for email in emails:
        email = email.lower().strip().rstrip(".")
        domain = email.split("@")[-1] if "@" in email else ""
        if domain in SKIP_EMAIL_DOMAINS:
            continue
        if any(fake in email for fake in ["noreply", "no-reply", "donotreply", "yourname", "user@"]):
            continue
        if len(email) < 6 or len(email) > 100:
            continue
        filtered.append(email)
    return list(set(filtered))


def extract_phones(text: str) -> list[str]:
    """Extract Indian phone numbers from text."""
    if not text:
        return []
    phones = re.findall(PHONE_REGEX, text)
    # Clean up formatting
    cleaned = []
    for p in phones:
        p = re.sub(r"[\s\-()]", "", p.strip())
        if len(p) >= 10:
            cleaned.append(p)
    return list(set(cleaned))


# ─── Google Search ───────────────────────────────────────
def search_google(page, query: str, max_results: int = 10) -> list[dict]:
    """Perform a single Google Search and extract results with contact info."""
    results = []
    logger.info(f"  🔎 Query: {query[:80]}...")

    try:
        encoded_query = query.replace(" ", "+")
        page.goto(
            f"https://www.google.com/search?q={encoded_query}&num={max_results}&hl=en",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        random_delay(2, 4)

        # Check for CAPTCHA / unusual traffic
        page_text = page.text_content("body") or ""
        if "unusual traffic" in page_text.lower() or "captcha" in page_text.lower():
            logger.warning("⚠️ Google CAPTCHA detected! Waiting 120 seconds...")
            time.sleep(120)
            return results

        # Extract search result blocks
        result_blocks = page.locator("#search .g, #rso .g").all()

        for block in result_blocks[:max_results]:
            try:
                # Title
                title = ""
                try:
                    title_el = block.locator("h3")
                    if title_el.count() > 0:
                        title = title_el.first.text_content(timeout=2000) or ""
                except Exception:
                    pass

                # URL
                url = ""
                try:
                    link_el = block.locator("a")
                    if link_el.count() > 0:
                        url = link_el.first.get_attribute("href") or ""
                except Exception:
                    pass

                # Snippet text
                snippet = ""
                try:
                    snippet_selectors = [".VwiC3b", ".st", "[data-sncf]", ".IsZvec"]
                    for sel in snippet_selectors:
                        el = block.locator(sel)
                        if el.count() > 0:
                            snippet = el.first.text_content(timeout=2000) or ""
                            if snippet.strip():
                                break
                except Exception:
                    pass

                # Extract contacts from the snippet + title
                full_text = f"{title} {snippet} {url}"
                emails = extract_emails(full_text)
                phones = extract_phones(full_text)

                is_linkedin = "linkedin.com/in" in url.lower()

                results.append({
                    "title": title.strip(),
                    "url": url.strip(),
                    "snippet": snippet.strip()[:200],  # Truncate long snippets
                    "emails": emails,
                    "phones": phones,
                    "is_linkedin": is_linkedin,
                })

            except Exception as e:
                logger.debug(f"  Failed to extract search result: {e}")
                continue

    except Exception as e:
        logger.error(f"  Google search failed: {e}")

    return results


def visit_page_for_contacts(page, url: str) -> dict:
    """Visit a URL and scrape it for email addresses and phone numbers."""
    contacts = {"emails": [], "phones": []}

    domain = urlparse(url).netloc.lower()
    if any(skip in domain for skip in SKIP_VISIT_DOMAINS):
        return contacts

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=12000)
        random_delay(1.5, 3)

        page_text = page.text_content("body") or ""
        page_html = page.content() or ""

        # Extract from visible text
        contacts["emails"] = extract_emails(page_text)
        # Also check HTML for mailto: links
        mailto_emails = re.findall(r'mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', page_html)
        contacts["emails"] = list(set(contacts["emails"] + [e.lower() for e in mailto_emails]))

        contacts["phones"] = extract_phones(page_text)

    except Exception as e:
        logger.debug(f"  Could not visit {url[:60]}: {e}")

    return contacts


# ─── Main Scraper Logic ─────────────────────────────────
def scrape_google_search(
    city: str, keyword: str, headless: bool = True, deep: bool = False
) -> list[dict]:
    """Run Google searches for a city × keyword and extract contacts."""
    results = []

    with open(QUERIES_CONFIG, encoding="utf-8") as f:
        query_templates = json.load(f)

    with _get_playwright_context_manager() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": random.randint(1280, 1440), "height": random.randint(800, 1000)},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        apply_stealth(page)

        try:
            # ── Business email queries ──
            if keyword:
                for template in query_templates.get("business_email_queries", []):
                    query = template.format(keyword=keyword, city=city)
                    search_results = search_google(page, query, max_results=10)

                    for sr in search_results:
                        # Save results that contain contacts directly from snippets
                        if sr["emails"] or sr["phones"]:
                            for email in sr["emails"] or [""]:
                                row = {
                                    "business_name": sr["title"],
                                    "city": city,
                                    "email": email,
                                    "phone": sr["phones"][0] if sr["phones"] else "",
                                    "website": sr["url"],
                                    "source": "google_search",
                                    "search_query": query[:100],
                                    "is_linkedin": sr["is_linkedin"],
                                    "scraped_at": datetime.now().isoformat(),
                                }
                                results.append(row)
                                append_to_csv(row, OUTPUT_CSV)
                                contact = email or sr["phones"][0] if sr["phones"] else "contact found"
                                logger.info(f"    📧 {contact} — {sr['title'][:50]}")

                        # Deep scrape: visit the actual page for more contacts
                        elif deep and sr["url"] and not sr["is_linkedin"]:
                            contacts = visit_page_for_contacts(page, sr["url"])
                            for email in contacts["emails"][:3]:
                                row = {
                                    "business_name": sr["title"],
                                    "city": city,
                                    "email": email,
                                    "phone": contacts["phones"][0] if contacts["phones"] else "",
                                    "website": sr["url"],
                                    "source": "google_search_deep",
                                    "search_query": query[:100],
                                    "is_linkedin": False,
                                    "scraped_at": datetime.now().isoformat(),
                                }
                                results.append(row)
                                append_to_csv(row, OUTPUT_CSV)
                                logger.info(f"    🔍 Deep: {email} — {sr['url'][:60]}")

                    random_delay(10, 18)  # Long delay between Google searches

            # ── SMM queries (Social Media Managers) ──
            for template in query_templates.get("smm_queries", []):
                query = template.format(city=city)
                search_results = search_google(page, query, max_results=10)

                for sr in search_results:
                    if sr["is_linkedin"]:
                        # Extract name from LinkedIn title format: "Name - Title - LinkedIn"
                        name = sr["title"].split(" - ")[0].split(" | ")[0].strip()
                        name = name.replace(" LinkedIn", "").replace("| LinkedIn", "").strip()
                        row = {
                            "business_name": name,
                            "city": city,
                            "email": sr["emails"][0] if sr["emails"] else "",
                            "phone": sr["phones"][0] if sr["phones"] else "",
                            "website": sr["url"],
                            "source": "google_search_linkedin",
                            "search_query": query[:100],
                            "is_linkedin": True,
                            "scraped_at": datetime.now().isoformat(),
                        }
                        results.append(row)
                        append_to_csv(row, OUTPUT_CSV)
                        logger.info(f"    👤 LinkedIn: {name}")

                    elif sr["emails"] or sr["phones"]:
                        for email in sr["emails"] or [""]:
                            row = {
                                "business_name": sr["title"],
                                "city": city,
                                "email": email,
                                "phone": sr["phones"][0] if sr["phones"] else "",
                                "website": sr["url"],
                                "source": "google_search_smm",
                                "search_query": query[:100],
                                "is_linkedin": False,
                                "scraped_at": datetime.now().isoformat(),
                            }
                            results.append(row)
                            append_to_csv(row, OUTPUT_CSV)
                            contact = email or sr["phones"][0]
                            logger.info(f"    📧 SMM: {contact} — {sr['title'][:50]}")

                random_delay(10, 18)

        except Exception as e:
            logger.error(f"🚨 Google Search scraping failed: {e}")
        finally:
            browser.close()

    return results


# ─── Entry Point ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Google Search Lead Scraper")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--city", type=str, help="Scrape only this city")
    parser.add_argument("--smm-only", action="store_true", help="Only search for Social Media Managers")
    parser.add_argument("--deep", action="store_true", help="Visit result pages for deeper contact extraction")
    parser.add_argument("--reset", action="store_true", help="Reset Google Search progress")
    args = parser.parse_args()

    Path("output").mkdir(parents=True, exist_ok=True)

    headless = os.getenv("HEADLESS", "true").lower() == "true"
    if args.headful:
        headless = False

    if args.reset:
        state = load_state()
        state["completed"] = [k for k in state["completed"] if not k.startswith("gsearch")]
        save_state(state)
        logger.info("🔄 Google Search state reset")

    state = load_state()

    with open(CITIES_CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    total_leads = 0
    for target in config["targets"]:
        city = target["city"]
        if args.city and city.lower() != args.city.lower():
            continue

        if args.smm_only:
            task_key = f"gsearch_smm:{city}"
            if task_key in state["completed"]:
                logger.info(f"⏭ Skipping SMM (already done): {city}")
                continue

            logger.info(f"🔍 Searching SMM profiles in {city}")
            leads = scrape_google_search(city, "", headless=headless, deep=args.deep)
            total_leads += len(leads)

            state["completed"].append(task_key)
            state["last_run"] = datetime.now().isoformat()
            save_state(state)

            random_delay(20, 40)  # Very long delay between cities for Google
        else:
            for keyword in target["keywords"]:
                task_key = f"gsearch:{city}:{keyword}"
                if task_key in state["completed"]:
                    logger.info(f"⏭ Skipping (already done): {city} - {keyword}")
                    continue

                logger.info(f"🔍 Searching: {keyword} in {city}")
                leads = scrape_google_search(city, keyword, headless=headless, deep=args.deep)
                total_leads += len(leads)

                state["completed"].append(task_key)
                state["last_run"] = datetime.now().isoformat()
                save_state(state)

                random_delay(20, 40)  # Very long between batches

    logger.info("═══════════════════════════════════════════")
    logger.info(f"🎯 GOOGLE SEARCH SCRAPING COMPLETE — {total_leads} leads")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
