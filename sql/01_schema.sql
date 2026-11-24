-- 01_schema.sql: tables for Companies House accounts data
DROP SCHEMA IF EXISTS sme CASCADE;
CREATE SCHEMA sme;
SET search_path TO sme;

-- One row per company, from the Companies House monthly snapshot (live companies only)
CREATE TABLE companies (
    company_number     CHAR(8) PRIMARY KEY,
    name               TEXT NOT NULL,
    category           TEXT,
    status             TEXT NOT NULL,
    incorporation_date DATE,
    account_category   TEXT,
    sic_text           TEXT,
    sic_code           CHAR(5) GENERATED ALWAYS AS (left(sic_text, 5)) STORED
);

-- One row per set of accounts. No foreign key to companies on purpose:
-- a company that has been dissolved since the snapshot is missing from companies,
-- but its accounts are still real data that we want to keep.
CREATE TABLE filings (
    filing_id          INT PRIMARY KEY,
    company_number     CHAR(8) NOT NULL,
    balance_sheet_date DATE NOT NULL,
    source_file        TEXT NOT NULL UNIQUE,
    bulk_file          TEXT NOT NULL      -- which daily Companies House zip it came from
);

-- Every number in every set of accounts, exactly as it was tagged (already scaled to units)
CREATE TABLE raw_facts (
    fact_id      BIGSERIAL PRIMARY KEY,
    filing_id    INT NOT NULL REFERENCES filings,
    tag          TEXT NOT NULL,
    period_start DATE,            -- NULL for balance sheet items (a point in time)
    period_end   DATE NOT NULL,
    dimensions   TEXT NOT NULL DEFAULT '',
    unit         TEXT,
    scale        SMALLINT,
    value        NUMERIC(20, 2) NOT NULL
);

-- The small set of balance sheet items we analyse
CREATE TABLE standard_items (
    item_code   TEXT PRIMARY KEY,
    item_name   TEXT NOT NULL,
    period_type TEXT NOT NULL CHECK (period_type IN ('instant', 'duration'))
);

-- Which tag (plus dimensions) means which standard item. Lower priority number wins.
CREATE TABLE tag_mappings (
    mapping_id SERIAL PRIMARY KEY,
    tag        TEXT NOT NULL,
    dimensions TEXT NOT NULL DEFAULT '',
    item_code  TEXT NOT NULL REFERENCES standard_items,
    priority   SMALLINT NOT NULL DEFAULT 1 CHECK (priority > 0),
    method     TEXT NOT NULL CHECK (method IN ('rule', 'manual')),
    note       TEXT,
    UNIQUE (tag, dimensions)
);

-- Clean, standardised figures: one value per filing, period and item
CREATE TABLE financials (
    filing_id  INT NOT NULL REFERENCES filings,
    period_end DATE NOT NULL,
    item_code  TEXT NOT NULL REFERENCES standard_items,
    value_gbp  NUMERIC(20, 2) NOT NULL,
    source_tag TEXT NOT NULL,
    PRIMARY KEY (filing_id, period_end, item_code)
);

-- Problems found by the checks in 04_checks.sql
CREATE TABLE data_issues (
    issue_id   SERIAL PRIMARY KEY,
    filing_id  INT REFERENCES filings,
    check_name TEXT NOT NULL,
    detail     TEXT
);
