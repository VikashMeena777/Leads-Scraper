# 🤖 AI-Powered Lead Generation System
### Complete Build Plan & Developer Specification
**For Cold Outreach Automation | Restaurants, Cafes & Social Media Managers**

> **Target Cities:** Jaipur • Delhi/NCR • Mumbai • Bangalore • Hyderabad • Pune  
> **Budget:** Free / Open Source Only  
> **Stack:** Python • n8n (self-hosted) • Google Sheets • Playwright

---

## Table of Contents
1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Build Phases](#3-build-phases)
   - [Phase 1 — Google Maps Scraper](#phase-1--google-maps-scraper)
   - [Phase 2 — Justdial Scraper (Backup)](#phase-2--justdial-scraper-backup)
   - [Phase 3 — Google Search Results Scraper](#phase-3--google-search-results-scraper)
   - [Phase 4 — Data Cleaner & Google Sheets Uploader](#phase-4--data-cleaner--google-sheets-uploader)
   - [Phase 5 — n8n Automation Setup](#phase-5--n8n-automation-setup)
   - [Phase 6 — Maintenance & Scaling](#phase-6--maintenance--scaling)
4. [Installation & Setup Checklist](#4-installation--setup-checklist)
5. [Build Timeline](#5-build-timeline)
6. [Known Risks & Solutions](#6-known-risks--solutions)
7. [Quick Reference Commands](#7-quick-reference-commands)

---

## 1. Project Overview

### 1.1 Goal
- Automatically collect **Phone Numbers** and **Email IDs** of target businesses
- **Target Types:** Restaurants, Cafes, Social Media Managers / Freelancers
- **Target Cities:** Jaipur, Delhi/NCR, Mumbai, Bangalore, Hyderabad, Pune
- **Use for:** Cold outreach for AI automations, websites, and your products/services
- **Budget:** Free / Open Source only — no paid APIs required

### 1.2 Data Sources

| Source | What We Get | Reliability | Risk Level |
|---|---|---|---|
| **Google Maps** (Playwright) | Phone, Website, Address, Name, Rating | ⭐⭐⭐ High | 🟡 Moderate (needs stealth) |
| **Justdial** (Playwright) | Phone, Address, Name, Category | ⭐⭐⭐⭐ Very High | 🟢 Low (less protected) |
| **Google Search Results** (Playwright) | Emails, Phone, Website from business pages | ⭐⭐⭐ High | 🟡 Moderate |

### 1.3 Tech Stack

| Component | Tool / Library | Cost | Purpose |
|---|---|---|---|
| Scraper Engine | Python 3.11+ | Free | Core scripting language |
| Google Maps Scrape | Playwright + playwright-stealth | Free | Extract business listings |
| Justdial Scrape | Playwright + playwright-stealth | Free | Backup data source (Indian businesses) |
| Google Search Scrape | Playwright + playwright-stealth | Free | Find emails & contacts from search results |
| Data Storage | Google Sheets + gspread | Free | Master lead database |
| Automation / Scheduler | n8n (self-hosted) | Free | Orchestrate all workflows |
| Notifications | Telegram Bot via n8n | Free | Alert when new leads found |
| Data Cleaning | pandas + phonenumbers | Free | Deduplicate & format data |
| Environment Config | python-dotenv | Free | Secure config management |

### 1.4 Why NOT Instagram & LinkedIn Scrapers

| Platform | Reason for Exclusion |
|---|---|
| **Instagram** (Instaloader) | Meta heavily rate-limits in 2025+. Hashtag scraping gets ~5-10 posts before blocking. Login mandatory, accounts get banned. Not worth the risk. |
| **LinkedIn** (linkedin-api) | LinkedIn permanently bans accounts using unofficial API. Extremely aggressive bot detection. Secondary accounts also get flagged. |
| **Alternative** | Google Search dorks (`site:linkedin.com`, `site:instagram.com`) achieve similar results WITHOUT login or account risk. This is covered in Phase 3. |

---

## 2. System Architecture

### 2.1 High-Level Flow

```
[n8n Scheduler] ──triggers──▶ [Python Scrapers]
                                      │
              ┌───────────────────────┤──────────────────────┐
              │                       │                      │
      [Google Maps]           [Justdial]           [Google Search]
      Restaurants/Cafes       Phone numbers         Emails & contacts
              │                       │                      │
              └───────────────────────┴──────────────────────┘
                                      │
                          [Data Cleaner Script]
                      Deduplicate + Format + Validate
                                      │
                          [Google Sheets DB]
                         Master Lead Database
                                      │
                      [n8n Telegram Notification]
                       Alert: X new leads added today
```

### 2.2 Folder Structure

```
lead-gen-system/
├── scrapers/
│   ├── google_maps_scraper.py      # Phase 1 — Primary source
│   ├── justdial_scraper.py         # Phase 2 — Backup source
│   ├── google_search_scraper.py    # Phase 3 — Email & contact finder
│   └── utils/
│       ├── stealth.py              # Anti-detection helpers
│       ├── state.py                # Resume-on-crash state tracker
│       └── proxies.py              # Proxy rotation (optional)
├── processor/
│   ├── cleaner.py                  # Phase 4 — dedup + format
│   └── sheets_uploader.py         # Phase 4 — push to Google Sheets
├── config/
│   ├── cities.json                 # City + keyword targets
│   └── search_queries.json        # Google Search dork templates
├── output/
│   ├── google_maps_raw.csv         # Raw output per source
│   ├── justdial_raw.csv
│   ├── google_search_raw.csv
│   ├── leads_clean.csv             # Final cleaned output
│   └── state.json                  # Scraper progress tracker
├── n8n/
│   └── workflow.json               # Import into n8n
├── .env.example                    # Required environment variables
├── .env                            # Your actual secrets (gitignored)
├── .gitignore
├── requirements.txt
└── README.md
```

### 2.3 `cities.json` Structure

```json
{
  "targets": [
    { "city": "Jaipur", "keywords": ["restaurants", "cafes", "bakeries", "hotels"] },
    { "city": "Delhi", "keywords": ["restaurants", "cafes", "cloud kitchens"] },
    { "city": "Mumbai", "keywords": ["restaurants", "cafes", "food joints"] },
    { "city": "Bangalore", "keywords": ["cafes", "restaurants", "co-working cafes"] },
    { "city": "Hyderabad", "keywords": ["restaurants", "cafes", "bakeries"] },
    { "city": "Pune", "keywords": ["cafes", "restaurants", "bakeries"] }
  ]
}
```

### 2.4 `search_queries.json` Structure

```json
{
  "business_email_queries": [
    "{keyword} in {city} contact email",
    "{keyword} in {city} phone number",
    "{keyword} {city} owner contact",
    "\"{keyword}\" \"{city}\" \"@gmail.com\" OR \"@yahoo.com\" OR \"contact\""
  ],
  "smm_queries": [
    "\"social media manager\" \"{city}\" email contact",
    "\"digital marketing freelancer\" \"{city}\" contact",
    "site:linkedin.com/in \"social media manager\" \"{city}\"",
    "site:linkedin.com/in \"digital marketer\" \"{city}\"",
    "\"content creator\" \"{city}\" \"@gmail.com\" OR \"contact\""
  ],
  "website_email_queries": [
    "site:{website} email OR contact OR \"@\"",
    "site:{website} \"contact us\" OR \"get in touch\""
  ]
}
```

### 2.5 `.env.example`

```env
# ─── Google Sheets ──────────────────────────
GOOGLE_SHEET_ID=
GOOGLE_CREDENTIALS_PATH=config/credentials.json

# ─── Telegram Notifications ─────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ─── Scraper Settings ───────────────────────
HEADLESS=true
MIN_DELAY=2
MAX_DELAY=5
MAX_RETRIES=3

# ─── Proxy (Optional) ───────────────────────
USE_PROXY=false
PROXY_URL=
```

---

## 3. Build Phases

> **Rule:** Build phases in order. Each phase produces working output before moving to the next.
> **Rule:** Every scraper saves results INCREMENTALLY (after each listing) — never at the end only.

---

### Phase 1 — Google Maps Scraper

> ⏱ **Estimated Time:** 2–3 hours | **Priority:** 🔴 HIGH | **Data:** Phone, Website, Address, Name

#### What It Does
- Searches Google Maps for each city × keyword combination (e.g., `"restaurants in Jaipur"`)
- Scrolls and collects all visible listings on the page
- Extracts: Business Name, Phone Number, Website URL, Address, Rating, Category
- Saves results **incrementally** to `output/google_maps_raw.csv`

#### Anti-Detection Strategy

> ⚠️ **CRITICAL:** Google Maps actively blocks headless Playwright scraping. Without stealth, you'll get CAPTCHAs within 10-20 requests.

| Technique | Implementation |
|---|---|
| **playwright-stealth** | Patches browser fingerprint to look like a real user |
| **Random delays** | 2-5 seconds between actions with jitter (not fixed intervals) |
| **Random mouse movements** | Move mouse naturally before clicking |
| **Headed mode option** | `--headful` flag for debugging when blocked |
| **User-Agent rotation** | Rotate between 10+ real Chrome UA strings |
| **Viewport randomization** | Slightly different window sizes per session |
| **`AutomationControlled` disabled** | Hides Playwright's automation flag |

#### Search Targets

| City | Keywords | Expected Leads | Notes |
|---|---|---|---|
| Jaipur | restaurants, cafes, hotels, bakeries | 200–400 | High density of local businesses |
| Delhi/NCR | restaurants, cafes, cloud kitchens | 500–1000 | Largest volume |
| Mumbai | restaurants, cafes, food joints | 500–800 | Competitive market |
| Bangalore | cafes, restaurants, co-working | 400–700 | Tech-savvy owners |
| Hyderabad | restaurants, cafes, bakeries | 300–500 | Growing market |
| Pune | cafes, restaurants, bakeries | 250–400 | High cafe density |

#### Code Logic (Step by Step)

1. Load environment variables from `.env`
2. Launch Playwright browser with stealth patches applied
3. Load `state.json` to check if resuming a previous run
4. Loop over `cities.json` — for each city × keyword pair
5. Navigate to `maps.google.com` and search
6. Scroll results panel to load all listings (with random delays)
7. Click each result → extract Name, Phone, Website, Address
8. **Append row to CSV immediately** (incremental save)
9. Update `state.json` with progress
10. Rate-limit: add **random 2–5 second delay** between requests

#### `scrapers/google_maps_scraper.py` — Full Structure

```python
import os
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── User Agent Rotation ────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# ─── State Management (Resume on Crash) ─────────────────
STATE_FILE = Path("output/state.json")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"completed": [], "last_run": None}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ─── Random Delay Helper ────────────────────────────────
def random_delay(min_sec=None, max_sec=None):
    min_sec = min_sec or float(os.getenv("MIN_DELAY", 2))
    max_sec = max_sec or float(os.getenv("MAX_DELAY", 5))
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)

# ─── CSV Append Helper (Incremental Save) ───────────────
def append_to_csv(row: dict, filepath: str):
    """Append a single row to CSV. Creates file with headers if it doesn't exist."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists():
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)

# ─── Main Scraper ────────────────────────────────────────
def scrape_city_keyword(city: str, keyword: str, headless: bool = True) -> list:
    """Scrape Google Maps for a single city × keyword combination."""
    results = []
    search_query = f"{keyword} in {city}"
    logger.info(f"Scraping: {search_query}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": random.randint(1200, 1400), "height": random.randint(800, 1000)},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        stealth_sync(page)  # Apply stealth patches

        try:
            # Navigate to Google Maps
            page.goto(
                f"https://www.google.com/maps/search/{keyword}+in+{city}",
                wait_until="networkidle",
                timeout=30000,
            )
            random_delay(3, 5)

            # Scroll the results panel to load all listings
            results_panel = page.locator('[role="feed"]')
            if results_panel.count() > 0:
                for scroll_attempt in range(15):  # Max 15 scrolls
                    results_panel.evaluate("el => el.scrollTop = el.scrollHeight")
                    random_delay(1.5, 3)
                    # Check if "end of results" indicator appears
                    end_marker = page.locator("text=You've reached the end of the list")
                    if end_marker.count() > 0:
                        logger.info(f"Reached end of results after {scroll_attempt + 1} scrolls")
                        break

            # Extract all listing links
            listings = page.locator('[role="feed"] a[href*="/maps/place/"]').all()
            logger.info(f"Found {len(listings)} listings for '{search_query}'")

            for i, listing in enumerate(listings):
                try:
                    listing.click()
                    random_delay(2, 4)

                    # Extract business details from the detail panel
                    name = page.locator("h1").first.text_content() or ""
                    
                    # Phone number
                    phone = ""
                    phone_el = page.locator('[data-item-id*="phone"] .Io6YTe')
                    if phone_el.count() > 0:
                        phone = phone_el.first.text_content() or ""

                    # Website
                    website = ""
                    website_el = page.locator('[data-item-id*="authority"] .Io6YTe')
                    if website_el.count() > 0:
                        website = website_el.first.text_content() or ""

                    # Address
                    address = ""
                    address_el = page.locator('[data-item-id*="address"] .Io6YTe')
                    if address_el.count() > 0:
                        address = address_el.first.text_content() or ""

                    # Rating
                    rating = ""
                    rating_el = page.locator('div.F7nice span[aria-hidden="true"]')
                    if rating_el.count() > 0:
                        rating = rating_el.first.text_content() or ""

                    # Category
                    category = ""
                    cat_el = page.locator('button.DkEaL')
                    if cat_el.count() > 0:
                        category = cat_el.first.text_content() or ""

                    row = {
                        "business_name": name.strip(),
                        "category": category.strip(),
                        "city": city,
                        "phone": phone.strip(),
                        "website": website.strip(),
                        "address": address.strip(),
                        "rating": rating.strip(),
                        "source": "google_maps",
                        "search_keyword": keyword,
                        "scraped_at": datetime.now().isoformat(),
                    }

                    if row["business_name"]:  # Only save if we got a name
                        results.append(row)
                        append_to_csv(row, "output/google_maps_raw.csv")
                        logger.info(f"  [{i+1}/{len(listings)}] {name.strip()} | {phone.strip()}")

                    random_delay()  # Random delay between listings

                except Exception as e:
                    logger.warning(f"  Failed to extract listing {i+1}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to scrape '{search_query}': {e}")
        finally:
            browser.close()

    return results

# ─── Entry Point ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Google Maps Lead Scraper")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode for debugging")
    parser.add_argument("--city", type=str, help="Scrape only this city")
    parser.add_argument("--keyword", type=str, help="Scrape only this keyword")
    args = parser.parse_args()

    headless = not args.headful
    state = load_state()

    with open("config/cities.json") as f:
        config = json.load(f)

    total_leads = 0
    for target in config["targets"]:
        city = target["city"]
        if args.city and city.lower() != args.city.lower():
            continue

        for keyword in target["keywords"]:
            if args.keyword and keyword.lower() != args.keyword.lower():
                continue

            task_key = f"gmaps:{city}:{keyword}"
            if task_key in state["completed"]:
                logger.info(f"Skipping (already done): {city} - {keyword}")
                continue

            leads = scrape_city_keyword(city, keyword, headless=headless)
            total_leads += len(leads)

            state["completed"].append(task_key)
            state["last_run"] = datetime.now().isoformat()
            save_state(state)

            random_delay(5, 10)  # Longer delay between city-keyword combos

    logger.info(f"✅ Google Maps scraping complete. Total leads: {total_leads}")

if __name__ == "__main__":
    main()
```

#### Output CSV Columns

| Column | Example Value |
|---|---|
| business_name | Brew & Bite Cafe |
| category | Cafe |
| city | Jaipur |
| phone | +91-9876543210 |
| website | https://brewandbite.in |
| address | C-12, Malviya Nagar, Jaipur |
| rating | 4.3 |
| source | google_maps |
| search_keyword | cafes |
| scraped_at | 2024-01-15T10:30:00 |

---

### Phase 2 — Justdial Scraper (Backup)

> ⏱ **Estimated Time:** 1–2 hours | **Priority:** 🟡 MEDIUM | **Data:** Phone, Address, Name, Category

#### What It Does
- Searches Justdial for restaurants/cafes in target cities
- Justdial has **explicit phone numbers** displayed on listings (easier than Google Maps)
- Less bot detection than Google — more reliable for Indian businesses
- Acts as a **backup/supplement** to Google Maps data

#### Why Justdial?
| Advantage | Detail |
|---|---|
| **Phone numbers displayed** | Unlike Google Maps, Justdial shows phone numbers directly in listings |
| **Indian business focus** | Justdial is specifically built for Indian local businesses |
| **Less bot detection** | Much easier to scrape than Google Maps |
| **Complementary data** | Catches businesses not listed on Google Maps |

#### Code Logic (Step by Step)

1. Navigate to `justdial.com/{city}/{keyword}`
2. Wait for listings to load
3. Extract: Business Name, Phone, Address, Category, Rating
4. Handle Justdial's phone number obfuscation (they use CSS sprites — need to decode)
5. Scroll to load more results
6. Append each row to CSV incrementally
7. Rate-limit with 3-5 second random delays

#### `scrapers/justdial_scraper.py` — Full Structure

```python
import os
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

STATE_FILE = Path("output/state.json")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"completed": [], "last_run": None}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def random_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))

def append_to_csv(row: dict, filepath: str):
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists():
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)

def scrape_justdial_city_keyword(city: str, keyword: str, headless: bool = True) -> list:
    """Scrape Justdial for a single city × keyword combination."""
    results = []
    # Justdial URL format: justdial.com/city/keyword
    url_keyword = keyword.replace(" ", "-")
    url = f"https://www.justdial.com/{city}/{url_keyword}"
    logger.info(f"Scraping Justdial: {city} - {keyword}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": random.randint(1200, 1400), "height": random.randint(800, 1000)},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        stealth_sync(page)

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            random_delay(3, 5)

            # Close any popups (Justdial often shows login/download prompts)
            try:
                close_btn = page.locator("span.popup_cls, .close-btn, #best_deal_close")
                if close_btn.count() > 0:
                    close_btn.first.click()
                    random_delay(1, 2)
            except:
                pass

            # Scroll to load more results
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                random_delay(2, 3)

            # Extract listings — Justdial uses specific CSS classes
            listing_cards = page.locator(".resultbox_info, .store-details, .jsx-s1, li.cntanr").all()
            logger.info(f"Found {len(listing_cards)} listings on Justdial")

            for i, card in enumerate(listing_cards):
                try:
                    # Business Name
                    name = ""
                    name_el = card.locator("h2, .lng_cont_name, .store-name span")
                    if name_el.count() > 0:
                        name = name_el.first.text_content() or ""

                    # Phone - Justdial obfuscates phones, try multiple selectors
                    phone = ""
                    phone_el = card.locator(".mobilesv, .contact-info a[href^='tel:'], .telnowrap")
                    if phone_el.count() > 0:
                        phone_text = phone_el.first.get_attribute("href") or phone_el.first.text_content() or ""
                        phone = phone_text.replace("tel:", "").strip()

                    # Address
                    address = ""
                    addr_el = card.locator(".cont_sw_addr, .mrehover, .comp-address span")
                    if addr_el.count() > 0:
                        address = addr_el.first.text_content() or ""

                    # Rating
                    rating = ""
                    rating_el = card.locator(".green-box, .total_hr_avg span, .rating span")
                    if rating_el.count() > 0:
                        rating = rating_el.first.text_content() or ""

                    row = {
                        "business_name": name.strip(),
                        "category": keyword,
                        "city": city,
                        "phone": phone.strip(),
                        "website": "",  # Justdial rarely shows websites
                        "address": address.strip(),
                        "rating": rating.strip(),
                        "source": "justdial",
                        "search_keyword": keyword,
                        "scraped_at": datetime.now().isoformat(),
                    }

                    if row["business_name"]:
                        results.append(row)
                        append_to_csv(row, "output/justdial_raw.csv")
                        logger.info(f"  [{i+1}/{len(listing_cards)}] {name.strip()} | {phone.strip()}")

                    random_delay(1, 2)

                except Exception as e:
                    logger.warning(f"  Failed to extract Justdial listing {i+1}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to scrape Justdial '{city}/{keyword}': {e}")
        finally:
            browser.close()

    return results

def main():
    parser = argparse.ArgumentParser(description="Justdial Lead Scraper")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--city", type=str, help="Scrape only this city")
    args = parser.parse_args()

    headless = not args.headful
    state = load_state()

    with open("config/cities.json") as f:
        config = json.load(f)

    total_leads = 0
    for target in config["targets"]:
        city = target["city"]
        if args.city and city.lower() != args.city.lower():
            continue

        for keyword in target["keywords"]:
            task_key = f"justdial:{city}:{keyword}"
            if task_key in state["completed"]:
                logger.info(f"Skipping (already done): {city} - {keyword}")
                continue

            leads = scrape_justdial_city_keyword(city, keyword, headless=headless)
            total_leads += len(leads)

            state["completed"].append(task_key)
            state["last_run"] = datetime.now().isoformat()
            save_state(state)

            random_delay(5, 10)

    logger.info(f"✅ Justdial scraping complete. Total leads: {total_leads}")

if __name__ == "__main__":
    main()
```

---

### Phase 3 — Google Search Results Scraper

> ⏱ **Estimated Time:** 2–3 hours | **Priority:** 🔴 HIGH | **Data:** Emails, Phones, LinkedIn profiles, Websites

#### What It Does
- Performs **Google Search queries** to find emails and contact info for businesses and SMMs
- Uses **Google Dork** techniques to extract data from public pages
- Searches for: business contact pages, LinkedIn profiles, email patterns
- **No login required** for any platform — all data comes from Google's public index

#### Search Strategy

| Target Type | Google Search Query | What We Extract |
|---|---|---|
| Restaurant emails | `"restaurants in Jaipur" "contact" "@gmail.com" OR "@yahoo.com"` | Emails from listing sites |
| Cafe contact pages | `"cafes in Delhi" contact email phone` | Emails + phones from websites |
| SMM on LinkedIn | `site:linkedin.com/in "social media manager" "Jaipur"` | Name, title, LinkedIn URL |
| SMM on LinkedIn | `site:linkedin.com/in "digital marketer" "Mumbai"` | Name, title, LinkedIn URL |
| Business websites | `"restaurants" "Bangalore" inurl:contact` | Email + phone from contact pages |
| Content creators | `"content creator" "{city}" "@gmail.com" OR "contact"` | Emails from bios/pages |

#### Email & Phone Extraction

```python
import re

# Email patterns to detect
EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

# Indian phone patterns
PHONE_REGEX = r"(?:\+91[\-\s]?)?(?:0)?[6-9]\d{4}[\-\s]?\d{5}"

# Patterns that hint at contact info in text
CONTACT_HINTS = [
    r"(?:email|mail|e-mail)\s*[:@]\s*(\S+@\S+)",
    r"(?:phone|call|tel|mob|mobile|whatsapp)\s*[:\-]\s*([\d\s\+\-()]{10,})",
    r"(?:contact\s+us|reach\s+us|get\s+in\s+touch)",
]
```

#### `scrapers/google_search_scraper.py` — Full Structure

```python
import os
import re
import json
import time
import random
import logging
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, unquote

import pandas as pd
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
PHONE_REGEX = r"(?:\+91[\-\s]?)?(?:0)?[6-9]\d{4}[\-\s]?\d{5}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

STATE_FILE = Path("output/state.json")

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"completed": [], "last_run": None}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def random_delay(min_sec=3, max_sec=7):
    time.sleep(random.uniform(min_sec, max_sec))

def append_to_csv(row: dict, filepath: str):
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([row])
    if path.exists():
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)

def extract_emails(text: str) -> list:
    """Extract all email addresses from text."""
    emails = re.findall(EMAIL_REGEX, text)
    # Filter out common false positives
    filtered = []
    for email in emails:
        email = email.lower().strip()
        if not any(fake in email for fake in ["example.com", "test.com", "email.com", "domain.com", "yourname@"]):
            filtered.append(email)
    return list(set(filtered))

def extract_phones(text: str) -> list:
    """Extract Indian phone numbers from text."""
    phones = re.findall(PHONE_REGEX, text)
    return list(set([p.strip() for p in phones]))

def search_google(page, query: str, max_results: int = 20) -> list:
    """Perform a Google search and extract results."""
    results = []
    logger.info(f"Google Search: {query}")

    try:
        # Navigate to Google
        page.goto(f"https://www.google.com/search?q={query}&num={max_results}&hl=en", 
                  wait_until="networkidle", timeout=30000)
        random_delay(2, 4)

        # Check for CAPTCHA
        if "unusual traffic" in (page.content() or "").lower():
            logger.warning("⚠️ Google CAPTCHA detected! Waiting 60 seconds...")
            time.sleep(60)
            return results

        # Extract search results
        search_results = page.locator("#search .g, #rso .g").all()
        
        for result in search_results[:max_results]:
            try:
                # Title
                title = ""
                title_el = result.locator("h3")
                if title_el.count() > 0:
                    title = title_el.first.text_content() or ""

                # URL
                url = ""
                link_el = result.locator("a")
                if link_el.count() > 0:
                    url = link_el.first.get_attribute("href") or ""

                # Snippet text (often contains emails/phones)
                snippet = ""
                snippet_el = result.locator(".VwiC3b, .st, [data-sncf]")
                if snippet_el.count() > 0:
                    snippet = snippet_el.first.text_content() or ""

                # Extract emails and phones from snippet
                full_text = f"{title} {snippet} {url}"
                emails = extract_emails(full_text)
                phones = extract_phones(full_text)

                results.append({
                    "title": title.strip(),
                    "url": url.strip(),
                    "snippet": snippet.strip(),
                    "emails_found": ", ".join(emails),
                    "phones_found": ", ".join(phones),
                    "is_linkedin": "linkedin.com/in" in url.lower(),
                })

            except Exception as e:
                logger.warning(f"Failed to extract search result: {e}")
                continue

    except Exception as e:
        logger.error(f"Google search failed for '{query}': {e}")

    return results

def visit_page_for_contacts(page, url: str) -> dict:
    """Visit a URL and scrape it for email addresses and phone numbers."""
    contacts = {"emails": [], "phones": []}
    
    # Skip certain domains
    skip_domains = ["google.com", "facebook.com", "twitter.com", "youtube.com", "wikipedia.org"]
    domain = urlparse(url).netloc.lower()
    if any(skip in domain for skip in skip_domains):
        return contacts

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        random_delay(2, 3)
        
        page_text = page.content() or ""
        contacts["emails"] = extract_emails(page_text)
        contacts["phones"] = extract_phones(page_text)

    except Exception as e:
        logger.debug(f"Could not visit {url}: {e}")

    return contacts

def scrape_google_search(city: str, keyword: str, headless: bool = True) -> list:
    """Run Google searches for a city × keyword and extract contacts."""
    results = []

    with open("config/search_queries.json") as f:
        query_templates = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": random.randint(1200, 1400), "height": random.randint(800, 1000)},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        stealth_sync(page)

        try:
            # Run business email queries
            for template in query_templates.get("business_email_queries", []):
                query = template.format(keyword=keyword, city=city)
                search_results = search_google(page, query, max_results=10)

                for sr in search_results:
                    # If snippet had contacts, save directly
                    if sr["emails_found"] or sr["phones_found"]:
                        for email in sr["emails_found"].split(", "):
                            row = {
                                "business_name": sr["title"],
                                "city": city,
                                "email": email,
                                "phone": sr["phones_found"].split(", ")[0] if sr["phones_found"] else "",
                                "website": sr["url"],
                                "source": "google_search",
                                "search_query": query,
                                "is_linkedin": sr["is_linkedin"],
                                "scraped_at": datetime.now().isoformat(),
                            }
                            results.append(row)
                            append_to_csv(row, "output/google_search_raw.csv")
                            logger.info(f"  Found: {email} ({sr['title'][:40]})")

                    # Optionally visit the page for deeper extraction
                    elif sr["url"] and not sr["is_linkedin"]:
                        contacts = visit_page_for_contacts(page, sr["url"])
                        for email in contacts["emails"][:3]:  # Max 3 emails per page
                            row = {
                                "business_name": sr["title"],
                                "city": city,
                                "email": email,
                                "phone": contacts["phones"][0] if contacts["phones"] else "",
                                "website": sr["url"],
                                "source": "google_search_deep",
                                "search_query": query,
                                "is_linkedin": False,
                                "scraped_at": datetime.now().isoformat(),
                            }
                            results.append(row)
                            append_to_csv(row, "output/google_search_raw.csv")
                            logger.info(f"  Deep found: {email} from {sr['url'][:50]}")

                random_delay(8, 15)  # Long delay between Google searches

            # Run SMM queries
            for template in query_templates.get("smm_queries", []):
                query = template.format(city=city)
                search_results = search_google(page, query, max_results=10)

                for sr in search_results:
                    if sr["is_linkedin"]:
                        # Extract name from LinkedIn result title
                        name = sr["title"].split(" - ")[0].split(" | ")[0].strip()
                        row = {
                            "business_name": name,
                            "city": city,
                            "email": sr["emails_found"].split(", ")[0] if sr["emails_found"] else "",
                            "phone": sr["phones_found"].split(", ")[0] if sr["phones_found"] else "",
                            "website": sr["url"],
                            "source": "google_search_linkedin",
                            "search_query": query,
                            "is_linkedin": True,
                            "scraped_at": datetime.now().isoformat(),
                        }
                        results.append(row)
                        append_to_csv(row, "output/google_search_raw.csv")
                        logger.info(f"  LinkedIn: {name} | {sr['url'][:60]}")

                random_delay(8, 15)

        except Exception as e:
            logger.error(f"Google search scraping failed: {e}")
        finally:
            browser.close()

    return results

def main():
    parser = argparse.ArgumentParser(description="Google Search Lead Scraper")
    parser.add_argument("--headful", action="store_true", help="Run browser in headed mode")
    parser.add_argument("--city", type=str, help="Scrape only this city")
    parser.add_argument("--smm-only", action="store_true", help="Only search for Social Media Managers")
    args = parser.parse_args()

    headless = not args.headful
    state = load_state()

    with open("config/cities.json") as f:
        config = json.load(f)

    total_leads = 0
    for target in config["targets"]:
        city = target["city"]
        if args.city and city.lower() != args.city.lower():
            continue

        if args.smm_only:
            # Only run SMM queries (no keywords needed)
            task_key = f"gsearch_smm:{city}"
            if task_key in state["completed"]:
                logger.info(f"Skipping SMM (already done): {city}")
                continue

            leads = scrape_google_search(city, "", headless=headless)
            total_leads += len(leads)
            state["completed"].append(task_key)
            save_state(state)
        else:
            for keyword in target["keywords"]:
                task_key = f"gsearch:{city}:{keyword}"
                if task_key in state["completed"]:
                    logger.info(f"Skipping (already done): {city} - {keyword}")
                    continue

                leads = scrape_google_search(city, keyword, headless=headless)
                total_leads += len(leads)
                state["completed"].append(task_key)
                state["last_run"] = datetime.now().isoformat()
                save_state(state)

                random_delay(15, 30)  # Very long delay between batches for Google

    logger.info(f"✅ Google Search scraping complete. Total leads: {total_leads}")

if __name__ == "__main__":
    main()
```

---

### Phase 4 — Data Cleaner & Google Sheets Uploader

> ⏱ **Estimated Time:** 1.5–2 hours | **Priority:** 🔴 HIGH | **Makes data usable**

#### Install

```bash
pip install pandas phonenumbers gspread google-auth python-dotenv
```

#### `processor/cleaner.py` — Logic (Step by Step)

1. Load all CSVs from `output/` folder (`*_raw.csv`)
2. Standardize phone numbers using `phonenumbers` library → format: `+91XXXXXXXXXX`
3. Validate email format using regex
4. Remove duplicates — match by **phone OR email**
5. Remove rows with no phone AND no email
6. Add `status` column defaulting to `"New"`
7. Add `date_added` column with today's date
8. Save to `output/leads_clean.csv`

```python
import os
import re
import logging
from pathlib import Path
from datetime import date

import pandas as pd
import phonenumbers
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

def normalize_phone(phone_str) -> str | None:
    """Normalize phone number to E.164 format (+91XXXXXXXXXX)."""
    if not phone_str or pd.isna(phone_str):
        return None
    try:
        # Try parsing as Indian number
        p = phonenumbers.parse(str(phone_str), "IN")
        if phonenumbers.is_valid_number(p):
            return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return None

def validate_email(email) -> str | None:
    """Validate and normalize email address."""
    if not email or pd.isna(email):
        return None
    email = str(email).lower().strip()
    # Filter out obviously fake emails
    fake_patterns = ["example.com", "test.com", "domain.com", "yourname@", "email@email",
                     "noreply", "no-reply", "donotreply", "sentry", "wixpress"]
    if any(fake in email for fake in fake_patterns):
        return None
    if re.match(EMAIL_REGEX, email):
        return email
    return None

def clean_all():
    """Load all raw CSVs, clean, deduplicate, and save."""
    output_dir = Path("output")
    dfs = []

    # Load all raw CSV files
    for csv_file in output_dir.glob("*_raw.csv"):
        try:
            df = pd.read_csv(csv_file, dtype=str)
            logger.info(f"Loaded {len(df)} rows from {csv_file.name}")
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Failed to load {csv_file.name}: {e}")

    if not dfs:
        logger.warning("No raw CSV files found in output/")
        return

    # Combine all dataframes
    df = pd.concat(dfs, ignore_index=True)
    logger.info(f"Total raw rows: {len(df)}")

    # Normalize phone numbers
    if "phone" in df.columns:
        df["phone"] = df["phone"].apply(normalize_phone)
    else:
        df["phone"] = None

    # Validate emails
    if "email" in df.columns:
        df["email"] = df["email"].apply(validate_email)
    else:
        df["email"] = None

    # Remove rows with no phone AND no email
    df = df[df["phone"].notna() | df["email"].notna()]
    logger.info(f"After removing rows with no contact info: {len(df)}")

    # Remove duplicates by phone (keep first occurrence)
    phone_mask = df["phone"].notna()
    df_with_phone = df[phone_mask].drop_duplicates(subset=["phone"], keep="first")
    df_without_phone = df[~phone_mask]
    df = pd.concat([df_with_phone, df_without_phone], ignore_index=True)

    # Remove duplicates by email (keep first occurrence)
    email_mask = df["email"].notna()
    df_with_email = df[email_mask].drop_duplicates(subset=["email"], keep="first")
    df_without_email = df[~email_mask]
    df = pd.concat([df_with_email, df_without_email], ignore_index=True)

    logger.info(f"After deduplication: {len(df)}")

    # Add metadata columns
    df["status"] = "New"
    df["date_added"] = str(date.today())

    # Standardize column order
    final_columns = [
        "business_name", "category", "city", "phone", "email",
        "website", "address", "rating", "source", "date_added", "status"
    ]
    # Only include columns that exist
    existing_cols = [c for c in final_columns if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in existing_cols]
    df = df[existing_cols + remaining_cols]

    # Save clean CSV
    clean_path = output_dir / "leads_clean.csv"
    df.to_csv(clean_path, index=False)
    logger.info(f"✅ Clean leads saved: {len(df)} rows → {clean_path}")

    # Print summary
    logger.info("─── Summary ───")
    logger.info(f"  Total clean leads: {len(df)}")
    logger.info(f"  With phone: {df['phone'].notna().sum()}")
    logger.info(f"  With email: {df['email'].notna().sum()}")
    if "city" in df.columns:
        logger.info(f"  By city: {df['city'].value_counts().to_dict()}")
    if "source" in df.columns:
        logger.info(f"  By source: {df['source'].value_counts().to_dict()}")

if __name__ == "__main__":
    clean_all()
```

#### Google Sheets Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → Create new project
2. Enable **Google Sheets API** and **Google Drive API**
3. Create Service Account → Download JSON key file
4. Save as `config/credentials.json`
5. Create a new Google Sheet → Share it with the service account email (Editor access)
6. Copy the Sheet ID from the URL → Add to `.env` as `GOOGLE_SHEET_ID`

#### `processor/sheets_uploader.py`

```python
import os
import logging
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

def upload_to_sheets():
    """Upload clean leads to Google Sheets, appending only new rows."""
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")

    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID not set in .env")
        return

    if not Path(creds_path).exists():
        logger.error(f"Credentials file not found: {creds_path}")
        return

    clean_csv = Path("output/leads_clean.csv")
    if not clean_csv.exists():
        logger.error("Clean CSV not found. Run cleaner.py first.")
        return

    # Authenticate
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(sheet_id).sheet1

    # Load clean data
    df = pd.read_csv(clean_csv, dtype=str).fillna("")
    logger.info(f"Clean CSV has {len(df)} rows")

    # Get existing data from sheet
    existing = sheet.get_all_records()
    existing_phones = {str(r.get("phone", "")) for r in existing if r.get("phone")}
    existing_emails = {str(r.get("email", "")).lower() for r in existing if r.get("email")}

    # Filter to only new rows
    new_rows = []
    for _, row in df.iterrows():
        phone = str(row.get("phone", ""))
        email = str(row.get("email", "")).lower()
        
        is_duplicate = False
        if phone and phone in existing_phones:
            is_duplicate = True
        if email and email in existing_emails:
            is_duplicate = True
        
        if not is_duplicate:
            new_rows.append(row.tolist())

    if new_rows:
        # If sheet is empty, add headers first
        if not existing:
            sheet.update("A1", [df.columns.tolist()])

        # Batch upload new rows (faster than row-by-row)
        batch_size = 100
        for i in range(0, len(new_rows), batch_size):
            batch = new_rows[i:i + batch_size]
            sheet.append_rows(batch, value_input_option="RAW")
            logger.info(f"Uploaded batch {i//batch_size + 1} ({len(batch)} rows)")

        logger.info(f"✅ Uploaded {len(new_rows)} new leads to Google Sheets")
    else:
        logger.info("No new leads to upload (all duplicates)")

    return len(new_rows)

if __name__ == "__main__":
    upload_to_sheets()
```

#### Master Lead DB — Final Column Structure

| Column | Type | Example | Notes |
|---|---|---|---|
| business_name | Text | Brew & Bite Cafe | |
| category | Text | Cafe | Restaurant / Cafe / SMM |
| city | Text | Jaipur | One of 6 target cities |
| phone | Text | +919876543210 | E.164 format |
| email | Text | hi@cafe.com | Validated format |
| website | Text | https://cafe.com | |
| address | Text | C-12, Malviya Nagar | |
| rating | Text | 4.3 | |
| source | Text | google_maps | google_maps / justdial / google_search |
| date_added | Date | 2024-01-15 | Auto timestamp |
| status | Dropdown | New | New / Contacted / Replied |

---

### Phase 5 — n8n Automation Setup

> ⏱ **Estimated Time:** 1–2 hours | **Priority:** 🔴 HIGH | **Makes everything run automatically**

#### Installing n8n (Self-hosted)

```bash
# Install n8n globally
npm install -g n8n

# Start n8n
n8n start

# Open in browser
# http://localhost:5678
```

> You already have n8n running at `vikashcloud.duckdns.org` — we'll deploy directly there.

#### n8n Workflow Design

```
 ┌──────────────┐     ┌───────────────────┐     ┌───────────────────┐
 │  Schedule     │────▶│ Execute Command   │────▶│ Execute Command   │
 │  Trigger      │     │ Google Maps       │     │ Justdial          │
 │  (Daily 9AM)  │     │ Scraper           │     │ Scraper           │
 └──────────────┘     └───────────────────┘     └───────────────────┘
                                                          │
                                                          ▼
 ┌──────────────┐     ┌───────────────────┐     ┌───────────────────┐
 │  Telegram     │◀────│ Execute Command   │◀────│ Execute Command   │
 │  Alert        │     │ Cleaner +         │     │ Google Search     │
 │  "X new leads"│     │ Sheets Uploader   │     │ Scraper           │
 └──────────────┘     └───────────────────┘     └───────────────────┘
         │
         ▼
 ┌──────────────┐
 │  Error        │
 │  Trigger      │──── Sends failure alert via Telegram
 └──────────────┘
```

| Node | Type | Function |
|---|---|---|
| 1. Schedule Trigger | `scheduleTrigger` | Runs every day at 9 AM IST |
| 2. Execute Command (Maps) | `executeCommand` | Runs `python scrapers/google_maps_scraper.py` |
| 3. Execute Command (Justdial) | `executeCommand` | Runs `python scrapers/justdial_scraper.py` |
| 4. Execute Command (Google Search) | `executeCommand` | Runs `python scrapers/google_search_scraper.py` |
| 5. Execute Command (Cleaner) | `executeCommand` | Runs `python processor/cleaner.py && python processor/sheets_uploader.py` |
| 6. Telegram Node | `telegram` | Sends alert: "✅ X new leads added today!" |
| 7. Error Trigger | `errorTrigger` | Catches any failures → sends Telegram alert |

#### Telegram Alert Setup

1. Message **@BotFather** on Telegram → `/newbot` → get your Bot Token
2. Get your Chat ID by messaging **@userinfobot**
3. Put both in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```
4. Message templates:
   ```
   ✅ SUCCESS:
   🎯 Lead Gen Update
   ✅ New leads added: {count}
   📊 Total in database: {total}
   🏙 Cities: Jaipur, Delhi, Mumbai, Bangalore, Hyderabad, Pune
   
   ❌ FAILURE:
   🚨 Lead Gen ERROR
   ❌ Pipeline failed at: {node_name}
   📋 Error: {error_message}
   🔧 Check n8n dashboard for details
   ```

---

### Phase 6 — Maintenance & Scaling

#### Weekly Maintenance Tasks
- [ ] Check Google Sheets for any duplicate entries
- [ ] Update `status` column as you contact leads
- [ ] Review scraper logs for errors or IP blocks
- [ ] Clear `state.json` to allow re-scraping (or run with `--city` flag for specific cities)
- [ ] Monitor n8n execution history for failures

#### How to Scale (When Ready)
- Add more city keywords to `cities.json` — no code change needed
- Add new business types: clothing brands, real estate, salons, gyms etc.
- Add more search query templates to `search_queries.json`
- Integrate **Apollo.io free tier** (50 credits/month) for email enrichment
- Add **email sending automation** in n8n (Gmail node) for cold outreach sequences
- Add a **Supabase database** instead of Google Sheets when you exceed 5,000 leads
- Integrate **proxy rotation** from your existing `Proxy Scripts` folder

#### Reset Scraper State
```bash
# Reset all progress (re-scrape everything)
echo '{"completed": [], "last_run": null}' > output/state.json

# Reset only Google Maps progress
python -c "
import json
state = json.load(open('output/state.json'))
state['completed'] = [k for k in state['completed'] if not k.startswith('gmaps:')]
json.dump(state, open('output/state.json', 'w'), indent=2)
"
```

---

## 4. Installation & Setup Checklist

### 4.1 Prerequisites
- [ ] Python 3.11+ installed
- [ ] Node.js 18+ installed (for n8n)
- [ ] Google Chrome installed (for Playwright)
- [ ] A Google account (for Sheets API)
- [ ] A Telegram account (for notifications)

### 4.2 Full Install Commands

```bash
# 1. Create project and virtual environment
mkdir lead-gen-system && cd lead-gen-system
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install all Python dependencies
pip install playwright playwright-stealth pandas phonenumbers gspread google-auth python-dotenv

# 3. Install Playwright browser
playwright install chromium

# 4. Install n8n (if not already installed)
npm install -g n8n

# 5. Create folder structure
mkdir -p scrapers/utils processor config output n8n

# 6. Create .env from template
cp .env.example .env

# 7. Save dependencies
pip freeze > requirements.txt
```

### 4.3 `requirements.txt`

```
playwright
playwright-stealth
pandas
phonenumbers
gspread
google-auth
python-dotenv
```

### 4.4 `.gitignore`

```
# Environment
.env
.env.local
venv/

# Credentials
config/credentials.json

# Output data
output/*.csv
output/state.json

# Python
__pycache__/
*.pyc

# OS
.DS_Store
Thumbs.db
```

---

## 5. Build Timeline

| Phase | Task | Time | Priority | Output |
|---|---|---|---|---|
| Phase 1 | Google Maps Scraper (with stealth) | 2–3 hrs | 🔴 HIGH | CSV with phone + address |
| Phase 2 | Justdial Scraper (backup source) | 1–2 hrs | 🟡 MEDIUM | CSV with phone + address |
| Phase 3 | Google Search Results Scraper | 2–3 hrs | 🔴 HIGH | CSV with emails + LinkedIn profiles |
| Phase 4 | Data Cleaner + Sheets Sync | 1.5–2 hrs | 🔴 HIGH | Clean Master Google Sheet |
| Phase 5 | n8n Automation + Telegram | 1–2 hrs | 🔴 HIGH | Fully automated pipeline |
| Phase 6 | Testing + Edge Cases | 1.5 hrs | 🔴 HIGH | Production-ready system |
| **TOTAL** | **Complete System** | **~12 hrs** | | **500–3000 leads/week** |

---

## 6. Known Risks & Solutions

| Risk | Solution |
|---|---|
| Google Maps blocks your IP | `playwright-stealth` + random delays (2–5 sec) + UA rotation |
| Google Search shows CAPTCHA | Long delays (8–15 sec between searches) + limit to 10 results per query |
| Justdial changes HTML structure | Use multiple CSS selectors with fallbacks |
| No email found for a lead | Use website URL → Phase 3 deep scraper visits the website |
| Duplicate entries in Sheet | `cleaner.py` deduplicates by phone + email before upload |
| Scraper crashes mid-run | `state.json` tracks progress → auto-resume on restart |
| n8n workflow crashes | Error Trigger node → sends Telegram failure alert |
| IP gets permanently blocked | Integrate proxy rotation from your `Proxy Scripts` folder |

---

## 7. Quick Reference Commands

```bash
# ─── Run individual scrapers ────────────────
python scrapers/google_maps_scraper.py                    # Run Google Maps scraper
python scrapers/google_maps_scraper.py --headful          # Run with visible browser (debugging)
python scrapers/google_maps_scraper.py --city Jaipur      # Scrape only Jaipur
python scrapers/justdial_scraper.py                       # Run Justdial scraper
python scrapers/justdial_scraper.py --headful             # Run with visible browser
python scrapers/google_search_scraper.py                  # Run Google Search scraper
python scrapers/google_search_scraper.py --smm-only       # Only search for Social Media Managers

# ─── Run cleaner + upload ───────────────────
python processor/cleaner.py                               # Clean and deduplicate all data
python processor/sheets_uploader.py                       # Upload clean data to Google Sheets

# ─── Full pipeline (one command) ────────────
python scrapers/google_maps_scraper.py && \
python scrapers/justdial_scraper.py && \
python scrapers/google_search_scraper.py && \
python processor/cleaner.py && \
python processor/sheets_uploader.py

# ─── Reset scraper progress ────────────────
echo '{"completed": [], "last_run": null}' > output/state.json

# ─── Start n8n ──────────────────────────────
n8n start
```

---

> 💡 **Tip:** Build Phase 1 first, validate the output CSV manually, then move to Phase 2.  
> Each phase is independent and produces working output on its own.
> Use `--headful` flag when debugging to see exactly what the browser is doing.
