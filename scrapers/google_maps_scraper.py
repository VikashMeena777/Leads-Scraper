"""
Google Maps Lead Scraper
========================
Scrapes Google Maps for business listings (restaurants, cafes, etc.)
Uses playwright-stealth for anti-detection.

Usage:
    python scrapers/google_maps_scraper.py                    # Full run (all cities)
    python scrapers/google_maps_scraper.py --headful          # Visible browser for debugging
    python scrapers/google_maps_scraper.py --city Jaipur      # Scrape only Jaipur
    python scrapers/google_maps_scraper.py --keyword cafes    # Scrape only cafes
"""

import os
import sys
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime

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

_file_handler = logging.FileHandler("output/google_maps_scraper.log", mode="a", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console, _file_handler],
)
logger = logging.getLogger(__name__)

# ─── User Agent Rotation ────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# ─── Config ──────────────────────────────────────────────
OUTPUT_CSV = "output/google_maps_raw.csv"
STATE_FILE = Path("output/state.json")
CITIES_CONFIG = "config/cities.json"


# ─── State Management (Resume on Crash) ─────────────────
def load_state() -> dict:
    """Load scraper progress state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Corrupted state.json — starting fresh")
    return {"completed": [], "last_run": None}


def save_state(state: dict):
    """Save scraper progress state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ─── Helpers ─────────────────────────────────────────────
def random_delay(min_sec: float = None, max_sec: float = None):
    """Sleep for a random duration to mimic human behavior."""
    min_sec = min_sec or float(os.getenv("MIN_DELAY", 2))
    max_sec = max_sec or float(os.getenv("MAX_DELAY", 5))
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def append_to_csv(row: dict, filepath: str):
    """Append a single row to CSV. Creates file with headers if it doesn't exist."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists() and path.stat().st_size > 0:
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)


def human_like_mouse_move(page):
    """Move mouse to a random position to look more human."""
    try:
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass


def apply_stealth(page):
    """Apply stealth patches to hide automation signals (fallback for old API)."""
    try:
        # Try old-style API (playwright-stealth < 2.0 or tf-playwright-stealth)
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        return
    except (ImportError, TypeError, AttributeError):
        pass

    # Manual stealth fallback — always works
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


def _get_playwright_context_manager(headless: bool):
    """Return a Stealth-wrapped or plain sync_playwright context manager."""
    try:
        from playwright_stealth import Stealth
        logger.info("🛡️ Using playwright-stealth v2 (Stealth context manager)")
        return Stealth().use_sync(sync_playwright())
    except (ImportError, TypeError, AttributeError):
        logger.info("🔧 Using plain Playwright (stealth will be applied per-page)")
        return sync_playwright()


# ─── Core Scraper ────────────────────────────────────────
def extract_listing_details(page) -> dict | None:
    """Extract business details from the currently open Google Maps listing panel."""
    try:
        # Business name
        name = ""
        try:
            name_el = page.locator("h1.DUwDvf")
            if name_el.count() > 0:
                name = name_el.first.text_content(timeout=3000) or ""
        except Exception:
            try:
                name_el = page.locator("h1")
                if name_el.count() > 0:
                    name = name_el.first.text_content(timeout=3000) or ""
            except Exception:
                pass

        if not name.strip():
            return None

        # Google Maps URL (current page URL — always available)
        google_maps_url = ""
        try:
            google_maps_url = page.url or ""
        except Exception:
            pass

        # Phone number — try multiple selectors
        phone = ""
        phone_selectors = [
            '[data-item-id*="phone"] .Io6YTe',
            'button[data-item-id*="phone"] .rogA2c',
            '[aria-label*="Phone"] .Io6YTe',
            'a[href^="tel:"]',
        ]
        for sel in phone_selectors:
            try:
                el = page.locator(sel)
                if el.count() > 0:
                    text = el.first.text_content(timeout=2000) or ""
                    href = el.first.get_attribute("href") or ""
                    phone = href.replace("tel:", "") if href.startswith("tel:") else text
                    if phone.strip():
                        break
            except Exception:
                continue

        # Website — try multiple selectors and extract both text and href
        website = ""
        website_selectors = [
            '[data-item-id*="authority"] .Io6YTe',
            'a[data-item-id*="authority"]',
            '[aria-label*="Website"] .Io6YTe',
            'a[aria-label*="Website"]',
            'a[data-tooltip*="website"]',
            'a[href*="http"]:has(.Io6YTe)',
        ]
        for sel in website_selectors:
            try:
                el = page.locator(sel)
                if el.count() > 0:
                    # Try href first (full URL), then display text (domain)
                    href = el.first.get_attribute("href") or ""
                    text = el.first.text_content(timeout=2000) or ""

                    # Google Maps wraps links in redirect — extract real URL
                    if "google.com/url?" in href:
                        import re as _re
                        match = _re.search(r'[?&]q=([^&]+)', href)
                        if match:
                            from urllib.parse import unquote
                            href = unquote(match.group(1))

                    # Prefer href (full URL), fallback to display text
                    if href and "google.com" not in href:
                        website = href
                    elif text.strip() and "google" not in text.lower():
                        website = text.strip()

                    if website:
                        # Ensure it starts with http
                        if website and not website.startswith("http"):
                            website = "https://" + website
                        break
            except Exception:
                continue

        # Address
        address = ""
        address_selectors = [
            '[data-item-id*="address"] .Io6YTe',
            'button[data-item-id*="address"] .rogA2c',
            '[aria-label*="Address"] .Io6YTe',
        ]
        for sel in address_selectors:
            try:
                el = page.locator(sel)
                if el.count() > 0:
                    address = el.first.text_content(timeout=2000) or ""
                    if address.strip():
                        break
            except Exception:
                continue

        # Rating
        rating = ""
        try:
            rating_el = page.locator('div.F7nice span[aria-hidden="true"]')
            if rating_el.count() > 0:
                rating = rating_el.first.text_content(timeout=2000) or ""
        except Exception:
            pass

        # Category
        category = ""
        try:
            cat_el = page.locator('button.DkEaL')
            if cat_el.count() > 0:
                category = cat_el.first.text_content(timeout=2000) or ""
        except Exception:
            pass

        return {
            "business_name": name.strip(),
            "category": category.strip(),
            "phone": phone.strip(),
            "website": website.strip(),
            "google_maps_url": google_maps_url.strip(),
            "address": address.strip(),
            "rating": rating.strip(),
        }

    except Exception as e:
        logger.debug(f"extract_listing_details error: {e}")
        return None


def scrape_city_keyword(city: str, keyword: str, headless: bool = True) -> list:
    """Scrape Google Maps for a single city × keyword combination."""
    results = []
    search_query = f"{keyword} in {city}"
    logger.info(f"🔍 Starting: {search_query}")

    with _get_playwright_context_manager(headless) as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={
                "width": random.randint(1280, 1440),
                "height": random.randint(800, 1000),
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            geolocation={"latitude": 26.9124, "longitude": 75.7873},
            permissions=["geolocation"],
        )
        page = context.new_page()
        apply_stealth(page)  # Fallback for old API / manual patches

        try:
            # Navigate to Google Maps
            url = f"https://www.google.com/maps/search/{keyword}+in+{city}"
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            random_delay(3, 6)
            human_like_mouse_move(page)

            # Wait for results to load
            try:
                page.wait_for_selector('[role="feed"]', timeout=15000)
            except Exception:
                logger.warning(f"Results feed not found for '{search_query}' — might be blocked or no results")
                browser.close()
                return results

            # Scroll the results panel to load all listings
            results_panel = page.locator('[role="feed"]')
            if results_panel.count() > 0:
                prev_count = 0
                for scroll_attempt in range(20):
                    results_panel.evaluate("el => el.scrollTop = el.scrollHeight")
                    random_delay(1.5, 3.0)
                    human_like_mouse_move(page)

                    # Check for end of list
                    end_marker = page.locator("text=You've reached the end of the list")
                    if end_marker.count() > 0:
                        logger.info(f"📋 Reached end of results after {scroll_attempt + 1} scrolls")
                        break

                    # Check if new listings loaded
                    current_count = page.locator('[role="feed"] > div > div > a').count()
                    if current_count == prev_count and scroll_attempt > 3:
                        logger.info(f"📋 No new results after {scroll_attempt + 1} scrolls ({current_count} total)")
                        break
                    prev_count = current_count

            # Collect all listing links
            listing_links = page.locator('[role="feed"] > div > div > a[href*="/maps/place/"]').all()
            total_listings = len(listing_links)
            logger.info(f"📊 Found {total_listings} listings for '{search_query}'")

            # Track seen businesses to avoid duplicates
            seen_names = set()

            # Click each listing and extract details
            for i in range(total_listings):
                try:
                    # Re-query the listings (DOM might change after clicking)
                    listings = page.locator('[role="feed"] > div > div > a[href*="/maps/place/"]').all()
                    if i >= len(listings):
                        break

                    listings[i].click()
                    random_delay(2, 4)
                    human_like_mouse_move(page)

                    # Extract details from the panel
                    details = extract_listing_details(page)
                    if details and details["business_name"]:
                        # Deduplicate by normalized name
                        name_key = details["business_name"].strip().lower()
                        if name_key in seen_names:
                            logger.debug(f"  ⏭ [{i+1}/{total_listings}] Skipped duplicate: {details['business_name']}")
                        else:
                            seen_names.add(name_key)
                            row = {
                                **details,
                                "city": city,
                                "source": "google_maps",
                                "search_keyword": keyword,
                                "scraped_at": datetime.now().isoformat(),
                            }
                            results.append(row)
                            append_to_csv(row, OUTPUT_CSV)
                            phone_info = f" | 📞 {details['phone']}" if details["phone"] else ""
                            logger.info(f"  ✅ [{i+1}/{total_listings}] {details['business_name']}{phone_info}")
                    else:
                        logger.debug(f"  ⏭ [{i+1}/{total_listings}] Skipped (no name extracted)")

                    # Go back to results list
                    try:
                        back_btn = page.locator('button[aria-label="Back"]')
                        if back_btn.count() > 0:
                            back_btn.first.click()
                            random_delay(1, 2)
                    except Exception:
                        pass

                    random_delay()

                except Exception as e:
                    logger.warning(f"  ❌ [{i+1}/{total_listings}] Failed: {e}")
                    # Try to recover by going back
                    try:
                        page.go_back()
                        random_delay(1, 2)
                    except Exception:
                        pass
                    continue

        except Exception as e:
            logger.error(f"🚨 Failed to scrape '{search_query}': {e}")
        finally:
            browser.close()

    logger.info(f"✅ Finished '{search_query}' — {len(results)} unique leads collected")
    return results


# ─── Entry Point ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Google Maps Lead Scraper")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed (visible) mode for debugging")
    parser.add_argument("--city", type=str, help="Scrape only this city (e.g., --city Jaipur)")
    parser.add_argument("--keyword", type=str, help="Scrape only this keyword (e.g., --keyword cafes)")
    parser.add_argument("--reset", action="store_true", help="Reset progress and re-scrape everything")
    args = parser.parse_args()

    # Ensure output directory exists
    Path("output").mkdir(parents=True, exist_ok=True)

    headless = os.getenv("HEADLESS", "true").lower() == "true"
    if args.headful:
        headless = False

    # Load or reset state
    if args.reset:
        state = {"completed": [], "last_run": None}
        save_state(state)
        logger.info("🔄 State reset — will re-scrape everything")
    else:
        state = load_state()

    # Load city/keyword config
    with open(CITIES_CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    total_leads = 0
    total_tasks = 0
    skipped_tasks = 0

    for target in config["targets"]:
        city = target["city"]
        if args.city and city.lower() != args.city.lower():
            continue

        for keyword in target["keywords"]:
            if args.keyword and keyword.lower() != args.keyword.lower():
                continue

            task_key = f"gmaps:{city}:{keyword}"
            total_tasks += 1

            if task_key in state["completed"]:
                logger.info(f"⏭ Skipping (already done): {city} - {keyword}")
                skipped_tasks += 1
                continue

            leads = scrape_city_keyword(city, keyword, headless=headless)
            total_leads += len(leads)

            # Save progress
            state["completed"].append(task_key)
            state["last_run"] = datetime.now().isoformat()
            save_state(state)

            # Longer delay between city-keyword combos
            random_delay(5, 10)

    logger.info("═══════════════════════════════════════════")
    logger.info(f"🎯 GOOGLE MAPS SCRAPING COMPLETE")
    logger.info(f"   Total leads collected: {total_leads}")
    logger.info(f"   Tasks completed: {total_tasks - skipped_tasks}/{total_tasks}")
    logger.info(f"   Tasks skipped (already done): {skipped_tasks}")
    logger.info(f"   Output: {OUTPUT_CSV}")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
