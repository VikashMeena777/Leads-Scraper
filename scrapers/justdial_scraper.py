"""
Justdial Lead Scraper (Backup Source)
=====================================
Scrapes Justdial for business listings in Indian cities.
Justdial has explicit phone numbers and less bot detection than Google Maps.

Usage:
    python scrapers/justdial_scraper.py                   # Full run (all cities)
    python scrapers/justdial_scraper.py --headful         # Visible browser for debugging
    python scrapers/justdial_scraper.py --city Jaipur     # Scrape only Jaipur
"""

import os
import sys
import json
import time
import random
import re
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

_file_handler = logging.FileHandler("output/justdial_scraper.log", mode="a", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console, _file_handler],
)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

OUTPUT_CSV = "output/justdial_raw.csv"
STATE_FILE = Path("output/state.json")
CITIES_CONFIG = "config/cities.json"

# Justdial uses CSS sprite-based phone number obfuscation.
# The numbers are rendered as spans with specific CSS classes that map to digits.
# This mapping may change — update if Justdial changes their obfuscation.
JD_PHONE_CLASS_MAP = {
    "icon-acb": "0", "icon-yz": "1", "icon-wx": "2", "icon-vu": "3",
    "icon-ts": "4", "icon-rq": "5", "icon-po": "6", "icon-nm": "7",
    "icon-lk": "8", "icon-ji": "9",
}


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


def random_delay(min_sec: float = 2, max_sec: float = 5):
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
    """Apply stealth patches to hide automation signals (fallback for old API)."""
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


def decode_jd_phone(card) -> str:
    """Decode Justdial's obfuscated phone numbers from CSS sprite classes."""
    phone_digits = []
    try:
        # Justdial phone numbers are in spans with specific icon classes
        phone_spans = card.locator(".mobilesv span").all()
        if not phone_spans:
            phone_spans = card.locator(".lstnumber span").all()

        for span in phone_spans:
            classes = span.get_attribute("class") or ""
            for cls, digit in JD_PHONE_CLASS_MAP.items():
                if cls in classes:
                    phone_digits.append(digit)
                    break
    except Exception:
        pass

    if phone_digits:
        return "".join(phone_digits)

    # Fallback: try to find tel: links
    try:
        tel_link = card.locator('a[href^="tel:"]')
        if tel_link.count() > 0:
            href = tel_link.first.get_attribute("href") or ""
            return href.replace("tel:", "").strip()
    except Exception:
        pass

    # Fallback: try to find plain text phone numbers
    try:
        card_text = card.text_content() or ""
        phone_match = re.findall(r"(?:\+91[\-\s]?)?(?:0)?[6-9]\d{4}[\-\s]?\d{5}", card_text)
        if phone_match:
            return phone_match[0].strip()
    except Exception:
        pass

    return ""


def close_popups(page):
    """Close Justdial's common popups (login, app download, etc.)."""
    popup_selectors = [
        "#best_deal_close",
        ".close-btn",
        "span.popup_cls",
        "#pop-close",
        ".modalClose",
        'button[aria-label="Close"]',
    ]
    for sel in popup_selectors:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click()
                time.sleep(0.5)
        except Exception:
            continue


def scrape_justdial_city_keyword(city: str, keyword: str, headless: bool = True) -> list:
    """Scrape Justdial for a single city × keyword combination."""
    results = []
    url_keyword = keyword.replace(" ", "-")
    url = f"https://www.justdial.com/{city}/{url_keyword}"
    logger.info(f"🔍 Scraping Justdial: {city} - {keyword} ({url})")

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
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            random_delay(3, 6)
            close_popups(page)

            # Scroll to load more results
            for scroll_round in range(8):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                random_delay(2, 3)
                close_popups(page)

            # Find listing cards — Justdial uses various class names across versions
            card_selectors = [
                "li.cntanr",                    # Newer Justdial layout
                ".resultbox_info",              # Older layout
                ".store-details",               # Mobile-like layout
                ".jsx-s1",                      # React-based layout
                '[class*="resultbox"]',         # Generic catch-all
            ]

            cards = []
            for sel in card_selectors:
                cards = page.locator(sel).all()
                if cards:
                    logger.info(f"📊 Found {len(cards)} listings using selector: {sel}")
                    break

            if not cards:
                logger.warning(f"No listing cards found on Justdial for {city}/{keyword}")
                browser.close()
                return results

            for i, card in enumerate(cards):
                try:
                    # Business Name
                    name = ""
                    name_selectors = [
                        "h2 a",
                        ".lng_cont_name",
                        ".store-name span",
                        "a.lng_cont_name",
                        '[class*="storename"]',
                    ]
                    for sel in name_selectors:
                        try:
                            el = card.locator(sel)
                            if el.count() > 0:
                                name = el.first.text_content(timeout=2000) or ""
                                if name.strip():
                                    break
                        except Exception:
                            continue

                    if not name.strip():
                        continue

                    # Phone Number (decoded from CSS sprites or fallback methods)
                    phone = decode_jd_phone(card)

                    # Address
                    address = ""
                    addr_selectors = [
                        ".cont_sw_addr",
                        ".mrehover span",
                        ".comp-address span",
                        '[class*="address"]',
                    ]
                    for sel in addr_selectors:
                        try:
                            el = card.locator(sel)
                            if el.count() > 0:
                                address = el.first.text_content(timeout=2000) or ""
                                if address.strip():
                                    break
                        except Exception:
                            continue

                    # Rating
                    rating = ""
                    rating_selectors = [
                        ".green-box",
                        ".total_hr_avg span",
                        ".rating span",
                        '[class*="rating"]',
                    ]
                    for sel in rating_selectors:
                        try:
                            el = card.locator(sel)
                            if el.count() > 0:
                                rating = el.first.text_content(timeout=2000) or ""
                                if rating.strip():
                                    break
                        except Exception:
                            continue

                    row = {
                        "business_name": name.strip(),
                        "category": keyword,
                        "city": city,
                        "phone": phone.strip(),
                        "website": "",
                        "address": address.strip(),
                        "rating": rating.strip(),
                        "source": "justdial",
                        "search_keyword": keyword,
                        "scraped_at": datetime.now().isoformat(),
                    }

                    results.append(row)
                    append_to_csv(row, OUTPUT_CSV)
                    phone_info = f" | 📞 {phone}" if phone else " | ❌ no phone"
                    logger.info(f"  ✅ [{i+1}/{len(cards)}] {name.strip()}{phone_info}")

                    random_delay(0.5, 1.5)

                except Exception as e:
                    logger.warning(f"  ❌ [{i+1}/{len(cards)}] Extraction failed: {e}")
                    continue

        except Exception as e:
            logger.error(f"🚨 Failed to scrape Justdial '{city}/{keyword}': {e}")
        finally:
            browser.close()

    logger.info(f"✅ Finished Justdial '{city}/{keyword}' — {len(results)} leads")
    return results


def main():
    parser = argparse.ArgumentParser(description="Justdial Lead Scraper")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--city", type=str, help="Scrape only this city")
    parser.add_argument("--reset", action="store_true", help="Reset Justdial progress")
    args = parser.parse_args()

    Path("output").mkdir(parents=True, exist_ok=True)

    headless = os.getenv("HEADLESS", "true").lower() == "true"
    if args.headful:
        headless = False

    if args.reset:
        state = load_state()
        state["completed"] = [k for k in state["completed"] if not k.startswith("justdial:")]
        save_state(state)
        logger.info("🔄 Justdial state reset")
    
    state = load_state()

    with open(CITIES_CONFIG, encoding="utf-8") as f:
        config = json.load(f)

    total_leads = 0
    for target in config["targets"]:
        city = target["city"]
        if args.city and city.lower() != args.city.lower():
            continue

        for keyword in target["keywords"]:
            task_key = f"justdial:{city}:{keyword}"
            if task_key in state["completed"]:
                logger.info(f"⏭ Skipping (already done): {city} - {keyword}")
                continue

            leads = scrape_justdial_city_keyword(city, keyword, headless=headless)
            total_leads += len(leads)

            state["completed"].append(task_key)
            state["last_run"] = datetime.now().isoformat()
            save_state(state)

            random_delay(5, 10)

    logger.info("═══════════════════════════════════════════")
    logger.info(f"🎯 JUSTDIAL SCRAPING COMPLETE — {total_leads} leads")
    logger.info("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
