"""Keep only the companies that appear in our accounts sample, and only the columns we use.

Usage:
    python scripts/filter_companies.py data/raw/BasicCompanyDataAsOneFile-2026-11-01.zip data/filings.csv data/companies.csv

The Companies House snapshot is about 2 GB unzipped, so it is read as a stream, row by row.
"""

import csv
import io
import sys
import zipfile

KEEP = {
    "CompanyNumber": "company_number",
    "CompanyName": "name",
    "CompanyCategory": "category",
    "CompanyStatus": "status",
    "IncorporationDate": "incorporation_date",
    "Accounts.AccountCategory": "account_category",
    "SICCode.SicText_1": "sic_text",
}


def main(zip_path, filings_path, out_path):
    with open(filings_path, newline="") as f:
        wanted = {row["company_number"] for row in csv.DictReader(f)}
    found = 0
    with zipfile.ZipFile(zip_path) as z:
        inner = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
        with z.open(inner) as raw, open(out_path, "w", newline="") as out:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"))
            header = [h.strip() for h in next(reader)]
            idx = {h: i for i, h in enumerate(header)}
            writer = csv.writer(out)
            writer.writerow(list(KEEP.values()))
            for row in reader:
                if len(row) < len(header):  # skip blank or broken lines
                    continue
                number = row[idx["CompanyNumber"]].strip()
                if number in wanted:
                    writer.writerow([row[idx[k]].strip() for k in KEEP])
                    found += 1
    print(f"companies in accounts sample: {len(wanted)}, found in snapshot: {found}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
