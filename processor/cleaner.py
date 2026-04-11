"""
Data Cleaner
=============
Loads all raw CSVs from output/, normalizes phone numbers and emails,
deduplicates, and saves a clean master CSV.

Usage:
    python processor/cleaner.py
"""

import os
import sys
import re
import logging
from pathlib import Path
from datetime import date

import pandas as pd
import phonenumbers
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

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

# Domains and patterns that indicate fake/useless emails
FAKE_EMAIL_PATTERNS = [
    "example.com", "test.com", "domain.com", "yourname@", "email@email",
    "noreply", "no-reply", "donotreply", "sentry.io", "wixpress.com",
    "w3.org", "schema.org", "googleapis.com", "gstatic.com",
]


def normalize_phone(phone_str) -> str | None:
    """Normalize a phone number to E.164 format (+91XXXXXXXXXX)."""
    if not phone_str or pd.isna(phone_str):
        return None

    phone_str = str(phone_str).strip()
    if not phone_str:
        return None

    # Clean up common formatting
    phone_str = re.sub(r"[\s\-\(\)]", "", phone_str)

    try:
        p = phonenumbers.parse(phone_str, "IN")
        if phonenumbers.is_valid_number(p):
            return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass

    # Fallback: if it looks like a 10-digit Indian number, try with +91 prefix
    cleaned = re.sub(r"[^\d]", "", phone_str)
    if len(cleaned) == 10 and cleaned[0] in "6789":
        try:
            p = phonenumbers.parse(f"+91{cleaned}", None)
            if phonenumbers.is_valid_number(p):
                return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            pass

    return None


def validate_email(email) -> str | None:
    """Validate and normalize an email address."""
    if not email or pd.isna(email):
        return None

    email = str(email).lower().strip().rstrip(".")

    if not email:
        return None

    # Check against fake patterns
    if any(fake in email for fake in FAKE_EMAIL_PATTERNS):
        return None

    # Basic format validation
    if re.match(EMAIL_REGEX, email):
        return email

    return None


def clean_all():
    """Load all raw CSVs, clean, deduplicate, and save a master clean CSV."""
    output_dir = Path("output")
    dfs = []

    # Load all raw CSV files
    for csv_file in sorted(output_dir.glob("*_raw.csv")):
        try:
            df = pd.read_csv(csv_file, dtype=str)
            logger.info(f"📂 Loaded {len(df):>5} rows from {csv_file.name}")
            dfs.append(df)
        except Exception as e:
            logger.warning(f"❌ Failed to load {csv_file.name}: {e}")

    if not dfs:
        logger.warning("No raw CSV files found in output/. Run scrapers first.")
        return 0

    # Combine all dataframes
    df = pd.concat(dfs, ignore_index=True)
    initial_count = len(df)
    logger.info(f"\n📊 Total raw rows: {initial_count}")

    # ── Normalize phone numbers ──
    if "phone" in df.columns:
        df["phone"] = df["phone"].apply(normalize_phone)
        phone_count = df["phone"].notna().sum()
        logger.info(f"📞 Valid phones after normalization: {phone_count}")
    else:
        df["phone"] = None

    # ── Validate emails ──
    if "email" in df.columns:
        df["email"] = df["email"].apply(validate_email)
        email_count = df["email"].notna().sum()
        logger.info(f"📧 Valid emails after validation: {email_count}")
    else:
        df["email"] = None

    # ── Remove rows with NO contact info at all ──
    df = df[df["phone"].notna() | df["email"].notna()]
    logger.info(f"🧹 After removing rows with no contact info: {len(df)}")

    # ── Deduplicate by phone ──
    before_dedup = len(df)
    phone_mask = df["phone"].notna()
    df_with_phone = df[phone_mask].drop_duplicates(subset=["phone"], keep="first")
    df_without_phone = df[~phone_mask]
    df = pd.concat([df_with_phone, df_without_phone], ignore_index=True)
    logger.info(f"🔄 After phone dedup: {len(df)} (removed {before_dedup - len(df)} duplicates)")

    # ── Deduplicate by email ──
    before_dedup = len(df)
    email_mask = df["email"].notna()
    df_with_email = df[email_mask].drop_duplicates(subset=["email"], keep="first")
    df_without_email = df[~email_mask]
    df = pd.concat([df_with_email, df_without_email], ignore_index=True)
    logger.info(f"🔄 After email dedup: {len(df)} (removed {before_dedup - len(df)} duplicates)")

    # ── Also deduplicate by business name + city (fuzzy prevention) ──
    if "business_name" in df.columns and "city" in df.columns:
        before_dedup = len(df)
        name_mask = df["business_name"].notna() & df["city"].notna()
        df_with_name = df[name_mask].drop_duplicates(subset=["business_name", "city"], keep="first")
        df_without_name = df[~name_mask]
        df = pd.concat([df_with_name, df_without_name], ignore_index=True)
        logger.info(f"🔄 After name+city dedup: {len(df)} (removed {before_dedup - len(df)} duplicates)")

    # ── Add metadata columns ──
    df["status"] = "New"
    df["date_added"] = str(date.today())

    # ── Standardize column order ──
    priority_columns = [
        "business_name", "category", "city", "phone", "email",
        "website", "address", "rating", "source", "date_added", "status",
    ]
    existing_cols = [c for c in priority_columns if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in existing_cols]
    df = df[existing_cols + remaining_cols]

    # ── Save clean CSV ──
    clean_path = output_dir / "leads_clean.csv"
    df.to_csv(clean_path, index=False)

    # ── Print Summary ──
    logger.info("")
    logger.info("═══════════════════════════════════════════")
    logger.info(f"🎯 CLEANING COMPLETE")
    logger.info(f"   Raw input rows:  {initial_count}")
    logger.info(f"   Clean output:    {len(df)}")
    logger.info(f"   Removed:         {initial_count - len(df)}")
    logger.info(f"   With phone:      {df['phone'].notna().sum()}")
    logger.info(f"   With email:      {df['email'].notna().sum()}")
    if "city" in df.columns:
        logger.info(f"   By city:")
        for city, count in df["city"].value_counts().items():
            logger.info(f"     {city}: {count}")
    if "source" in df.columns:
        logger.info(f"   By source:")
        for source, count in df["source"].value_counts().items():
            logger.info(f"     {source}: {count}")
    logger.info(f"   Output: {clean_path}")
    logger.info("═══════════════════════════════════════════")

    return len(df)


if __name__ == "__main__":
    clean_all()
