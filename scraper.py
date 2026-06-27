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
SLEEP_BETWEEN = 2

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


def find_ads_recursive(obj, path=""):
    """Walk every node in the JSON tree and return the first list that looks like ads."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            result = find_ads_recursive(v, f"{path}.{k}")
            if result:
                return result
    elif isinstance(obj, list) and len(obj) > 0:
        first = obj[0]
        if isinstance(first, dict) and ("list_id" in first or "subject" in first):
            print(f"     🎯 Found ads at: {path}  (count={len(obj)})")
            print(f"        First item keys: {list(first.keys())[:10]}")
            return obj
        for item in obj[:3]:
            result = find_ads_recursive(item, f"{path}[]")
            if result:
                return result
    return None


def fetch_page(page):
    url = page_url(page)
    print(f"  🌐 {url}")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    print(f"     HTTP {resp.status_code} | {len(resp.text)} chars")

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL)
    if not match:
        print("     ❌ No __NEXT_DATA__ found")
        return []

    try:
        data = json.loads(match.group(1))
    except Exception as e:
        print(f"     ❌ JSON parse error: {e}")
        return []

    # Print top 2 levels to understand structure
    print("     📂 JSON top-level keys:", list(data.keys()))
    props = data.get("props", {})
    print("     📂 props keys:", list(props.keys()))
    page_props = props.get("pageProps", {})
    print("     📂 pageProps keys:", list(page_props.keys()))
    for k, v in page_props.items():
        if isinstance(v, dict):
            print(f"        pageProps.{k} → dict keys: {list(v.keys())[:8]}")
        elif isinstance(v, list):
            print(f"        pageProps.{k} → list len={len(v)}", end="")
            if v and isinstance(v[0], dict):
                print(f", item[0] keys: {list(v[0].keys())[:6]}", end="")
            print()

    # Now hunt recursively
    ads = find_ads_recursive(data)
    if not ads:
        print("     ❌ Could not find ads anywhere in JSON tree")
        return []

    return parse_ads(ads)


def parse_ads(ads):
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for ad in ads:
        try:
            attrs = ad.get("attributes", {})
            def attr(key):
                v = attrs.get(key, {})
                return str(v.get("value", "N/A")) if isinstance(v, dict) else str(v or "N/A")

            price_raw = ad.get("price", {})
            price = str(price_raw.get("value", "N/A")) if isinstance(price_raw, dict) else str(price_raw or "N/A")

            results.append({
                "listing_id":    str(ad.get("list_id") or "N/A"),
                "title":         ad.get("subject", "N/A"),
                "price":         price,
                "location":      ad.get("region", "N/A"),
                "state":         ad.get("state_name", "Penang"),
                "beds":          attr("rooms") or attr("bedrooms"),
                "baths":         attr("bathrooms"),
                "size_sqft":     attr("size") or attr("floor_area"),
                "property_type": attr("property_type") or attr("sub_catname"),
                "url":           ad.get("url", f"https://www.mudah.my/ad/{ad.get('list_id','')}.htm"),
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
    print(f"\n📂 Known listings in master: {len(existing_ids)}")

    all_listings = []
    for page in range(1, MAX_PAGES + 1):
        print(f"\n  📄 Page {page}/{MAX_PAGES}")
        try:
            items = fetch_page(page)
            if not items:
                print(f"     ⚠️  Empty — stopping at page {page}")
                break
            all_listings.extend(items)
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
        print(f"💾 Saved → {OUTPUT_FILE}")
    else:
        save_csv(OUTPUT_FILE, [], mode="w")
        print("ℹ️  No new listings.")
    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
