import requests
import json
import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

url = "https://www.mudah.my/penang/properties-for-sale?adsby=false"
resp = requests.get(url, headers=HEADERS, timeout=20)
html = resp.text

match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
if not match:
    print("❌ No __NEXT_DATA__ found at all")
else:
    print("✅ __NEXT_DATA__ found, size:", len(match.group(1)), "chars")
    data = json.loads(match.group(1))

    # Recursively search for any key that has a list with 'list_id' inside
    def find_ads(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                find_ads(v, f"{path}.{k}")
        elif isinstance(obj, list) and len(obj) > 0:
            first = obj[0]
            if isinstance(first, dict) and ("list_id" in first or "subject" in first or "price" in first):
                print(f"\n🎯 FOUND ADS at path: {path}")
                print(f"   Count: {len(obj)}")
                print(f"   First item keys: {list(first.keys())}")
                print(f"   Sample - list_id: {first.get('list_id','?')}, subject: {str(first.get('subject','?'))[:50]}, price: {first.get('price','?')}")
            else:
                for item in obj[:2]:
                    find_ads(item, f"{path}[]")

    find_ads(data)

    # Also print top 3 levels regardless
    print("\n\n--- TOP LEVEL STRUCTURE ---")
    def print_tree(obj, prefix="", depth=0):
        if depth > 3:
            return
        if isinstance(obj, dict):
            for k, v in list(obj.items())[:20]:
                if isinstance(v, list):
                    print(f"{prefix}{k}: [list len={len(v)}]")
                    if v and isinstance(v[0], dict):
                        print(f"{prefix}  item[0] keys: {list(v[0].keys())[:10]}")
                elif isinstance(v, dict):
                    print(f"{prefix}{k}: {{dict}}")
                    print_tree(v, prefix + "  ", depth + 1)
                else:
                    print(f"{prefix}{k}: {str(v)[:80]}")
    print_tree(data)
