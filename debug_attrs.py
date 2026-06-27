import requests
import json
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

url = "https://www.mudah.my/penang/properties-for-sale?adsby=false"
resp = requests.get(url, headers=HEADERS, timeout=20)
data = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', resp.text, re.DOTALL).group(1))
ads = data["props"]["pageProps"]["initialStore"]["ads"]

# Print FULL attributes of first 3 ads
for i, ad in enumerate(ads[:3]):
    print(f"\n{'='*60}")
    print(f"AD #{i+1} — id: {ad.get('id')}")
    print(f"TOP LEVEL KEYS: {list(ad.keys())}")
    attrs = ad.get("attributes", {})
    print(f"\nALL ATTRIBUTES:")
    for k, v in attrs.items():
        print(f"  {k}: {v}")
    links = ad.get("links", {})
    print(f"\nLINKS: {links}")
