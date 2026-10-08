import requests
import json
import re
import csv
import os
import sys
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

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL      = "https://www.mudah.my/penang/properties-for-sale"
MAX_PAGES     = 50     # stops automatically when a page comes back empty
SLEEP_BETWEEN = 5      # seconds between pages
RETRY_WAIT    = 60     # seconds to wait after a 429 (rate limit)

OUTPUT_DIR  = "data"
TODAY       = datetime.now().strftime("%Y-%m-%d")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"mudah_penang_{TODAY}.csv")
MASTER_FILE = os.path.join(OUTPUT_DIR, "mudah_penang_all.csv")

# Master file keeps everything (internal use)
CSV_FIELDS = [
    "listing_id", "title", "price", "price_numeric", "price_range",
    "location", "state", "beds", "baths", "size_sqft",
    "property_type", "title_type", "seller_name", "phone",
    "url", "scraped_at",
]

# Daily output file: clean columns only
OUTPUT_FIELDS = [
    "title", "price", "location",
    "beds", "baths", "size_sqft", "property_type", "title_type",
    "seller_name", "phone", "url",
]


# ── Helpers ──────────────────────────────────────────────────────────────────
def page_url(page):
    if page == 1:
        return f"{BASE_URL}?adsby=false"
    return f"{BASE_URL}?adsby=false&o={page}"


def price_bucket(price_numeric):
    """Label like 'RM300k-400k' (RM100k steps) or 'RM1.5M-2.0M' (RM500k steps above 1M)."""
    if price_numeric is None or price_numeric <= 0:
        return "Unknown"
    if price_numeric >= 1_000_000:
        lower = (price_numeric // 500_000) * 500_000
        upper = lower + 500_000
        return f"RM{lower / 1_000_000:.1f}M-{upper / 1_000_000:.1f}M"
    lower = (price_numeric // 100_000) * 100_000
    upper = lower + 100_000
    return f"RM{int(lower / 1000)}k-{int(upper / 1000)}k"


def sort_by_price(rows):
    """Cheapest first. Unknown prices go to the bottom."""
    def key(row):
        try:
            return (0, int(row.get("price_numeric", "")))
        except (ValueError, TypeError):
            return (1, 0)
    return sorted(rows, key=key)


# ── Fetching ─────────────────────────────────────────────────────────────────
def fetch_with_retry(url, retries=3):
    for attempt in range(1, retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        print(f"     HTTP {resp.status_code} | {len(resp.text)} chars")
        if resp.status_code == 200:
            return resp
        if resp.status_code == 429:
            if attempt < retries:
                print(f"     ⏳ Rate limited ({attempt}/{retries}) — waiting {RETRY_WAIT}s...")
                time.sleep(RETRY_WAIT)
            else:
                print(f"     🛑 Rate limited {retries} times — giving up")
                return None
        else:
            print(f"     ❌ Unexpected status {resp.status_code}")
            return None
    return None


def looks_like_ad(item):
    if not isinstance(item, dict):
        return False
    a = item.get("attributes") if isinstance(item.get("attributes"), dict) else item
    return "subject" in a and ("listId" in a or "adviewUrl" in a or "priceLabel" in a)


def find_ads(obj):
    """Search a JSON tree for the list of ads, wherever it is."""
    if isinstance(obj, list):
        if obj and looks_like_ad(obj[0]):
            return obj
        for item in obj:
            found = find_ads(item)
            if found:
                return found
    elif isinstance(obj, dict):
        for v in obj.values():
            found = find_ads(v)
            if found:
                return found
    return None


DECODER = json.JSONDecoder()
SCRIPT_RE = re.compile(r"<script([^>]*)>(.*?)</script>", re.DOTALL)


def ads_from_json_scripts(html):
    """Method 1: <script> tags holding JSON (__NEXT_DATA__ in any attribute order, or type=application/json)."""
    for m in SCRIPT_RE.finditer(html):
        attrs, body = m.group(1), m.group(2).strip()
        if not body.startswith(("{", "[")):
            continue
        if "__NEXT_DATA__" in attrs or "application/json" in attrs:
            try:
                ads = find_ads(json.loads(body))
            except ValueError:
                continue
            if ads:
                return ads
    return None


def ads_from_window_state(html):
    """Method 2: window.__SOMETHING__ = {...};"""
    for m in re.finditer(r"window\.__[A-Za-z_]+__\s*=\s*", html):
        try:
            obj, _ = DECODER.raw_decode(html, m.end())
        except ValueError:
            continue
        ads = find_ads(obj)
        if ads:
            return ads
    return None


def ads_from_stream_chunks(html):
    """Method 3: Next.js streaming payload: self.__next_f.push([1,"...json..."])."""
    chunks = []
    for m in re.finditer(r"self\.__next_f\.push\(\[\d+,", html):
        try:
            obj, _ = DECODER.raw_decode(html, m.end())
        except ValueError:
            continue
        if isinstance(obj, str):
            chunks.append(obj)
    return ads_from_text(" ".join(chunks)) if chunks else None


def ads_from_text(text):
    """Method 4: find any  "ads":[ ... ]  list inside raw text."""
    for m in re.finditer(r'"ads"\s*:\s*\[', text):
        try:
            obj, _ = DECODER.raw_decode(text, m.end() - 1)
        except ValueError:
            continue
        if isinstance(obj, list) and obj and looks_like_ad(obj[0]):
            return obj
    return None


def extract_ads(html):
    for name, fn in [
        ("json <script> tag", ads_from_json_scripts),
        ("window state", ads_from_window_state),
        ("stream chunks", ads_from_stream_chunks),
        ("raw text search", ads_from_text),
    ]:
        ads = fn(html)
        if ads:
            return ads, name
    return None, None


def print_diagnostics(html):
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    print(f"     🔎 Page title: {title.group(1).strip()[:100] if title else 'none'}")
    print(f"     🔎 HTML size: {len(html)} chars")
    tokens = ["__NEXT_DATA__", "initialStore", "__next_f", "listId", "adviewUrl",
              "priceLabel", "application/ld+json", "__INITIAL_STATE__", "window.__"]
    print("     🔎 Token counts: " + ", ".join(f"{t}={html.count(t)}" for t in tokens))
    shown = 0
    for m in SCRIPT_RE.finditer(html):
        attrs, body = m.group(1).strip(), m.group(2)
        if ("id=" in attrs or "type=" in attrs) and shown < 12:
            print(f"     🔎 script [{attrs[:80]}] size={len(body)}")
            shown += 1


def fetch_page(page):
    url = page_url(page)
    print(f"  🌐 {url}")
    resp = fetch_with_retry(url)
    if resp is None:
        return None   # None = stop scraping

    ads, method = extract_ads(resp.text)
    if not ads:
        print("     ❌ Could not find ads in the page. Diagnostics:")
        print_diagnostics(resp.text)
        return []

    print(f"     ✅ Found {len(ads)} ads via: {method}")
    return parse_ads(ads)


def parse_ads(ads):
    results = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for ad in ads:
        try:
            a = ad.get("attributes") if isinstance(ad.get("attributes"), dict) else ad

            # Phone: 3 cases
            phone_raw = a.get("phone")
            if phone_raw and not a.get("phoneHidden"):
                phone = f"'{phone_raw}"      # ' keeps the leading 0 in Excel
            elif phone_raw and a.get("phoneHidden"):
                phone = "HIDDEN"
            else:
                phone = "CHAT ONLY"

            try:
                price_numeric = int(a.get("price"))
            except (TypeError, ValueError):
                price_numeric = None

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
                "phone":         phone,
                "url":           a.get("adviewUrl", f"https://www.mudah.my/ad/{ad.get('id')}.htm"),
                "scraped_at":    now,
            })
        except Exception as e:
            print(f"     ⚠️  Skipped ad: {e}")

    return results


# ── CSV ──────────────────────────────────────────────────────────────────────
def load_existing_ids(filepath):
    if not os.path.exists(filepath):
        return set()
    with open(filepath, newline="", encoding="utf-8") as f:
        return {row["listing_id"] for row in csv.DictReader(f) if row.get("listing_id")}


def save_csv(filepath, rows, fields, mode="w"):
    write_header = mode == "w" or not os.path.exists(filepath)
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


# ── Main ─────────────────────────────────────────────────────────────────────
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
            if page == 1:
                s = items[0]
                print(f"     📝 Sample: {s['title']} | {s['price']} ({s['price_range']}) | {s['beds']} bed | {s['seller_name']} | {s['phone']}")
            print(f"     ✅ Got {len(items)} | Total: {len(all_listings)}")
        except Exception as e:
            print(f"     ❌ Error: {e}")
            break
        time.sleep(SLEEP_BETWEEN)

    if not all_listings:
        print("\n🛑 ZERO listings scraped. See the diagnostic lines above (HTTP status / page title / JSON keys).")
        sys.exit(1)

    new = [l for l in all_listings if l["listing_id"] not in existing_ids and l["listing_id"] != "N/A"]
    print(f"\n📦 Scraped: {len(all_listings)} | New: {len(new)}")

    if new:
        save_csv(OUTPUT_FILE, sort_by_price(new), fields=OUTPUT_FIELDS, mode="w")
        save_csv(MASTER_FILE, new, fields=CSV_FIELDS, mode="a")
        print(f"💾 Daily  → {OUTPUT_FILE}  ({len(new)} rows, sorted cheapest → highest)")
        print(f"💾 Master → {MASTER_FILE}")
    else:
        save_csv(OUTPUT_FILE, [], fields=OUTPUT_FIELDS, mode="w")
        print("ℹ️  No new listings.")

    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()
