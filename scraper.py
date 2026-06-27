import requests
import csv
import time
import os
import re
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL       = "https://www.mudah.my/malaysia/properties-for-sale"
ADSBY          = "false"   # matches ?adsby=false in the URL
MAX_PAGES      = 5
SLEEP_BETWEEN  = 2         # seconds between requests

OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_all.csv")

CSV_FIELDS = [
    "listing_id", "title", "price", "location", "state",
    "beds", "baths", "size_sqft", "property_type",
    "url", "scraped_at",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.mudah.my/",
}

# Mudah's internal API endpoint
API_URL = "https://search.mudah.my/v1/search"

# ── Fetch via Mudah's search API ─────────────────────────────────────────────
def fetch_page(page: int) -> list[dict]:
    """
    Call Mudah's search API for one page of property listings.
    Falls back to HTML scraping if the API call fails.
    """
    params = {
        "category":    "1000",      # Properties
        "ad_type":     "s",         # For sale
        "limit":       "30",
        "from":        str((page - 1) * 30),
        "adsby":       ADSBY,
        "o":           str(page),
    }

    try:
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        listings = []
        ads = data.get("data", {}).get("ads", []) or data.get("ads", []) or []

        for ad in ads:
            attrs = ad.get("attributes", {})

            # Extract nested attribute value safely
            def attr(key):
                v = attrs.get(key, {})
                if isinstance(v, dict):
                    return v.get("value", "N/A")
                return v or "N/A"

            listing_id = str(ad.get("list_id") or ad.get("id", "N/A"))
            title      = ad.get("subject", "N/A")
            price_raw  = ad.get("price", {})
            price      = price_raw.get("value", "N/A") if isinstance(price_raw, dict) else str(price_raw)
            region     = ad.get("region", "N/A")
            state      = ad.get("state_name") or ad.get("region_name", "N/A")
            prop_type  = attr("property_type") or attr("category_name")
            beds       = attr("rooms")
            baths      = attr("bathrooms")
            size       = attr("size")

            link = ad.get("url") or f"https://www.mudah.my/ad/{listing_id}.htm"

            listings.append({
                "listing_id":   listing_id,
                "title":        title,
                "price":        price,
                "location":     region,
                "state":        state,
                "beds":         beds,
                "baths":        baths,
                "size_sqft":    size,
                "property_type": prop_type,
                "url":          link,
                "scraped_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        return listings

    except Exception as e:
        print(f"     ⚠️  API call failed: {e}")
        return fetch_page_html(page)   # fallback


# ── HTML fallback scraper ─────────────────────────────────────────────────────
def fetch_page_html(page: int) -> list[dict]:
    """Fallback: scrape the HTML listing page directly."""
    if page == 1:
        url = f"{BASE_URL}?adsby={ADSBY}"
    else:
        url = f"{BASE_URL}?adsby={ADSBY}&o={page}"

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    # Mudah embeds listing data as JSON inside a <script> tag
    # Pattern: window.__INITIAL_STATE__ = {...}
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", resp.text, re.DOTALL)
    if not match:
        print("     ⚠️  Could not find embedded JSON in page HTML")
        return []

    import json
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"     ⚠️  JSON parse error: {e}")
        return []

    # Navigate into the state tree to find ads
    # Structure varies but typically: listings.listingData.ads
    ads = (
        state.get("listings", {}).get("listingData", {}).get("ads", [])
        or state.get("adList", {}).get("ads", [])
        or []
    )

    listings = []
    for ad in ads:
        listing_id = str(ad.get("list_id") or ad.get("id", "N/A"))
        title      = ad.get("subject", "N/A")
        price      = str(ad.get("price", {}).get("value", "N/A"))
        region     = ad.get("region", "N/A")
        state_name = ad.get("state_name", "N/A")
        link       = ad.get("url", f"https://www.mudah.my/ad/{listing_id}.htm")

        attrs  = ad.get("attributes", {})
        beds   = attrs.get("rooms", {}).get("value", "N/A")
        baths  = attrs.get("bathrooms", {}).get("value", "N/A")
        size   = attrs.get("size", {}).get("value", "N/A")
        ptype  = attrs.get("property_type", {}).get("value", "N/A")

        listings.append({
            "listing_id":    listing_id,
            "title":         title,
            "price":         price,
            "location":      region,
            "state":         state_name,
            "beds":          beds,
            "baths":         baths,
            "size_sqft":     size,
            "property_type": ptype,
            "url":           link,
            "scraped_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    return listings


# ── Scrape all pages ──────────────────────────────────────────────────────────
def scrape_all() -> list[dict]:
    all_listings = []
    for page in range(1, MAX_PAGES + 1):
        print(f"  📄 Page {page} …")
        try:
            items = fetch_page(page)
            print(f"     → {len(items)} listings")
            all_listings.extend(items)
        except Exception as e:
            print(f"     ❌ Error: {e}")
        time.sleep(SLEEP_BETWEEN)
    return all_listings


# ── CSV helpers ───────────────────────────────────────────────────────────────
def load_existing_ids(filepath: str) -> set:
    if not os.path.exists(filepath):
        return set()
    with open(filepath, newline="", encoding="utf-8") as f:
        return {row["listing_id"] for row in csv.DictReader(f) if row.get("listing_id")}


def save_csv(filepath: str, rows: list, mode: str = "w"):
    write_header = (mode == "w") or (not os.path.exists(filepath))
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n🏠 Mudah Property Scraper — {TODAY}")
    print("=" * 45)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    existing_ids = load_existing_ids(MASTER_FILE)
    print(f"\n📂 Known listings in master file: {len(existing_ids)}")

    print(f"\n🌐 Scraping up to {MAX_PAGES} pages …")
    listings = scrape_all()
    print(f"\n📦 Total scraped this run: {len(listings)}")

    new_listings = [
        l for l in listings
        if l["listing_id"] not in existing_ids and l["listing_id"] != "N/A"
    ]
    print(f"✨ New (not seen before): {len(new_listings)}")

    if new_listings:
        save_csv(OUTPUT_FILE, new_listings, mode="w")
        print(f"💾 Daily file  → {OUTPUT_FILE}")
        save_csv(MASTER_FILE, new_listings, mode="a")
        print(f"💾 Master file → {MASTER_FILE}")
    else:
        print("ℹ️  No new listings today.")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
