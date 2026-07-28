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

OUTPUT_DIR     = "data"
TODAY          = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE    = os.path.join(OUTPUT_DIR, f"mudah_penang_{TODAY}.csv")
MASTER_FILE    = os.path.join(OUTPUT_DIR, "mudah_penang_all.csv")

# All fields — stored in master file (internal use)
CSV_FIELDS = [
    "listing_id", "title", "price", "price_numeric", "price_range", "location", "state",
    "beds", "baths", "size_sqft", "property_type", "title_type",
    "seller_name", "seller_type", "phone", "url", "scraped_at",
]

# Cleaned up — what appears in daily/price-range output files
OUTPUT_FIELDS = [
    "title", "price", "highest_mv", "location",
    "beds", "baths", "size_sqft", "property_type", "title_type",
    "seller_name", "seller_type", "phone", "url",
]

SQFT_TOLERANCE = 0.20   # ±20% size range counts as "comparable"


def page_url(page):
    if page == 1:
        return f"{BASE_URL}?adsby=false"
    return f"{BASE_URL}?adsby=false&o={page}"


def price_bucket(price_numeric):
    """Return a price range label like 'RM200k-300k' for a numeric price."""
    if price_numeric is None or price_numeric <= 0:
        return "Unknown"
    if price_numeric >= 1_000_000:
        # Group into RM1.0M-1.5M, RM1.5M-2.0M etc for high-end
        lower = (price_numeric // 500_000) * 500_000
        upper = lower + 500_000
        return f"RM{lower/1_000_000:.1f}M-{upper/1_000_000:.1f}M"
    else:
        lower = (price_numeric // 100_000) * 100_000
        upper = lower + 100_000
        return f"RM{int(lower/1000)}k-{int(upper/1000)}k"


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
                print(f"     🛑 Rate limited {retries} times — giving up")
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

            phone_raw = a.get("phone")
            if phone_raw and not a.get("phoneHidden"):
                phone = f"'{phone_raw}"
            elif phone_raw and a.get("phoneHidden"):
                phone = "HIDDEN"
            else:
                phone = "CHAT ONLY"

            price_numeric = a.get("price")
            try:
                price_numeric = int(price_numeric)
            except (TypeError, ValueError):
                price_numeric = None

            # Detect if listed by an Agent/Company vs Private individual seller
            seller_type = "Agent" if a.get("companyAd") else "Private"

            results.append({
                "listing_id":    str(ad.get("id") or a.get("listId", "N/A")),
                "title":         a.get("subject", "N/A"),
                "price":         a.get("priceLabel", str(a.get("price", "N/A"))),
                "price_numeric": price_numeric if price_numeric is not None else "",
                "price_range":   price_bucket(price_numeric),
                "location":      a.get("locationLabel") or a.get("subareaName", "N/A"),
                "state":         a.get("regionName", "Penang"),
                "beds":          str(a.get("roomsName", "N/A")),
                "baths":         str(a.get("bathroomName", "N/A")),
                "size_sqft":     str(a.get("size", "N/A")),
                "property_type": a.get("propertyTypeName", "N/A"),
                "title_type":    a.get("titleTypeName", "N/A"),
                "seller_name":   a.get("nameLabel") or a.get("name", "N/A"),
                "seller_type":   seller_type,
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


def load_all_rows(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_csv(filepath, rows, fields, mode="w"):
    write_header = mode == "w" or not os.path.exists(filepath)
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def _safe_float(v):
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def build_comparable_pool(all_rows):
    """Pre-parse location/sqft/price/seller_type once for fast comparison lookups."""
    pool = []
    for r in all_rows:
        sqft = _safe_float(r.get("size_sqft"))
        price = _safe_float(r.get("price_numeric"))
        loc = (r.get("location") or "").strip().lower()
        seller_type = r.get("seller_type", "Private")
        if sqft and price and loc:
            pool.append({"location": loc, "sqft": sqft, "price": price, "seller_type": seller_type})
    return pool


def compute_market_value(row, pool):
    """
    Market Value — lowest to highest price among comparable listings
    (same location, similar sqft), regardless of seller type.
    """
    sqft = _safe_float(row.get("size_sqft"))
    loc = (row.get("location") or "").strip().lower()
    if not sqft or not loc:
        return "N/A"

    low_bound = sqft * (1 - SQFT_TOLERANCE)
    high_bound = sqft * (1 + SQFT_TOLERANCE)

    comps = [
        p["price"] for p in pool
        if p["location"] == loc and low_bound <= p["sqft"] <= high_bound
    ]

    if len(comps) < MIN_COMPARABLES:
        return "Insufficient data"

    lowest = min(comps)
    highest = max(comps)
    return f"RM{int(lowest):,} - RM{int(highest):,}"


def sort_by_price(rows):
    """Sort listings by price ascending — RM100k first, RM1M+ last. Unknown prices go last."""
    def sort_key(row):
        p = row.get("price_numeric", "")
        try:
            return (0, int(p))
        except (ValueError, TypeError):
            return (1, 0)   # unknown/blank prices sorted to the end
    return sorted(rows, key=sort_key)


def sort_by_market_value(rows):
    """Sort listings by Market Value ascending (lowest RM first). Rows with
    'Insufficient data' or 'N/A' (no MV computed) are sorted to the end."""
    def sort_key(row):
        mv = row.get("highest_mv", "")
        match = re.match(r"RM([\d,]+)", mv)
        if match:
            return (0, int(match.group(1).replace(",", "")))
        return (1, 0)
    return sorted(rows, key=sort_key)


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
                print(f"     📝 Sample: {s['title']} | {s['price']} ({s['price_range']}) | {s['beds']} bed | 📞 {s['phone']}")
            print(f"     ✅ Got {len(items)} | Total: {len(all_listings)}")
        except Exception as e:
            print(f"     ❌ Error: {e}")
            break
        time.sleep(SLEEP_BETWEEN)

    new = [l for l in all_listings if l["listing_id"] not in existing_ids and l["listing_id"] != "N/A"]
    print(f"\n📦 Scraped: {len(all_listings)} | New: {len(new)}")

    if new:
        # Append to master FIRST so the comparable pool includes today's listings too
        save_csv(MASTER_FILE, new, fields=CSV_FIELDS, mode="a")
        print(f"💾 Master → {MASTER_FILE}")

        # Build comparable pool from the full master (all-time data)
        all_master_rows = load_all_rows(MASTER_FILE)
        pool = build_comparable_pool(all_master_rows)
        print(f"📊 Comparable pool size: {len(pool)} listings with valid price+sqft+location")

        for row in new:
            row["highest_mv"] = compute_market_value(row, pool)

        sorted_new = sort_by_market_value(new)
        save_csv(OUTPUT_FILE, sorted_new, fields=OUTPUT_FIELDS, mode="w")
        print(f"💾 Daily  → {OUTPUT_FILE}  ({len(new)} rows, sorted by Market Value: lowest → highest)")
    else:
        save_csv(OUTPUT_FILE, [], fields=OUTPUT_FIELDS, mode="w")
        print("ℹ️  No new listings today.")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
