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
    print("❌ No __NEXT_DATA__ found")
    exit()

data = json.loads(match.group(1))

def print_tree(obj, prefix="", depth=0):
    if depth > 4:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                print(f"{prefix}{k}: [list of {len(v)}]")
                if len(v) > 0 and isinstance(v[0], dict):
                    print(f"{prefix}  [0] keys: {list(v[0].keys())[:8]}")
            elif isinstance(v, dict):
                print(f"{prefix}{k}:")
                print_tree(v, prefix + "  ", depth + 1)
            else:
                print(f"{prefix}{k}: {str(v)[:60]}")

print_tree(data)
