import requests
import json
import re
import csv
import os
import time
from datetime import datetime

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

BASE_URL      = "https://www.mudah.my/penang/properties-for-sale"
MAX_PAGES     = 50
SLEEP_BETWEEN = 5
RETRY_WAIT    = 60

OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_penang_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_penang_all.csv")

CSV_FIELDS = [
    "listing_id", "title", "price", "location", "state",
    "beds", "baths", "size_sqft", "property_type", "title_type",
    "phone", "url", "scraped_at",
]


def page_url(page):
    if page == 1:
        return f"{BASE_URL}?adsby=false"
    return f"{BASE_URL}?adsby=false&o={page}"


def fetch_with_retry(url, retries=3):
    for attempt in range(1, retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        print(f"     HTTP {resp.status_code} | {len(resp.text)} chars")
        if resp.status_code == 200:
            return resp
        elif resp.status_code == 429:
            if attempt < retries:
                print(f"     ⏳ Rate limited (attempt {attempt}/{retries}) — waiting {RETRY_WAIT}s...")
                time.sleep(RETRY_WAIT)
            else:
                print(f"     🛑 Rate limited {retries} times — giving up on this page")
                return None
        else:
            print(f"     ❌ Unexpected status {resp.status_code}")
            return None
    return None


def fetch_page(page):
    url = page_url(page)
    print(f"  🌐 {url}")
    resp = fetch_with_retry(url)
    if resp is None:
        return None

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL)
    if not match:
        print("     ❌ No __NEXT_DATA__ found")
        return []

    data = json.loads(match.group(1))
    ads = data["props"]["pageProps"]["initialStore"].get("ads", [])
    print(f"     📦 Raw ads in page: {len(ads)}")
    return parse_ads(ads)


def parse_ads(ads):
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for ad in ads:
        try:
            a = ad.get("attributes", {})

            # Phone — hidden listings show None
            phone_raw = a.get("phone")
            # Prefix with ' so Excel treats it as text and preserves leading zero
            phone = f"'{phone_raw}" if phone_raw and not a.get("phoneHidden") else "N/A"

            results.append({
                "listing_id":    str(ad.get("id") or a.get("listId", "N/A")),
                "title":         a.get("subject", "N/A"),
                "price":         a.get("priceLabel", str(a.get("price", "N/A"))),
                "location":      a.get("locationLabel") or a.get("subareaName", "N/A"),
                "state":         a.get("regionName", "Penang"),
                "beds":          str(a.get("roomsName", "N/A")),
                "baths":         str(a.get("bathroomName", "N/A")),
                "size_sqft":     str(a.get("size", "N/A")),
                "property_type": a.get("propertyTypeName", "N/A"),
                "title_type":    a.get("titleTypeName", "N/A"),
                "phone":         phone,
                "url":           a.get("adviewUrl", f"https://www.mudah.my/ad/{ad.get('id')}.htm"),
                "scraped_at":    now,
            })
        except Exception as e:
            print(f"     ⚠️  Skipped ad: {e}")

    return results


def load_existing_ids(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, newline="", encoding="utf-8") as f:
        return {row["listing_id"] for row in csv.DictReader(f) if row.get("listing_id")}


def save_csv(filepath, rows, mode="w"):
    write_header = mode == "w" or not os.path.exists(filepath)
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def main():
    print(f"\n🏠 Mudah Penang Property Scraper — {TODAY}")
    print("=" * 50)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    existing_ids = load_existing_ids(MASTER_FILE)
    print(f"📂 Known listings in master: {len(existing_ids)}\n")

    all_listings = []
    for page in range(1, MAX_PAGES + 1):
        print(f"\n  📄 Page {page}/{MAX_PAGES}")
        try:
            items = fetch_page(page)
            if items is None:
                print("     🛑 Stopping due to rate limit")
                break
            if not items:
                print(f"     ⚠️  No listings — stopping at page {page}")
                break
            all_listings.extend(items)
            if page == 1 and items:
                s = items[0]
                print(f"     📝 Sample: {s['title']} | {s['price']} | {s['beds']} bed | {s['size_sqft']} sqft | 📞 {s['phone']}")
            print(f"     ✅ Got {len(items)} | Total: {len(all_listings)}")
        except Exception as e:
            print(f"     ❌ Error: {e}")
            break
        time.sleep(SLEEP_BETWEEN)

    new = [l for l in all_listings if l["listing_id"] not in existing_ids and l["listing_id"] != "N/A"]
    print(f"\n📦 Scraped: {len(all_listings)} | New: {len(new)}")

    if new:
        save_csv(OUTPUT_FILE, new, mode="w")
        save_csv(MASTER_FILE, new, mode="a")
        print(f"💾 Daily  → {OUTPUT_FILE}  ({len(new)} rows)")
        print(f"💾 Master → {MASTER_FILE}")
    elif all_listings:
        print("ℹ️  All listings already in master — nothing new.")
        save_csv(OUTPUT_FILE, [], mode="w")
    else:
        save_csv(OUTPUT_FILE, [], mode="w")
        print("ℹ️  No listings scraped.")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
