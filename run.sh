#!/bin/sh
# Full pipeline: parse accounts, filter the company snapshot, then run the SQL in order.
# Needs the two Companies House zip files in data/raw/ (see README) and a running PostgreSQL.
set -e
export PGHOST="${PGHOST:-localhost}" PGUSER="${PGUSER:-postgres}"

COMPANIES=$(ls data/raw/BasicCompanyDataAsOneFile-*.zip | head -1)

python3 scripts/parse_ixbrl.py data data/raw/Accounts_Bulk_Data-*.zip
python3 scripts/filter_companies.py "$COMPANIES" data/filings.csv data/companies.csv

mkdir -p results
psql -q -v ON_ERROR_STOP=1 -f sql/01_schema.sql
psql -v ON_ERROR_STOP=1 -f sql/02_load.sql
psql -v ON_ERROR_STOP=1 -f sql/03_mapping.sql    > results/03_mapping_output.txt
psql -v ON_ERROR_STOP=1 -f sql/04_checks.sql     > results/04_checks_output.txt
psql -v ON_ERROR_STOP=1 -f sql/05_analysis.sql   > results/05_analysis_output.txt
psql -v ON_ERROR_STOP=1 -f sql/06_performance.sql > results/06_performance_output.txt
python3 scripts/make_charts.py
# Optional, needs an API key in .env:
# python3 scripts/llm_map.py && python3 scripts/evaluate_mapping.py
echo "Done. See results/"
