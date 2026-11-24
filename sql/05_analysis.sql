-- 05_analysis.sql: balance sheet health of small UK companies, by sector and by company age
SET search_path TO sme;

-- SIC 2007: the first two digits of a SIC code (the division) give the broad section
CREATE TABLE IF NOT EXISTS sic_sections (
    section      CHAR(1) PRIMARY KEY,
    first_div    SMALLINT NOT NULL,
    last_div     SMALLINT NOT NULL CHECK (last_div >= first_div),
    section_name TEXT NOT NULL
);
TRUNCATE sic_sections;
INSERT INTO sic_sections VALUES
    ('A',  1,  3, 'Agriculture, forestry and fishing'),
    ('B',  5,  9, 'Mining and quarrying'),
    ('C', 10, 33, 'Manufacturing'),
    ('D', 35, 35, 'Electricity and gas'),
    ('E', 36, 39, 'Water and waste'),
    ('F', 41, 43, 'Construction'),
    ('G', 45, 47, 'Wholesale and retail'),
    ('H', 49, 53, 'Transport and storage'),
    ('I', 55, 56, 'Accommodation and food'),
    ('J', 58, 63, 'Information and communication'),
    ('K', 64, 66, 'Finance and insurance'),
    ('L', 68, 68, 'Real estate'),
    ('M', 69, 75, 'Professional and technical'),
    ('N', 77, 82, 'Admin and support services'),
    ('O', 84, 84, 'Public administration'),
    ('P', 85, 85, 'Education'),
    ('Q', 86, 88, 'Health and social work'),
    ('R', 90, 93, 'Arts and recreation'),
    ('S', 94, 96, 'Other services'),
    ('T', 97, 98, 'Residents property management'),
    ('U', 99, 99, 'Extraterritorial bodies');

-- The analysis set: current-year balance sheets of trading companies, with sign errors corrected
CREATE OR REPLACE VIEW analysis_set AS
WITH latest AS (   -- if a company filed twice for the same date, keep the later filing
    SELECT DISTINCT ON (company_number, balance_sheet_date) filing_id
    FROM filings
    ORDER BY company_number, balance_sheet_date, filing_id DESC
)
SELECT b.filing_id,
       b.company_number,
       c.status,
       s.section,
       s.section_name,
       date_part('year', age(b.period_end, c.incorporation_date)) AS company_age_years,
       b.current_assets,
       b.creditors_within_1y,
       b.net_assets AS net_assets_as_tagged,
       CASE WHEN EXISTS (SELECT 1 FROM data_issues d
                         WHERE d.filing_id = b.filing_id AND d.check_name = 'sign_error_net_assets')
            THEN -b.net_assets ELSE b.net_assets END AS net_assets,
       b.current_assets / NULLIF(b.creditors_within_1y, 0) AS current_ratio
FROM balance_sheets b
JOIN latest USING (filing_id)
JOIN companies c USING (company_number)
LEFT JOIN sic_sections s
       ON substr(c.sic_code, 1, 2) ~ '^[0-9]{2}$'
      AND substr(c.sic_code, 1, 2)::int BETWEEN s.first_div AND s.last_div
WHERE b.is_current_year
  AND b.net_assets IS NOT NULL
  AND c.account_category IS DISTINCT FROM 'DORMANT'
  AND c.sic_code NOT IN ('99999', '74990')     -- dormant and non-trading companies
  AND NOT EXISTS (SELECT 1 FROM data_issues d
                  WHERE d.filing_id = b.filing_id
                    AND d.check_name IN ('non_gbp_currency', 'possible_unit_error', 'net_current_assets_mismatch'));

-- Headline: why the sign check matters
SELECT count(*) AS companies,
       round(100.0 * avg((net_assets_as_tagged < 0)::int), 1) AS pct_negative_net_assets_as_tagged,
       round(100.0 * avg((net_assets < 0)::int), 1)           AS pct_negative_net_assets_corrected
FROM analysis_set;

-- By sector (sections with at least 150 companies)
\copy (SELECT section, section_name, count(*) AS companies, round(100.0 * avg((net_assets < 0)::int), 1) AS pct_negative_net_assets, round(100.0 * avg((current_ratio < 1)::int) FILTER (WHERE current_ratio IS NOT NULL), 1) AS pct_current_ratio_below_1, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY current_ratio)::numeric, 2) AS median_current_ratio FROM analysis_set WHERE section IS NOT NULL GROUP BY section, section_name HAVING count(*) >= 150 ORDER BY pct_negative_net_assets DESC) TO 'results/by_sector.csv' WITH (FORMAT csv, HEADER)

-- By company age
\copy (SELECT CASE WHEN company_age_years < 2 THEN '0-1 years' WHEN company_age_years < 5 THEN '2-4 years' WHEN company_age_years < 10 THEN '5-9 years' ELSE '10+ years' END AS age_band, count(*) AS companies, round(100.0 * avg((net_assets < 0)::int), 1) AS pct_negative_net_assets, round(100.0 * avg((current_ratio < 1)::int) FILTER (WHERE current_ratio IS NOT NULL), 1) AS pct_current_ratio_below_1 FROM analysis_set WHERE company_age_years IS NOT NULL GROUP BY 1 ORDER BY min(company_age_years)) TO 'results/by_age.csv' WITH (FORMAT csv, HEADER)

-- Are firms already proposed for strike-off weaker? (snapshot taken before these accounts were filed)
SELECT status, count(*) AS companies,
       round(100.0 * avg((net_assets < 0)::int), 1) AS pct_negative_net_assets
FROM analysis_set
GROUP BY status
HAVING count(*) >= 20
ORDER BY companies DESC;
