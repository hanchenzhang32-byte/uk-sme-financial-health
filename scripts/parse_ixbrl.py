"""Parse Companies House iXBRL accounts into flat CSV files.

Usage:
    python scripts/parse_ixbrl.py data/ data/raw/Accounts_Bulk_Data-*.zip

Writes two files:
    filings.csv  one row per set of accounts (company number, balance sheet date, file name, daily zip)
    facts.csv    one row per numeric figure (ix:nonFraction) in the accounts

Only inline XBRL files (.html) are parsed. Nested .zip packages are counted and skipped.
"""

import csv
import re
import sys
import zipfile
from collections import Counter

from lxml import etree

PARSER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)
FILE_RE = re.compile(r"_(\w{8})_(\d{8})(?:_.*)?\.html$")


def local(tag):
    """'{namespace}Debtors' -> 'Debtors'"""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def read_contexts(root):
    """Map context id -> (period_start, period_end, dimensions)."""
    contexts = {}
    for ctx in root.iter():
        if local(ctx.tag) != "context":
            continue
        start = end = None
        dims = []
        for el in ctx.iter():
            name = local(el.tag)
            if name == "instant":
                end = (el.text or "").strip()
            elif name == "startDate":
                start = (el.text or "").strip()
            elif name == "endDate":
                end = (el.text or "").strip()
            elif name in ("explicitMember", "typedMember"):
                value = (el.text or "".join(el.itertext())).strip()
                dims.append(f"{el.get('dimension', '').split(':')[-1]}={value.split(':')[-1]}")
        contexts[ctx.get("id")] = (start, end, ";".join(sorted(dims)))
    return contexts


def read_units(root):
    """Map unit id -> measure, e.g. 'u0' -> 'GBP', 'u8' -> 'pure'."""
    units = {}
    for unit in root.iter():
        if local(unit.tag) != "unit":
            continue
        measures = [(m.text or "").strip().split(":")[-1] for m in unit.iter() if local(m.tag) == "measure"]
        units[unit.get("id")] = "/".join(measures)
    return units


def parse_value(el):
    """Turn the displayed text into a number, using the iXBRL format, scale and sign attributes."""
    text = "".join(el.itertext()).strip()
    fmt = (el.get("format") or "").lower()
    if "zero" in fmt or ("dash" in fmt and text in ("-", "–", "—", "")):
        number = 0.0
    else:
        cleaned = re.sub(r"[^0-9.,]", "", text)
        if "commadecimal" in fmt or "numdotcomma" in fmt:  # 1.234,56 style
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:  # 1,234.56 style (the usual UK format)
            cleaned = cleaned.replace(",", "")
        if cleaned in ("", "."):
            if text in ("-", "–", "—", "nil", "Nil"):
                number = 0.0
            else:
                return None
        else:
            number = float(cleaned)
    scale = el.get("scale")
    if scale:
        number *= 10 ** int(scale)
    if el.get("sign") == "-":
        number = -number
    return number


def main(out_dir, zip_paths):
    stats = Counter()
    with open(f"{out_dir}/filings.csv", "w", newline="") as ff, \
            open(f"{out_dir}/facts.csv", "w", newline="") as fx:
        fw, xw = csv.writer(ff), csv.writer(fx)
        fw.writerow(["filing_id", "company_number", "balance_sheet_date", "source_file", "bulk_file"])
        xw.writerow(["filing_id", "tag", "period_start", "period_end", "dimensions", "unit", "scale", "value"])
        filing_id = 0
        for zip_path in sorted(zip_paths):
            filing_id = parse_zip(zip_path, fw, xw, filing_id, stats)
    for k, v in sorted(stats.items()):
        print(f"{k}: {v}")


def parse_zip(zip_path, fw, xw, filing_id, stats):
    bulk_file = zip_path.replace("\\", "/").split("/")[-1]
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not name.endswith(".html"):
                stats["skipped_not_html"] += 1
                continue
            m = FILE_RE.search(name)
            if not m:
                stats["skipped_bad_name"] += 1
                continue
            root = etree.fromstring(z.read(name), PARSER)
            if root is None:
                stats["skipped_unreadable"] += 1
                continue
            filing_id += 1
            company, bsd = m.group(1), m.group(2)
            fw.writerow([filing_id, company, f"{bsd[:4]}-{bsd[4:6]}-{bsd[6:]}", name, bulk_file])
            contexts = read_contexts(root)
            units = read_units(root)
            for el in root.iter():
                if local(el.tag) != "nonFraction":
                    continue
                value = parse_value(el)
                if value is None:
                    stats["facts_unparsed"] += 1
                    continue
                start, end, dims = contexts.get(el.get("contextRef"), (None, None, ""))
                xw.writerow([filing_id, (el.get("name") or "").split(":")[-1], start or "", end or "",
                             dims, units.get(el.get("unitRef"), ""), el.get("scale") or "", value])
                stats["facts"] += 1
            stats["filings"] += 1
    return filing_id


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
