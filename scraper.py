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
SLEEP_BETWEEN = 4

OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_penang_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_penang_all.csv")

CSV_FIELDS = [
    "listing_id", "title", "price", "location", "state",
    "beds", "baths", "size_sqft", "property_type", "title_type",
    "url", "scraped_at",
]


def page_url(page):
    if page == 1:
        return f"{BASE_URL}?adsby=false"
    return f"{BASE_URL}?adsby=false&o={page}"


def fetch_page(page):
    url = page_url(page)
    print(f"  🌐 {url}")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    print(f"     HTTP {resp.status_code} | {len(resp.text)} chars")

    if resp.status_code == 429:
        print("     ⏳ Rate limited — waiting 30s then retrying...")
        time.sleep(30)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        print(f"     Retry HTTP {resp.status_code}")
        if resp.status_code != 200:
            return None

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL)
    if not match:
        print("     ❌ No __NEXT_DATA__ found")
        return []

    data = json.loads(match.group(1))
    ads = data["props"]["pageProps"]["initialStore"].get("ads", [])
    return parse_ads(ads)


def parse_ads(ads):
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for ad in ads:
        try:
            a = ad.get("attributes", {})

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
                print("     🛑 Stopping — repeated rate limit")
                break
            if not items:
                print(f"     ⚠️  Empty — stopping at page {page}")
                break
            all_listings.extend(items)
            # Print sample row from first page
            if page == 1:
                s = items[0]
                print(f"     📝 Sample: {s['title']} | {s['price']} | {s['beds']} bed {s['baths']} bath | {s['size_sqft']} sqft | {s['location']}")
            print(f"     ✅ Got {len(items)} | Total: {len(all_listings)}")
        except Exception as e:
            print(f"     ❌ {e}")
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
