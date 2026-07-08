#!/usr/bin/env python3
"""
generate_drafts.py

Scans Mudah.my property listing exports (PDF or CSV) and generates a
personalized outreach draft for each listing, based on `seller_name`,
`title`, and `price`.

USAGE
-----
From a folder of PDFs (e.g. exports of your scraper's results):
    python3 generate_drafts.py --pdf-dir /path/to/pdf_folder --out drafts.csv

From your scraper's CSV directly (recommended - far more reliable than
parsing PDF text, since the columns are already structured):
    python3 generate_drafts.py --csv /path/to/master.csv --out drafts.csv

From a single PDF:
    python3 generate_drafts.py --pdf /path/to/file.pdf --out drafts.csv

OUTPUT
------
Writes a CSV (`--out`, default drafts.csv) with columns:
    seller_name, title, price, phone, url, draft_message
and also a human-readable .txt file with the same basename, with one
draft per listing separated by "----".

NOTES
-----
- If you already run the GitHub Actions scraper that saves a master CSV
  with a `listing_id` column, prefer --csv: it's already structured, so
  there's no fragile text-parsing involved, and you can safely re-run
  this script on the deduplicated master file to draft outreach for only
  the listings you haven't contacted yet (see --skip-drafted-log).
- PDF parsing here uses a heuristic (title comes before the first "RM",
  the phone number is the token starting with "'" right before the URL,
  and seller_name is whatever sits between the last "Freehold"/
  "Leasehold" token and the phone number). This works well on PDF
  exports that preserve row structure (like Mudah.my listing exports)
  but is NOT bulletproof - always spot check drafts.csv before sending.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

AGENT_NAME = "Ammar Mirza"
AGENT_TITLE = "Realty Agent"
AGENT_FIRM = "CCI Property REN54406"
AGENT_SUPERVISOR = "Muazzam Ali"

DRAFT_TEMPLATE = """Hi {seller_name}, My name is {agent_name}, I am a {agent_title}. I'm from {agent_firm} supervised by {agent_supervisor}.

I got some interested (filtered loan checked) buyers looking around for your type of property.

saw your ads in Mudah titled '{title}' selling for {price}.

Let me know if you're interested and we can talk commissions and details. Any questions is open

Thank you for your time :)"""


def make_draft(seller_name: str, title: str, price: str) -> str:
    return DRAFT_TEMPLATE.format(
        seller_name=seller_name.strip(),
        title=title.strip(),
        price=price.strip(),
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
            phone = (row.get("phone") or "").strip()
            url = (row.get("url") or "").strip()
            listing_id = (row.get("listing_id") or "").strip()
            if not title or not seller_name:
                continue
            yield {
                "listing_id": listing_id,
                "seller_name": seller_name,
                "title": title,
                "price": price,
                "phone": phone,
                "url": url,
            }


# ---------------------------------------------------------------------------
# PDF input (heuristic text-parsing path)
# ---------------------------------------------------------------------------

# URLs can be broken across lines by the PDF text layer (e.g.
# "https://www.mudah.my/double-\nstorey-...htm"), so match across
# whitespace/newlines with DOTALL, then strip embedded whitespace after.
URL_RE = re.compile(r"https://www\.mudah\.my/.*?\.htm", re.IGNORECASE | re.DOTALL)
PRICE_RE = re.compile(r"RM\s*([\d,]+)")
PHONE_RE = re.compile(r"'(\d[\d]*)\s*$")
TITLE_TYPE_RE = re.compile(r"\b(Freehold|Leasehold)\b")


def extract_pdf_text(pdf_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        t = page.extract_text() or ""
        parts.append(t)
    return "\n".join(parts)


def rows_from_pdf_text(full_text: str):
    # Split on raw URLs first (they may still contain embedded newlines/
    # spaces from PDF line-wrapping), THEN normalize whitespace within
    # each resulting chunk. This avoids the URL's own whitespace being
    # collapsed into the surrounding text before we can find it.
    pieces_raw = URL_RE.split(full_text)
    urls_raw = URL_RE.findall(full_text)

    pieces = [re.sub(r"\s+", " ", p) for p in pieces_raw]
    urls = [re.sub(r"\s+", "", u) for u in urls_raw]

    # pieces[0] is header + row0's fields; pieces[i] for i>=1 is row i's fields
    # urls[i] is the URL that terminates pieces[i]
    for i, url in enumerate(urls):
        chunk = pieces[i]
        if i == 0:
            # strip the header line off the front of the first chunk
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

        # seller_name = whatever follows the LAST Freehold/Leasehold token
        tt_matches = list(TITLE_TYPE_RE.finditer(before_phone))
        if tt_matches:
            seller_name = before_phone[tt_matches[-1].end():].strip()
        else:
            # fallback: last 1-4 words before phone
            words = before_phone.strip().split()
            seller_name = " ".join(words[-3:]) if words else ""

        if not title or not seller_name:
            continue

        yield {
            "listing_id": "",
            "seller_name": seller_name,
            "title": title,
            "price": price,
            "phone": phone,
            "url": url,
        }


def rows_from_pdf(pdf_path: str):
    text = extract_pdf_text(pdf_path)
    yield from rows_from_pdf_text(text)


def rows_from_pdf_dir(pdf_dir: str):
    for name in sorted(os.listdir(pdf_dir)):
        if name.lower().endswith(".pdf"):
            yield from rows_from_pdf(os.path.join(pdf_dir, name))


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
    src.add_argument("--csv", help="Path to a structured CSV (e.g. your scraper's master CSV)")
    src.add_argument("--pdf", help="Path to a single PDF export")
    src.add_argument("--pdf-dir", help="Path to a folder of PDF exports")
    ap.add_argument("--out", default="drafts.csv", help="Output CSV path (default: drafts.csv)")
    ap.add_argument(
        "--skip-drafted-log",
        default=None,
        help="Path to a text file tracking listing keys already drafted (url or listing_id). "
             "If given, listings already in this log are skipped, and newly drafted ones are appended.",
    )
    args = ap.parse_args()

    if args.csv:
        rows = list(rows_from_csv(args.csv))
    elif args.pdf:
        rows = list(rows_from_pdf(args.pdf))
    else:
        rows = list(rows_from_pdf_dir(args.pdf_dir))

    already = load_already_drafted(args.skip_drafted_log)
    new_keys = set(already)

    out_rows = []
    for r in rows:
        key = r["listing_id"] or r["url"] or (r["seller_name"] + "|" + r["title"])
        if key in already:
            continue
        draft = make_draft(r["seller_name"], r["title"], r["price"])
        out_rows.append({**r, "draft_message": draft})
        new_keys.add(key)

    # Write CSV
    out_path = Path(args.out)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["listing_id", "seller_name", "title", "price", "phone", "url", "draft_message"]
        )
        writer.writeheader()
        for r in out_rows:
            writer.writerow(r)

    # Write human-readable TXT
    txt_path = out_path.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(f"### {r['seller_name']}  |  {r['phone']}  |  {r['url']}\n")
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
