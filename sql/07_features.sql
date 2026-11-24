-- 07_features.sql: dataset for predicting distress one year ahead.
-- Features come ONLY from last year's balance sheet (the prior-year column of each filing),
-- the label comes from this year's balance sheet. Using anything from this year as a
-- feature would leak the answer.
SET search_path TO sme;
DROP VIEW IF EXISTS distress_dataset;

-- Net assets with the sign error fixed, for every period (this year and last year)
CREATE OR REPLACE VIEW clean_balance_sheets AS
SELECT b.*,
       CASE WHEN rc.na_expected < -10
             AND abs(b.net_assets + rc.na_expected) <= greatest(10, 0.01 * abs(rc.na_expected))
            THEN -b.net_assets ELSE b.net_assets END AS net_assets_clean
FROM balance_sheets b
LEFT JOIN recomputed rc USING (filing_id, period_end);

CREATE OR REPLACE VIEW distress_dataset AS
WITH latest AS (   -- one filing per company and balance sheet date
    SELECT DISTINCT ON (company_number, balance_sheet_date) filing_id, balance_sheet_date
    FROM filings
    ORDER BY company_number, balance_sheet_date, filing_id DESC
),
prior AS (         -- the comparative column closest to one year before the balance sheet date
    SELECT DISTINCT ON (c.filing_id) c.*
    FROM clean_balance_sheets c
    JOIN latest l USING (filing_id)
    WHERE NOT c.is_current_year
      AND c.period_end BETWEEN l.balance_sheet_date - 400 AND l.balance_sheet_date - 330
    ORDER BY c.filing_id, abs((l.balance_sheet_date - c.period_end) - 365)
),
base AS (
    SELECT p.filing_id,
           p.company_number,
           s.section,
           date_part('year', age(p.period_end, co.incorporation_date))              AS company_age_years,
           coalesce(p.fixed_assets, 0) + coalesce(p.current_assets, 0)
             + coalesce(p.prepayments_outside_ca, 0)                                 AS total_assets,
           p.current_assets, p.creditors_within_1y, p.cash, p.creditors_after_1y, p.fixed_assets,
           p.net_current_assets, co.account_category,
           p.net_assets_clean AS prior_net_assets,
           p.net_assets       AS prior_net_assets_as_tagged,
           cur.net_assets_clean AS current_net_assets,
           cur.net_assets       AS current_net_assets_as_tagged
    FROM prior p
    JOIN clean_balance_sheets cur ON cur.filing_id = p.filing_id AND cur.is_current_year
    JOIN companies co ON co.company_number = p.company_number
    LEFT JOIN sic_sections s
           ON substr(co.sic_code, 1, 2) ~ '^[0-9]{2}$'
          AND substr(co.sic_code, 1, 2)::int BETWEEN s.first_div AND s.last_div
    WHERE co.account_category IS DISTINCT FROM 'DORMANT'
      AND co.sic_code NOT IN ('99999', '74990')
      AND cur.net_assets IS NOT NULL AND p.net_assets IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM data_issues d
                      WHERE d.filing_id = p.filing_id
                        AND d.check_name IN ('non_gbp_currency', 'possible_unit_error',
                                             'net_current_assets_mismatch', 'duplicate_filing'))
)
SELECT filing_id,
       coalesce(section, '?')                                         AS section,
       company_age_years,
       ln(total_assets)                                               AS log_total_assets,
       prior_net_assets / total_assets                                AS equity_ratio,
       current_assets / NULLIF(creditors_within_1y, 0)                AS current_ratio,
       cash / total_assets                                            AS cash_ratio,
       coalesce(creditors_after_1y, 0) / total_assets                 AS long_term_debt_ratio,
       coalesce(fixed_assets, 0) / total_assets                       AS fixed_asset_ratio,
       coalesce(creditors_within_1y, 0) / total_assets                AS short_term_debt_ratio,
       net_current_assets / total_assets                              AS working_capital_ratio,
       (account_category = 'MICRO ENTITY')::int                       AS micro_entity,
       (cash IS NULL)::int                                            AS cash_missing,
       (current_net_assets < 0)::int                                  AS label,
       -- the same columns without the sign fix, to measure what the fix is worth
       prior_net_assets_as_tagged / total_assets                      AS equity_ratio_as_tagged,
       (current_net_assets_as_tagged < 0)::int                        AS label_as_tagged,
       (prior_net_assets > 0)::int                                    AS in_population,
       (prior_net_assets_as_tagged > 0)::int                          AS in_population_as_tagged
FROM base
WHERE total_assets >= 1000;

-- Who is in the population (positive net assets last year) and how many turned negative
SELECT count(*) FILTER (WHERE in_population = 1)                          AS companies,
       sum(label) FILTER (WHERE in_population = 1)                        AS turned_negative,
       round(100.0 * avg(label) FILTER (WHERE in_population = 1), 2)      AS pct_turned_negative,
       count(*) FILTER (WHERE in_population_as_tagged = 1)                AS companies_as_tagged,
       round(100.0 * avg(label_as_tagged) FILTER (WHERE in_population_as_tagged = 1), 2) AS pct_turned_negative_as_tagged
FROM distress_dataset;

\copy (SELECT * FROM distress_dataset) TO 'data/distress_dataset.csv' WITH (FORMAT csv, HEADER)
