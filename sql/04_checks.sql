-- 04_checks.sql: data quality checks. Each check writes its findings into data_issues.
SET search_path TO sme;
TRUNCATE data_issues;

-- One row per filing and period, with the items side by side (conditional aggregation)
CREATE OR REPLACE VIEW balance_sheets AS
SELECT fi.filing_id,
       fi.company_number,
       fin.period_end,
       (fin.period_end = fi.balance_sheet_date) AS is_current_year,
       max(value_gbp) FILTER (WHERE item_code = 'cash')                   AS cash,
       max(value_gbp) FILTER (WHERE item_code = 'current_assets')         AS current_assets,
       max(value_gbp) FILTER (WHERE item_code = 'fixed_assets')           AS fixed_assets,
       max(value_gbp) FILTER (WHERE item_code = 'creditors_within_1y')    AS creditors_within_1y,
       max(value_gbp) FILTER (WHERE item_code = 'creditors_after_1y')     AS creditors_after_1y,
       max(value_gbp) FILTER (WHERE item_code = 'prepayments_outside_ca') AS prepayments_outside_ca,
       max(value_gbp) FILTER (WHERE item_code = 'accruals_outside_cl')    AS accruals_outside_cl,
       max(value_gbp) FILTER (WHERE item_code = 'provisions')             AS provisions,
       max(value_gbp) FILTER (WHERE item_code = 'net_current_assets')     AS net_current_assets,
       max(value_gbp) FILTER (WHERE item_code = 'total_assets_less_cl')   AS total_assets_less_cl,
       max(value_gbp) FILTER (WHERE item_code = 'net_assets')             AS net_assets
FROM financials fin
JOIN filings fi USING (filing_id)
WHERE fin.item_code <> 'employees'
GROUP BY fi.filing_id, fi.company_number, fin.period_end, fi.balance_sheet_date;

-- What the totals should be, recomputed from their parts
CREATE OR REPLACE VIEW recomputed AS
SELECT *,
       -- micro-entity layout (FRS 105): prepayments count in net current assets,
       -- accruals are deducted later, after total assets less current liabilities
       current_assets - creditors_within_1y + coalesce(prepayments_outside_ca, 0)  AS nca_expected,
       coalesce(fixed_assets, 0) + current_assets - creditors_within_1y
         + coalesce(prepayments_outside_ca, 0) - coalesce(creditors_after_1y, 0)
         - coalesce(provisions, 0) - coalesce(accruals_outside_cl, 0)              AS na_expected
FROM balance_sheets
WHERE current_assets IS NOT NULL AND creditors_within_1y IS NOT NULL;

-- 1. The same company and balance sheet date filed more than once (usually revised accounts)
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT filing_id, 'duplicate_filing',
       format('%s filings for company %s at %s', n, company_number, balance_sheet_date)
FROM (SELECT filing_id, company_number, balance_sheet_date,
             count(*) OVER (PARTITION BY company_number, balance_sheet_date) AS n
      FROM filings) d
WHERE n > 1;

-- 2. The same tag, period and dimensions reported with two different values in one filing
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT filing_id, 'conflicting_values',
       format('%s at %s has %s different values', tag, period_end, count(DISTINCT value))
FROM raw_facts
WHERE tag IN (SELECT tag FROM tag_mappings) AND unit = 'GBP'
GROUP BY filing_id, tag, period_start, period_end, dimensions
HAVING count(DISTINCT value) > 1;

-- 3. Net current liabilities shown in brackets on the page but tagged without a minus sign
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT filing_id, 'sign_error_net_current_assets',
       format('should be %s, tagged as %s', nca_expected, net_current_assets)
FROM recomputed
WHERE is_current_year AND nca_expected < -10
  AND abs(net_current_assets + nca_expected) <= greatest(10, 0.01 * abs(nca_expected));

-- 4. Net current assets that do not add up for any other reason
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT filing_id, 'net_current_assets_mismatch',
       format('parts add up to %s, reported as %s', nca_expected, net_current_assets)
FROM recomputed
WHERE is_current_year
  AND abs(nca_expected - net_current_assets) > greatest(10, 0.01 * abs(net_current_assets))
  AND NOT abs(net_current_assets + nca_expected) <= greatest(10, 0.01 * abs(nca_expected));

-- 5. Net liabilities tagged without a minus sign
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT filing_id, 'sign_error_net_assets',
       format('should be %s, tagged as %s', na_expected, net_assets)
FROM recomputed
WHERE is_current_year AND na_expected < -10
  AND abs(net_assets + na_expected) <= greatest(10, 0.01 * abs(na_expected));

-- 6. Possible unit error: this year about 1,000 times last year (or the other way round)
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT cur.filing_id, 'possible_unit_error',
       format('current assets %s this year vs %s last year', cur.current_assets, pri.current_assets)
FROM balance_sheets cur
JOIN balance_sheets pri ON pri.filing_id = cur.filing_id AND NOT pri.is_current_year
WHERE cur.is_current_year
  AND least(abs(cur.current_assets), abs(pri.current_assets)) >= 100
  AND greatest(abs(cur.current_assets), abs(pri.current_assets))
      / least(abs(cur.current_assets), abs(pri.current_assets)) BETWEEN 500 AND 2000;

-- 7. No net assets figure at all for the current year
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT f.filing_id, 'missing_net_assets', 'no NetAssetsLiabilities or total Equity for the balance sheet date'
FROM filings f
WHERE NOT EXISTS (SELECT 1 FROM financials fin
                  WHERE fin.filing_id = f.filing_id
                    AND fin.period_end = f.balance_sheet_date
                    AND fin.item_code = 'net_assets');

-- 8. Accounts reported in a currency other than pounds (left out of the analysis)
INSERT INTO data_issues (filing_id, check_name, detail)
SELECT filing_id, 'non_gbp_currency', string_agg(DISTINCT unit, ', ')
FROM raw_facts
WHERE unit IN ('USD', 'EUR')
GROUP BY filing_id;

-- Summary
SELECT check_name, count(DISTINCT filing_id) AS filings_flagged,
       round(100.0 * count(DISTINCT filing_id) / (SELECT count(*) FROM filings), 2) AS pct_of_filings
FROM data_issues
GROUP BY check_name
ORDER BY filings_flagged DESC;
