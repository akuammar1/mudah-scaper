
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import csv
import time
import os
import re

# ── Config ───────────────────────────────────────────────────────────────────
MUDAH_URL  = "https://www.mudah.my/malaysia/properties-for-sale"
HEADERS    = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_PAGES      = 5   # pages to scrape per run
SLEEP_BETWEEN  = 2   # seconds between requests

# Output folder & file
OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_all.csv")   # cumulative file

CSV_FIELDS = [
    "listing_id", "title", "price", "location",
    "beds", "baths", "size", "url", "scraped_at",
]

# ── Scraping ─────────────────────────────────────────────────────────────────
def scrape_page(url: str) -> list[dict]:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    listings = []
    for item in soup.select("li[class*='listing']"):
        try:
            title_el = item.select_one("h2, [class*='title']")
            title    = title_el.get_text(strip=True) if title_el else "N/A"

            price_el = item.select_one("[class*='price']")
            price    = price_el.get_text(strip=True) if price_el else "N/A"

            loc_el   = item.select_one("[class*='location'], [class*='region']")
            location = loc_el.get_text(strip=True) if loc_el else "N/A"

            link_el  = item.select_one("a[href]")
            link     = link_el["href"] if link_el else "N/A"
            if link != "N/A" and not link.startswith("http"):
                link = "https://www.mudah.my" + link

            listing_id = re.search(r"-(\d+)\.htm", link)
            listing_id = listing_id.group(1) if listing_id else "N/A"

            beds_el  = item.select_one("[class*='bed'], [data-beds]")
            beds     = beds_el.get_text(strip=True) if beds_el else "N/A"

            baths_el = item.select_one("[class*='bath'], [data-baths]")
            baths    = baths_el.get_text(strip=True) if baths_el else "N/A"

            size_el  = item.select_one("[class*='size'], [class*='sqft']")
            size     = size_el.get_text(strip=True) if size_el else "N/A"

            listings.append({
                "listing_id": listing_id,
                "title":      title,
                "price":      price,
                "location":   location,
                "beds":       beds,
                "baths":      baths,
                "size":       size,
                "url":        link,
                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        except Exception as e:
            print(f"  ⚠️  Skipped one item: {e}")

    return listings


def scrape_all() -> list[dict]:
    all_listings = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{MUDAH_URL}?o={page}"
        print(f"  📄 Page {page}: {url}")
        try:
            items = scrape_page(url)
            print(f"     → {len(items)} listings found")
            all_listings.extend(items)
        except Exception as e:
            print(f"     ❌ Error: {e}")
        time.sleep(SLEEP_BETWEEN)
    return all_listings


# ── CSV helpers ───────────────────────────────────────────────────────────────
def load_existing_ids(filepath: str) -> set[str]:
    """Read listing IDs already saved in the master CSV."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["listing_id"] for row in reader if row.get("listing_id")}


def save_csv(filepath: str, rows: list[dict], mode: str = "w"):
    """Write rows to a CSV file. mode='a' to append, 'w' to overwrite."""
    write_header = (mode == "w") or (not os.path.exists(filepath))
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n🏠 Mudah Scraper — {TODAY}")
    print("=" * 45)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load IDs we've seen before (deduplication)
    existing_ids = load_existing_ids(MASTER_FILE)
    print(f"\n📂 Existing listings in master file: {len(existing_ids)}")

    print(f"\n🌐 Scraping up to {MAX_PAGES} pages …")
    listings = scrape_all()
    print(f"\n📦 Total scraped this run: {len(listings)}")

    # Filter out duplicates
    new_listings = [
        l for l in listings
        if l["listing_id"] not in existing_ids and l["listing_id"] != "N/A"
    ]
    print(f"✨ New listings (not seen before): {len(new_listings)}")

    if new_listings:
        # 1. Daily file — today's new listings only
        save_csv(OUTPUT_FILE, new_listings, mode="w")
        print(f"💾 Saved daily file  → {OUTPUT_FILE}")

        # 2. Master file — append new listings
        save_csv(MASTER_FILE, new_listings, mode="a")
        print(f"💾 Updated master    → {MASTER_FILE}")
    else:
        print("ℹ️  No new listings to save today.")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
