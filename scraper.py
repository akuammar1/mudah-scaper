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
SLEEP_BETWEEN = 4   # increased to avoid 429

OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_penang_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_penang_all.csv")

CSV_FIELDS = [
    "listing_id", "title", "price", "location", "state",
    "beds", "baths", "size_sqft", "property_type", "url", "scraped_at",
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
        print("     ⏳ Rate limited — waiting 30s then retrying once...")
        time.sleep(30)
        resp = requests.get(url, headers=HEADERS, timeout=20)
        print(f"     Retry HTTP {resp.status_code}")
        if resp.status_code != 200:
            return None  # None = stop scraping

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL)
    if not match:
        print("     ❌ No __NEXT_DATA__ found")
        return []

    data = json.loads(match.group(1))
    ads = data["props"]["pageProps"]["initialStore"].get("ads", [])

    if not ads:
        return []

    # Debug first ad structure once
    if page == 1:
        first = ads[0]
        print(f"     📋 First ad keys: {list(first.keys())}")
        attrs = first.get("attributes", {})
        print(f"     📋 attributes keys: {list(attrs.keys())[:15]}")
        links = first.get("links", {})
        print(f"     📋 links keys: {list(links.keys())}")

    return parse_ads(ads)


def parse_ads(ads):
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for ad in ads:
        try:
            # Mudah uses JSON:API format — id is top level, data is in attributes
            attrs = ad.get("attributes", {})
            links = ad.get("links", {})

            def attr(key):
                v = attrs.get(key)
                if v is None:
                    return "N/A"
                if isinstance(v, dict):
                    return str(v.get("value") or v.get("label") or "N/A")
                return str(v)

            listing_id = str(ad.get("id") or ad.get("list_id") or "N/A")
            title      = attr("subject") or attr("title") or attr("name")
            price      = attr("price") or attr("asking_price")
            location   = attr("region") or attr("area") or attr("location")
            state      = attr("state_name") or attr("state") or "Penang"
            beds       = attr("rooms") or attr("bedrooms") or attr("bedroom")
            baths      = attr("bathrooms") or attr("bathroom")
            size       = attr("size") or attr("floor_size") or attr("built_up")
            ptype      = attr("property_type") or attr("sub_catname") or attr("category")

            # URL from links object
            link = (
                links.get("self")
                or links.get("html")
                or links.get("url")
                or attrs.get("url")
                or f"https://www.mudah.my/ad/{listing_id}.htm"
            )
            if isinstance(link, dict):
                link = link.get("href", f"https://www.mudah.my/ad/{listing_id}.htm")

            results.append({
                "listing_id":    listing_id,
                "title":         title,
                "price":         price,
                "location":      location,
                "state":         state,
                "beds":          beds,
                "baths":         baths,
                "size_sqft":     size,
                "property_type": ptype,
                "url":           link,
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
                print("     🛑 Stopping due to repeated rate limit")
                break
            if not items:
                print(f"     ⚠️  Empty — stopping at page {page}")
                break
            all_listings.extend(items)
            print(f"     ✅ Got {len(items)} | Total: {len(all_listings)}")
            # Print sample row from first page
            if page == 1 and items:
                s = items[0]
                print(f"     📝 Sample: [{s['listing_id']}] {s['title'][:40]} | {s['price']} | {s['location']}")
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
        print("ℹ️  All listings already in master — nothing new to save.")
        save_csv(OUTPUT_FILE, [], mode="w")
    else:
        save_csv(OUTPUT_FILE, [], mode="w")
        print("ℹ️  No listings scraped.")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
