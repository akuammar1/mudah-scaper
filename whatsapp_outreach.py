#!/usr/bin/env python3
"""
Semi-automated WhatsApp outreach for the Mudah lead pipeline.

What it does (no auto-sending, you tap send yourself):
  1. Reads the newest dated daily CSV(s) from the scraper (sale and/or rent).
  2. Skips anyone already in contacted.csv (by listing_id or phone).
  3. Picks up to DAILY_CAP new leads (cap counts what was already picked today).
  4. Builds a wa.me link per lead with the right message (sale or rent) pre-filled.
  5. Writes outreach/index.html and sends the links to Telegram (if configured).

Usage:
  python whatsapp_outreach.py                      # auto-find dated CSVs, sale + rent
  python whatsapp_outreach.py --type rent          # rent leads only
  python whatsapp_outreach.py --type sale          # sale leads only
  python whatsapp_outreach.py data/mudah_penang_rent_2026-11-20.csv
  python whatsapp_outreach.py --dry-run            # don't write the contacted log
"""
import argparse
import csv
import glob
import html
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

DAILY_CAP = None  # None = no limit; set a number (e.g. 9) to cap per day
LOG_FILE = "contacted.csv"
OUT_DIR = "outreach"
AGENT = "My name is Ammar Mirza Muazzam, a senior real estate agent from CCI Property, REN54406, under Muazzam Ali."
MIN_PRICE = 50000      # SALE: skip listings priced below this (rentals, per-sqft, junk)
MIN_RENT_PRICE = 500   # RENT: skip monthly rents below this (rooms, junk). Lower it to include rooms.
SALUTATION = "Mr"  # set to "" to greet with the plain name instead

# Possible column names in your CSV (first match wins). Edit if yours differ.
COLS = {
    "id": ["listing_id", "id", "ad_id"],
    "name": ["seller_name", "seller", "name", "advertiser", "contact_name"],
    "phone": ["phone", "phone_number", "seller_phone", "contact", "mobile", "tel"],
    "title": ["title", "subject", "listing_title", "property_name"],
    "area": ["location", "area", "region", "subarea", "address"],
    "price": ["price", "asking_price", "price_rm"],
    "url": ["url", "link", "listing_url"],
    "type": ["listing_type"],
}

# Names that are clearly not a person -> use a plain "Hi" instead.
NOT_A_NAME = {
    "owner", "agent", "admin", "seller", "sdn", "bhd", "realty", "property",
    "properties", "hartanah", "team", "sales", "enquiry", "private", "user",
}

SALE_TEMPLATES = [
    "{greet} I saw your ads on Mudah, {place}.{price_part} {agent} "
    "I have several buyers looking in this area right now and your "
    "property caught their eye. Is it still available? Are you interested?",

    "{greet} I saw your ads on Mudah, {place}.{price_part} {agent} "
    "I currently have a few interested buyers for this kind of property. "
    "Is it still available? Are you interested?",

    "{greet} I saw your ads on Mudah, {place}.{price_part} {agent} "
    "I've got buyers asking about properties in this area and yours looks "
    "like a good match. Is it still available? Are you interested?",
]

RENT_TEMPLATES = [
    "{greet} I saw your rental ad on Mudah, {place}.{price_part} {agent} "
    "I have a few tenants looking for a property in this area right now. "
    "Is it still available for rent? Are you interested?",

    "{greet} I saw your rental ad on Mudah, {place}.{price_part} {agent} "
    "I currently have some interested tenants for this kind of property. "
    "Is it still available for rent? Are you interested?",

    "{greet} I saw your rental ad on Mudah, {place}.{price_part} {agent} "
    "I've got tenants asking about properties in this area and yours looks "
    "like a good match. Is it still available for rent? Are you interested?",
]

TEMPLATES = {"sale": SALE_TEMPLATES, "rent": RENT_TEMPLATES}


def pick(row, key):
    for col in COLS[key]:
        for k in row:
            if k and k.strip().lower() == col:
                return (row[k] or "").strip()
    return ""


def norm_phone(raw):
    d = re.sub(r"\D", "", (raw or "").lstrip("'"))
    if d.startswith("0"):
        d = "6" + d
    elif d.startswith("1"):
        d = "60" + d
    if not d.startswith("60") or not (10 <= len(d) <= 12):
        return None
    return d


def clean_name(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    words = raw.split()
    if any(ch.isdigit() for ch in raw):
        return ""
    if any(w.lower().strip(".,") in NOT_A_NAME for w in words):
        return ""
    return words[0].title()


def price_value(raw):
    digits = re.sub(r"[^\d.]", "", (raw or "").replace(",", ""))
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def fmt_price(raw, ltype="sale"):
    raw = (raw or "").strip()
    if not raw:
        return ""
    out = raw
    digits = re.sub(r"[^\d.]", "", raw)
    if digits and digits.replace(".", "", 1).isdigit() and "rm" not in raw.lower():
        try:
            out = f"RM{int(float(digits)):,}"
        except ValueError:
            pass
    else:
        out = raw if raw.lower().startswith("rm") else f"RM{raw}"
    if ltype == "rent" and not re.search(r"month|/\s*mo|mth", out, re.I):
        out += "/month"
    return out


def file_type(path, row):
    """sale or rent: from the listing_type column, else from the file name."""
    t = pick(row, "type").lower()
    if t in ("sale", "rent"):
        return t
    return "rent" if "rent" in os.path.basename(path).lower() else "sale"


def build_message(lead):
    ltype = lead["type"]
    name = clean_name(lead["name"])
    if name:
        greet = f"Hi {SALUTATION} {name}.".replace("  ", " ")
    else:
        greet = "Hi,"
    place = lead["area"] or lead["title"] or "your property"
    price = fmt_price(lead["price"], ltype)
    if price:
        price_part = f" Rental at {price}." if ltype == "rent" else f" Pricing at {price}."
    else:
        price_part = ""
    return random.choice(TEMPLATES[ltype]).format(
        greet=greet, place=place, price_part=price_part, agent=AGENT
    )


def load_log():
    ids, phones, today_count = set(), set(), 0
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("listing_id"):
                    ids.add(r["listing_id"])
                if r.get("phone"):
                    phones.add(r["phone"])
                if r.get("date") == date.today().isoformat():
                    today_count += 1
    return ids, phones, today_count


def append_log(leads):
    new_file = not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "listing_id", "phone", "name"])
        for l in leads:
            w.writerow([date.today().isoformat(), l["id"], l["phone"], l["name"]])


def find_csvs():
    files = [
        p for p in glob.glob("**/*.csv", recursive=True)
        if re.search(r"\d{4}-\d{2}-\d{2}", os.path.basename(p))
        and not any(x in p.lower() for x in ("master", "draft", "contacted"))
    ]
    return sorted(files, key=lambda p: re.search(r"\d{4}-\d{2}-\d{2}", p).group(), reverse=True)


def collect(files, ids, phones, need, want="both"):
    leads, seen = [], set()
    for path in files:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ltype = file_type(path, row)
                if want != "both" and ltype != want:
                    continue
                phone = norm_phone(pick(row, "phone"))
                lid = pick(row, "id") or (phone or "")
                pv = price_value(pick(row, "price"))
                floor = MIN_RENT_PRICE if ltype == "rent" else MIN_PRICE
                if pv is not None and pv < floor:
                    continue
                if not phone or lid in ids or phone in phones or phone in seen:
                    continue
                seen.add(phone)
                leads.append({
                    "id": lid, "phone": phone, "name": pick(row, "name"),
                    "title": pick(row, "title"), "area": pick(row, "area"),
                    "price": pick(row, "price"), "url": pick(row, "url"),
                    "type": ltype,
                })
                if len(leads) >= need:
                    return leads
    return leads


def wa_link(phone, message):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(message)}"


def tag(l):
    return "RENT" if l["type"] == "rent" else "SALE"


def write_html(leads):
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for i, l in enumerate(leads, 1):
        label = html.escape(clean_name(l["name"]) or "Seller")
        sub = html.escape(" | ".join(
            x for x in (l["area"] or l["title"], fmt_price(l["price"], l["type"])) if x))
        rows.append(
            f'<a class="card" href="{html.escape(l["link"])}">'
            f'<b>{i}. [{tag(l)}] {label}</b><span>{sub}</span><em>Open in WhatsApp</em></a>'
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Outreach {date.today()}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#f4f4f4}}
h1{{font-size:18px}}
.card{{display:block;background:#fff;border-radius:12px;padding:14px;margin:10px 0;
text-decoration:none;color:#111;box-shadow:0 1px 3px #0002}}
.card span{{display:block;color:#555;font-size:14px;margin:4px 0}}
.card em{{color:#128c7e;font-style:normal;font-weight:600}}
</style></head><body>
<h1>{len(leads)} leads for {date.today()}</h1>{''.join(rows)}</body></html>"""
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


def tg_post(token, payload):
    """Send one Telegram message. Returns (ok, response_text)."""
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, str(r.status)
    except urllib.error.HTTPError as e:
        return False, e.read().decode("utf-8", "replace")
    except Exception as e:  # network hiccup etc.
        return False, str(e)


def send_telegram(leads):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram not configured, skipping.")
        return

    def esc(x):
        return html.escape(x, quote=False)

    def item(i, l):
        label = esc(clean_name(l["name"]) or "Seller")
        sub = esc(" | ".join(
            x for x in (l["area"] or l["title"], fmt_price(l["price"], l["type"])) if x))
        href = l["link"].replace("&", "&amp;").replace('"', "&quot;")
        return f'{i}. [{tag(l)}] <a href="{href}">{label}</a> - {sub}'

    n_rent = sum(1 for l in leads if l["type"] == "rent")
    n_sale = len(leads) - n_rent
    items = [item(i, l) for i, l in enumerate(leads, 1)]
    # Telegram caps messages at 4096 chars, so send in chunks of 20
    for start in range(0, len(items), 20):
        head = (f"<b>{len(leads)} WhatsApp leads for {date.today()}</b> "
                f"({n_sale} sale, {n_rent} rent) (part {start // 20 + 1})\n\n")
        ok, resp = tg_post(token, {
            "chat_id": chat, "text": head + "\n".join(items[start:start + 20]),
            "parse_mode": "HTML", "disable_web_page_preview": True,
        })
        if ok:
            print("Telegram: ok")
            continue
        print("Telegram rejected a batch, sending one by one. Reason:", resp)
        for j in range(start, min(start + 20, len(items))):
            ok, resp = tg_post(token, {
                "chat_id": chat, "text": items[j],
                "parse_mode": "HTML", "disable_web_page_preview": True,
            })
            if not ok:
                # last resort: plain text with the raw link
                l = leads[j]
                ok, resp = tg_post(token, {
                    "chat_id": chat, "disable_web_page_preview": True,
                    "text": f'{j + 1}. [{tag(l)}] {clean_name(l["name"]) or "Seller"}: {l["link"]}',
                })
            if not ok:
                print(f"Could not send lead {j + 1} to Telegram:", resp)


def main():
    ap = argparse.ArgumentParser(description="WhatsApp outreach for Mudah leads")
    ap.add_argument("files", nargs="*", help="CSV file(s); default: auto-find dated CSVs")
    ap.add_argument("--type", choices=["sale", "rent", "both"], default="both",
                    help="which listing type to pick leads from (default: both)")
    ap.add_argument("--dry-run", action="store_true", help="don't write the contacted log")
    args = ap.parse_args()

    files = args.files or find_csvs()
    if not files:
        sys.exit("No dated CSV files found. Pass a path: python whatsapp_outreach.py data/mudah_penang_2026-11-08.csv")

    ids, phones, today_count = load_log()
    need = (DAILY_CAP - today_count) if DAILY_CAP else 10**9
    if need <= 0:
        sys.exit(f"Daily cap of {DAILY_CAP} already reached today.")

    leads = collect(files, ids, phones, need, args.type)
    if not leads:
        sys.exit("No new leads left (everyone is already in contacted.csv).")

    for l in leads:
        l["link"] = wa_link(l["phone"], build_message(l))

    write_html(leads)
    send_telegram(leads)
    if not args.dry_run:
        append_log(leads)
    print(f"Prepared {len(leads)} leads ({today_count} already done today, cap {DAILY_CAP or 'none'}).")


if __name__ == "__main__":
    main()
