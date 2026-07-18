"""
Scrape a single Mudah listing URL for testing/verification.

Usage:
    python scrape_single.py https://www.mudah.my/ara-green-115014914.htm
"""
import requests
import json
import re
import sys

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def find_ad_data(obj):
    if isinstance(obj, dict):
        if "subject" in obj and ("price" in obj or "priceLabel" in obj):
            return obj
        for v in obj.values():
            result = find_ad_data(v)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_ad_data(item)
            if result:
                return result
    return None


def scrape_single(url: str):
    print(f"🌐 Fetching: {url}\n")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    print(f"HTTP {resp.status_code} | {len(resp.text)} chars\n")

    if resp.status_code != 200:
        print("❌ Failed to fetch page")
        return

    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL)
    if not match:
        print("❌ No __NEXT_DATA__ found")
        return

    data = json.loads(match.group(1))
    page_props = data.get("props", {}).get("pageProps", {})
    print("📂 pageProps keys:", list(page_props.keys()))

    ad = None
    for key in ["ad", "adData", "listing", "adDetail", "initialStore"]:
        candidate = page_props.get(key)
        if isinstance(candidate, dict) and ("subject" in candidate or "attributes" in candidate):
            ad = candidate
            break

    if not ad:
        ad = find_ad_data(page_props)

    if not ad:
        print("❌ Could not locate ad data in JSON — dumping top-level structure:")
        for k, v in page_props.items():
            print(f"  {k}: {type(v).__name__}")
        return

    a = ad.get("attributes", ad)

    print("\n" + "=" * 50)
    print("📋 LISTING DETAILS")
    print("=" * 50)
    print(f"Title:         {a.get('subject', 'N/A')}")
    print(f"Price:         {a.get('priceLabel') or a.get('price', 'N/A')}")
    print(f"Location:      {a.get('locationLabel') or a.get('subareaName', 'N/A')}")
    print(f"State:         {a.get('regionName', 'N/A')}")
    print(f"Beds:          {a.get('roomsName', 'N/A')}")
    print(f"Baths:         {a.get('bathroomName', 'N/A')}")
    print(f"Size:          {a.get('size', 'N/A')} {a.get('sizeSuffix','')}")
    print(f"Property type: {a.get('propertyTypeName', 'N/A')}")
    print(f"Title type:    {a.get('titleTypeName', 'N/A')}")
    print(f"Seller name:   {a.get('nameLabel') or a.get('name', 'N/A')}")

    phone_raw = a.get("phone")
    phone_hidden = a.get("phoneHidden")
    print(f"Phone (raw):   {phone_raw}")
    print(f"Phone hidden:  {phone_hidden}")
    if phone_raw and not phone_hidden:
        print(f"Phone (final): {phone_raw}")
    elif phone_raw and phone_hidden:
        print(f"Phone (final): HIDDEN (needs login)")
    else:
        print(f"Phone (final): CHAT ONLY (seller provided no number)")

    print(f"URL:           {a.get('adviewUrl', url)}")
    print("=" * 50)

    print("\n📦 ALL RAW FIELDS:")
    for k, v in a.items():
        if isinstance(v, (dict, list)):
            continue
        print(f"  {k}: {v}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scrape_single.py <mudah_listing_url>")
        sys.exit(1)
    scrape_single(sys.argv[1])
