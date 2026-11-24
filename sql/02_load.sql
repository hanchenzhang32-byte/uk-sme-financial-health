-- 02_load.sql: load the CSV files made by the Python scripts (run with psql from the repo folder)
SET search_path TO sme;
SET datestyle TO 'ISO, DMY';   -- the snapshot writes dates as dd/mm/yyyy

\copy companies (company_number, name, category, status, incorporation_date, account_category, sic_text) FROM 'data/companies.csv' WITH (FORMAT csv, HEADER, NULL '')
\copy filings (filing_id, company_number, balance_sheet_date, source_file, bulk_file) FROM 'data/filings.csv' WITH (FORMAT csv, HEADER)
\copy raw_facts (filing_id, tag, period_start, period_end, dimensions, unit, scale, value) FROM 'data/facts.csv' WITH (FORMAT csv, HEADER, NULL '', FORCE_NOT_NULL (dimensions))

ANALYZE;

SELECT (SELECT count(*) FROM companies) AS companies,
       (SELECT count(*) FROM filings)   AS filings,
       (SELECT count(*) FROM raw_facts) AS raw_facts;
