#!/usr/bin/env python3
"""
generate_drafts.py

Scans Mudah.my property listing exports (PDF or CSV) and generates a
personalized outreach draft for each listing, based on `seller_name`,
`title`, `price` and `listing_type` (sale or rent).

USAGE
-----
From your scraper's CSV (recommended):
    python3 generate_drafts.py --csv data/2026-11-20.csv --out drafts.csv
    python3 generate_drafts.py --csv data/rent_2026-11-20.csv --out drafts_rent.csv

Only one type from a mixed CSV:
    python3 generate_drafts.py --csv master.csv --type rent --out drafts_rent.csv

From PDFs (assumed "sale" unless you pass --type rent):
    python3 generate_drafts.py --pdf-dir /path/to/pdfs --type rent --out drafts.csv

LISTING TYPE
------------
- If the CSV has a `listing_type` column ("sale" / "rent"), it is used per row.
- If the column is missing (older sale-only CSVs), rows default to "sale".
- `--type sale|rent` filters to that type; for PDFs it sets the type.

OUTPUT
------
CSV (`--out`) columns:
    listing_id, listing_type, seller_name, title, price, phone, url, draft_message
plus a human-readable .txt with the same basename.
"""

import argparse
import csv
import os
import re
from pathlib import Path

AGENT_NAME = "Ammar Mirza"
AGENT_TITLE = "Realty Agent"
AGENT_FIRM = "CCI Property REN54406"
AGENT_SUPERVISOR = "Muazzam Ali"

SALE_TEMPLATE = """Hi {seller_name}, My name is {agent_name}, I am a {agent_title}. I'm from {agent_firm} supervised by {agent_supervisor}.

I got some interested (filtered loan checked) buyers looking around for your type of property.

saw your ads in Mudah titled '{title}' selling for {price}.

Let me know if you're interested and we can talk commissions and details. Any questions is open

Thank you for your time :)"""

RENT_TEMPLATE = """Hi {seller_name}, My name is {agent_name}, I am a {agent_title}. I'm from {agent_firm} supervised by {agent_supervisor}.

I got some interested (screened) tenants looking around for your type of property.

saw your ads in Mudah titled '{title}' for rent at {price}.

Let me know if you're interested and we can talk details and arrangements. Any questions is open

Thank you for your time :)"""

TEMPLATES = {"sale": SALE_TEMPLATE, "rent": RENT_TEMPLATE}


def normalize_type(value: str) -> str:
    v = (value or "").strip().lower()
    return "rent" if v in ("rent", "rental", "for rent", "sewa") else "sale"


def format_price(price: str, listing_type: str) -> str:
    price = price.strip()
    if listing_type == "rent" and price and not re.search(r"(per|/)\s*(month|mth|mo)", price, re.I):
        return f"{price}/month"
    return price


def make_draft(seller_name: str, title: str, price: str, listing_type: str = "sale") -> str:
    listing_type = normalize_type(listing_type)
    return TEMPLATES[listing_type].format(
        seller_name=seller_name.strip(),
        title=title.strip(),
        price=format_price(price, listing_type),
        agent_name=AGENT_NAME,
        agent_title=AGENT_TITLE,
        agent_firm=AGENT_FIRM,
        agent_supervisor=AGENT_SUPERVISOR,
    )


# ---------------------------------------------------------------------------
# CSV input (preferred / robust path)
# ---------------------------------------------------------------------------

def rows_from_csv(csv_path: str):
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("title") or "").strip()
            price = (row.get("price") or "").strip()
            seller_name = (row.get("seller_name") or "").strip()
            if not title or not seller_name:
                continue
            yield {
                "listing_id": (row.get("listing_id") or "").strip(),
                "listing_type": normalize_type(row.get("listing_type")),
                "seller_name": seller_name,
                "title": title,
                "price": price,
                "phone": (row.get("phone") or "").strip(),
                "url": (row.get("url") or "").strip(),
            }


# ---------------------------------------------------------------------------
# PDF input (heuristic text-parsing path)
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"https://www\.mudah\.my/.*?\.htm", re.IGNORECASE | re.DOTALL)
PRICE_RE = re.compile(r"RM\s*([\d,]+)")
PHONE_RE = re.compile(r"'(\d[\d]*)\s*$")
TITLE_TYPE_RE = re.compile(r"\b(Freehold|Leasehold)\b")


def extract_pdf_text(pdf_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def rows_from_pdf_text(full_text: str, listing_type: str = "sale"):
    pieces_raw = URL_RE.split(full_text)
    urls_raw = URL_RE.findall(full_text)

    pieces = [re.sub(r"\s+", " ", p) for p in pieces_raw]
    urls = [re.sub(r"\s+", "", u) for u in urls_raw]

    for i, url in enumerate(urls):
        chunk = pieces[i]
        if i == 0:
            chunk = re.sub(
                r"^\s*title\s+price\s+location\s+beds\s+baths\s+size_sqft\s+"
                r"property_type\s+title_type\s+seller_name\s+phone\s+url\s*",
                "",
                chunk,
            )

        price_match = PRICE_RE.search(chunk)
        if not price_match:
            continue
        title = chunk[: price_match.start()].strip()
        price = "RM " + price_match.group(1)

        remainder = chunk[price_match.end():]
        phone_match = PHONE_RE.search(remainder)
        phone = phone_match.group(1) if phone_match else ""
        before_phone = remainder[: phone_match.start()] if phone_match else remainder

        tt_matches = list(TITLE_TYPE_RE.finditer(before_phone))
        if tt_matches:
            seller_name = before_phone[tt_matches[-1].end():].strip()
        else:
            words = before_phone.strip().split()
            seller_name = " ".join(words[-3:]) if words else ""

        if not title or not seller_name:
            continue

        yield {
            "listing_id": "",
            "listing_type": listing_type,
            "seller_name": seller_name,
            "title": title,
            "price": price,
            "phone": phone,
            "url": url,
        }


def rows_from_pdf(pdf_path: str, listing_type: str = "sale"):
    yield from rows_from_pdf_text(extract_pdf_text(pdf_path), listing_type)


def rows_from_pdf_dir(pdf_dir: str, listing_type: str = "sale"):
    for name in sorted(os.listdir(pdf_dir)):
        if name.lower().endswith(".pdf"):
            yield from rows_from_pdf(os.path.join(pdf_dir, name), listing_type)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_already_drafted(log_path: str) -> set:
    if not log_path or not os.path.exists(log_path):
        return set()
    with open(log_path, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_drafted_log(log_path: str, keys: set):
    if not log_path:
        return
    with open(log_path, "w", encoding="utf-8") as f:
        for k in sorted(keys):
            f.write(k + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="Path to a structured CSV (scraper output)")
    src.add_argument("--pdf", help="Path to a single PDF export")
    src.add_argument("--pdf-dir", help="Path to a folder of PDF exports")
    ap.add_argument("--out", default="drafts.csv", help="Output CSV path (default: drafts.csv)")
    ap.add_argument("--type", choices=["sale", "rent"], default=None,
                    help="Only draft this listing type (CSV), or set the type for PDFs (default sale)")
    ap.add_argument(
        "--skip-drafted-log",
        default=None,
        help="Text file tracking listing keys already drafted. Listings in it are skipped; new ones are added.",
    )
    args = ap.parse_args()

    pdf_type = args.type or "sale"
    if args.csv:
        rows = list(rows_from_csv(args.csv))
    elif args.pdf:
        rows = list(rows_from_pdf(args.pdf, pdf_type))
    else:
        rows = list(rows_from_pdf_dir(args.pdf_dir, pdf_type))

    if args.type:
        rows = [r for r in rows if r["listing_type"] == args.type]

    already = load_already_drafted(args.skip_drafted_log)
    new_keys = set(already)

    out_rows = []
    for r in rows:
        base = r["listing_id"] or r["url"] or (r["seller_name"] + "|" + r["title"])
        key = base  # listing_ids are unique across sale and rent
        if key in already:
            continue
        draft = make_draft(r["seller_name"], r["title"], r["price"], r["listing_type"])
        out_rows.append({**r, "draft_message": draft})
        new_keys.add(key)

    out_path = Path(args.out)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["listing_id", "listing_type", "seller_name", "title", "price", "phone", "url", "draft_message"],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    txt_path = out_path.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(f"### [{r['listing_type'].upper()}] {r['seller_name']}  |  {r['phone']}  |  {r['url']}\n")
            f.write(r["draft_message"] + "\n")
            f.write("\n----\n\n")

    if args.skip_drafted_log:
        save_drafted_log(args.skip_drafted_log, new_keys)

    print(f"Parsed {len(rows)} listing rows.")
    print(f"Generated {len(out_rows)} new draft(s).")
    print(f"CSV:  {out_path}")
    print(f"TXT:  {txt_path}")
    if len(rows) and not out_rows:
        print("(0 new drafts - likely all already in --skip-drafted-log)")


if __name__ == "__main__":
    main()
