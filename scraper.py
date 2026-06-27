import requests
import csv
import time
import os
import re
import json
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL      = "https://www.mudah.my/penang/properties-for-sale"
ADSBY         = "false"
MAX_PAGES     = 50         # increase this for more pages
SLEEP_BETWEEN = 2

OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_penang_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_penang_all.csv")

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Build page URL ────────────────────────────────────────────────────────────
def page_url(page: int) -> str:
    if page == 1:
        return f"{BASE_URL}?adsby={ADSBY}"
    return f"{BASE_URL}?adsby={ADSBY}&o={page}"


# ── Extract JSON embedded in HTML ─────────────────────────────────────────────
def fetch_page(page: int) -> list[dict]:
    url = page_url(page)
    print(f"  🌐 Fetching: {url}")

    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text

    print(f"     HTTP {resp.status_code} | {len(html)} chars received")

    # ── Strategy 1: window.__INITIAL_STATE__ ─────────────────────────────────
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\s*</script>", html, re.DOTALL)
    if match:
        print("     ✅ Found __INITIAL_STATE__")
        try:
            state = json.loads(match.group(1))
            ads = (
                state.get("listings", {}).get("listingData", {}).get("ads", [])
                or state.get("adList", {}).get("ads", [])
                or state.get("listingData", {}).get("ads", [])
                or []
            )
            if ads:
                print(f"     ✅ Strategy 1 got {len(ads)} ads")
                return parse_ads(ads)
        except Exception as e:
            print(f"     ⚠️  Strategy 1 JSON parse failed: {e}")

    # ── Strategy 2: __NEXT_DATA__ (Next.js) ──────────────────────────────────
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
    if match:
        print("     ✅ Found __NEXT_DATA__")
        try:
            data = json.loads(match.group(1))
            # Navigate into Next.js page props
            props = data.get("props", {}).get("pageProps", {})
            ads = (
                props.get("listings", {}).get("ads", [])
                or props.get("ads", [])
                or props.get("data", {}).get("ads", [])
                or []
            )
            if ads:
                print(f"     ✅ Strategy 2 got {len(ads)} ads")
                return parse_ads(ads)
        except Exception as e:
            print(f"     ⚠️  Strategy 2 JSON parse failed: {e}")

    # ── Strategy 3: any JSON blob containing "list_id" ───────────────────────
    matches = re.findall(r'\{[^{}]*"list_id"[^{}]*\}', html)
    if matches:
        print(f"     ✅ Strategy 3: found {len(matches)} raw ad blobs")
        ads = []
        for m in matches:
            try:
                ads.append(json.loads(m))
            except Exception:
                pass
        if ads:
            return parse_ads(ads)

    print("     ❌ No listing data found on this page — might be JS-rendered")
    # Dump a snippet so we can debug
    print("     📋 HTML snippet (first 500 chars):")
    print("     " + html[:500].replace("\n", " "))
    return []


def parse_ads(ads: list) -> list[dict]:
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for ad in ads:
        try:
            attrs = ad.get("attributes", {})

            def attr(key):
                v = attrs.get(key, {})
                if isinstance(v, dict):
                    return str(v.get("value", "N/A"))
                return str(v) if v else "N/A"

            listing_id = str(ad.get("list_id") or ad.get("id", "N/A"))
            title      = ad.get("subject") or ad.get("title", "N/A")

            price_raw = ad.get("price", {})
            if isinstance(price_raw, dict):
                price = str(price_raw.get("value", "N/A"))
            else:
                price = str(price_raw) if price_raw else "N/A"

            location   = ad.get("region") or ad.get("location", "N/A")
            state      = ad.get("state_name") or ad.get("region_name", "Penang")
            beds       = attr("rooms") or attr("bedrooms")
            baths      = attr("bathrooms")
            size       = attr("size") or attr("floor_area")
            ptype      = attr("property_type") or attr("sub_catname")
            link       = ad.get("url") or f"https://www.mudah.my/ad/{listing_id}.htm"

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
            print(f"     ⚠️  Skipped one ad: {e}")

    return results


# ── Scrape all pages ──────────────────────────────────────────────────────────
def scrape_all() -> list[dict]:
    all_listings = []
    for page in range(1, MAX_PAGES + 1):
        print(f"\n  📄 Page {page}/{MAX_PAGES}")
        try:
            items = fetch_page(page)
            if not items:
                print(f"     ⚠️  Empty page — stopping early at page {page}")
                break
            all_listings.extend(items)
            print(f"     Running total: {len(all_listings)}")
        except Exception as e:
            print(f"     ❌ Error on page {page}: {e}")
            break
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
    print(f"\n🏠 Mudah Penang Property Scraper — {TODAY}")
    print("=" * 50)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    existing_ids = load_existing_ids(MASTER_FILE)
    print(f"\n📂 Known listings in master: {len(existing_ids)}")

    print(f"\n🌐 Scraping up to {MAX_PAGES} pages of Penang listings …")
    listings = scrape_all()
    print(f"\n📦 Total scraped: {len(listings)}")

    new_listings = [
        l for l in listings
        if l["listing_id"] not in existing_ids and l["listing_id"] != "N/A"
    ]
    print(f"✨ New listings: {len(new_listings)}")

    if new_listings:
        save_csv(OUTPUT_FILE, new_listings, mode="w")
        print(f"\n💾 Daily file  → {OUTPUT_FILE}")
        save_csv(MASTER_FILE, new_listings, mode="a")
        print(f"💾 Master file → {MASTER_FILE}")
    else:
        print("\nℹ️  No new listings today.")
        # Still write an empty daily file so the commit step has something
        save_csv(OUTPUT_FILE, [], mode="w")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
