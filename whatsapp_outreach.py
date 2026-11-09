#!/usr/bin/env python3
"""
Semi-automated WhatsApp outreach for the Mudah lead pipeline.

What it does (no auto-sending, you tap send yourself):
  1. Reads the newest dated daily CSV(s) from the scraper.
  2. Skips anyone already in contacted.csv (by listing_id or phone).
  3. Picks up to DAILY_CAP new leads (cap counts what was already picked today).
  4. Builds a wa.me link per lead with the message pre-filled.
  5. Writes outreach/index.html and sends the links to Telegram (if configured).

Usage:
  python whatsapp_outreach.py                 # auto-find dated CSVs
  python whatsapp_outreach.py data/2026-11-08.csv
  python whatsapp_outreach.py --dry-run       # don't write the contacted log
"""
import csv
import glob
import html
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request
from datetime import date

DAILY_CAP = 9
LOG_FILE = "contacted.csv"
OUT_DIR = "outreach"
AGENT = "Ammar from CCI Property (REN54406)"
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
}

# Names that are clearly not a person -> use a plain "Hi" instead.
NOT_A_NAME = {
    "owner", "agent", "admin", "seller", "sdn", "bhd", "realty", "property",
    "properties", "hartanah", "team", "sales", "enquiry", "private", "user",
}

TEMPLATES = [
    "{greet} I saw your ad on Mudah for {place}{price_part}. "
    "{agent}. I have several buyers looking in this area right now and "
    "your property caught their eye. Is it still available? "
    "(Reply STOP and I won't message again.)",

    "{greet} I came across your listing on Mudah, {place}{price_part}. "
    "I'm {agent} and I currently have a few interested buyers for this kind "
    "of property. Would you be open to a quick chat? "
    "(Reply STOP and I won't message again.)",

    "{greet} I noticed your Mudah ad for {place}{price_part}. "
    "{agent} here. I've got buyers asking about properties in this area and "
    "yours looks like a good match. Can I share how I can help? "
    "(Reply STOP and I won't message again.)",
]


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


def fmt_price(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"[^\d.]", "", raw)
    if digits and digits.replace(".", "", 1).isdigit() and "rm" not in raw.lower():
        try:
            return f"RM{int(float(digits)):,}"
        except ValueError:
            pass
    return raw if raw.lower().startswith("rm") else f"RM{raw}"


def build_message(lead):
    name = clean_name(lead["name"])
    if name:
        greet = f"Hi {SALUTATION} {name}.".replace("  ", " ")
    else:
        greet = "Hi,"
    place = lead["area"] or lead["title"] or "your property"
    price = fmt_price(lead["price"])
    price_part = f" at {price}" if price else ""
    return random.choice(TEMPLATES).format(
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
    new_file = not os.path.exists(LOG_FILE)
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


def collect(files, ids, phones, need):
    leads, seen = [], set()
    for path in files:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                phone = norm_phone(pick(row, "phone"))
                lid = pick(row, "id") or (phone or "")
                if not phone or lid in ids or phone in phones or phone in seen:
                    continue
                seen.add(phone)
                leads.append({
                    "id": lid, "phone": phone, "name": pick(row, "name"),
                    "title": pick(row, "title"), "area": pick(row, "area"),
                    "price": pick(row, "price"), "url": pick(row, "url"),
                })
                if len(leads) >= need:
                    return leads
    return leads


def wa_link(phone, message):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(message)}"


def write_html(leads):
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for i, l in enumerate(leads, 1):
        label = html.escape(clean_name(l["name"]) or "Seller")
        sub = html.escape(" | ".join(x for x in (l["area"] or l["title"], fmt_price(l["price"])) if x))
        rows.append(
            f'<a class="card" href="{html.escape(l["link"])}">'
            f'<b>{i}. {label}</b><span>{sub}</span><em>Open in WhatsApp</em></a>'
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


def send_telegram(leads):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram not configured, skipping.")
        return
    lines = [f"<b>{len(leads)} WhatsApp leads for {date.today()}</b>", ""]
    for i, l in enumerate(leads, 1):
        label = html.escape(clean_name(l["name"]) or "Seller")
        sub = html.escape(" | ".join(x for x in (l["area"] or l["title"], fmt_price(l["price"])) if x))
        lines.append(f'{i}. <a href="{html.escape(l["link"])}">{label}</a> - {sub}')
    data = json.dumps({
        "chat_id": chat, "text": "\n".join(lines),
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("Telegram:", r.status)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    files = args or find_csvs()
    if not files:
        sys.exit("No dated CSV files found. Pass a path: python whatsapp_outreach.py data/2026-11-08.csv")

    ids, phones, today_count = load_log()
    need = DAILY_CAP - today_count
    if need <= 0:
        sys.exit(f"Daily cap of {DAILY_CAP} already reached today.")

    leads = collect(files, ids, phones, need)
    if not leads:
        sys.exit("No new leads left (everyone is already in contacted.csv).")

    for l in leads:
        l["link"] = wa_link(l["phone"], build_message(l))

    write_html(leads)
    send_telegram(leads)
    if not dry:
        append_log(leads)
    print(f"Prepared {len(leads)} leads ({today_count} already done today, cap {DAILY_CAP}).")


if __name__ == "__main__":
    main()
