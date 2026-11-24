-- 03_mapping.sql: map raw tags to standard balance sheet items, then build the financials table
SET search_path TO sme;

-- Step 1: how concentrated are the tags? (top 15 tags and their share of all numbers)
SELECT tag,
       count(*) AS facts,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_all_facts
FROM raw_facts
GROUP BY tag
ORDER BY facts DESC
LIMIT 15;

INSERT INTO standard_items VALUES
    ('cash',                 'Cash at bank and in hand',                    'instant'),
    ('debtors',              'Debtors',                                     'instant'),
    ('current_assets',       'Current assets',                              'instant'),
    ('fixed_assets',         'Fixed assets',                                'instant'),
    ('creditors_within_1y',  'Creditors due within one year',               'instant'),
    ('creditors_after_1y',   'Creditors due after more than one year',      'instant'),
    ('net_current_assets',   'Net current assets (liabilities)',            'instant'),
    ('total_assets_less_cl', 'Total assets less current liabilities',       'instant'),
    ('net_assets',           'Net assets (liabilities)',                    'instant'),
    ('prepayments_outside_ca','Prepayments shown outside current assets',   'instant'),
    ('accruals_outside_cl',  'Accruals shown outside creditors',            'instant'),
    ('provisions',           'Provisions for liabilities',                  'instant'),
    ('employees',            'Average number of employees',                 'duration');

-- The same item is tagged in different ways by different accounting software.
-- Creditors due within one year alone appears with three different dimension sets.
INSERT INTO tag_mappings (tag, dimensions, item_code, priority, method, note) VALUES
    ('CashBankOnHand', '', 'cash', 1, 'rule', NULL),
    ('Debtors', '', 'debtors', 1, 'rule', 'total debtors'),
    ('Debtors', 'MaturitiesOrExpirationPeriodsDimension=WithinOneYear', 'debtors', 2, 'rule', 'used only if no total'),
    ('Debtors', 'FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments', 'debtors', 2, 'rule', 'used only if no total'),
    ('Debtors', 'FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments;MaturitiesOrExpirationPeriodsDimension=WithinOneYear', 'debtors', 2, 'rule', 'used only if no total'),
    ('CurrentAssets', '', 'current_assets', 1, 'rule', NULL),
    ('FixedAssets', '', 'fixed_assets', 1, 'rule', NULL),
    ('Creditors', 'MaturitiesOrExpirationPeriodsDimension=WithinOneYear', 'creditors_within_1y', 1, 'rule', 'style 1'),
    ('Creditors', 'FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments', 'creditors_within_1y', 1, 'rule', 'style 2'),
    ('Creditors', 'FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments;MaturitiesOrExpirationPeriodsDimension=WithinOneYear', 'creditors_within_1y', 1, 'rule', 'style 3'),
    ('Creditors', 'MaturitiesOrExpirationPeriodsDimension=AfterOneYear', 'creditors_after_1y', 1, 'rule', 'style 1'),
    ('Creditors', 'FinancialInstrumentCurrentNon-currentDimension=Non-currentFinancialInstruments', 'creditors_after_1y', 1, 'rule', 'style 2'),
    ('Creditors', 'FinancialInstrumentCurrentNon-currentDimension=Non-currentFinancialInstruments;MaturitiesOrExpirationPeriodsDimension=AfterOneYear', 'creditors_after_1y', 1, 'rule', 'style 3'),
    ('NetCurrentAssetsLiabilities', '', 'net_current_assets', 1, 'rule', NULL),
    ('TotalAssetsLessCurrentLiabilities', '', 'total_assets_less_cl', 1, 'rule', NULL),
    ('NetAssetsLiabilities', '', 'net_assets', 1, 'rule', NULL),
    ('Equity', '', 'net_assets', 2, 'rule', 'total equity equals net assets; used only if NetAssetsLiabilities is missing'),
    ('PrepaymentsAccruedIncomeNotExpressedWithinCurrentAssetSubtotal', '', 'prepayments_outside_ca', 1, 'rule', 'needed for the net current assets check'),
    ('AccruedLiabilitiesNotExpressedWithinCreditorsSubtotal', '', 'accruals_outside_cl', 1, 'rule', 'needed for the net current assets check'),
    ('ProvisionsForLiabilitiesBalanceSheetSubtotal', '', 'provisions', 1, 'rule', 'needed for the net assets check'),
    ('AverageNumberEmployeesDuringPeriod', '', 'employees', 1, 'rule', NULL);
-- Deliberately NOT mapped: 'Creditors' with no dimensions. In some accounts it means
-- creditors due within one year, in others total creditors, so it goes to manual review.

-- Step 2: build financials. For each filing, period and item keep the best-priority tag;
-- if the same tag appears twice with different values (it should not), keep the most common value.
INSERT INTO financials (filing_id, period_end, item_code, value_gbp, source_tag)
SELECT DISTINCT ON (r.filing_id, r.period_end, m.item_code)
       r.filing_id, r.period_end, m.item_code, r.value, r.tag
FROM raw_facts r
JOIN tag_mappings m ON m.tag = r.tag AND m.dimensions = r.dimensions
JOIN standard_items s ON s.item_code = m.item_code
WHERE (s.period_type = 'instant' AND r.period_start IS NULL AND r.unit = 'GBP')
   OR (s.period_type = 'duration' AND r.period_start IS NOT NULL)
GROUP BY r.filing_id, r.period_end, m.item_code, m.priority, r.value, r.tag
ORDER BY r.filing_id, r.period_end, m.item_code, m.priority, count(*) DESC;

-- Step 3: coverage. What share of numbers carrying a mapped tag made it into financials?
SELECT count(DISTINCT tag) AS distinct_tags,
       (SELECT count(DISTINCT tag) FROM tag_mappings) AS tags_mapped,
       round(100.0 * count(*) FILTER (WHERE tag IN (SELECT tag FROM tag_mappings)) / count(*), 1) AS pct_facts_with_mapped_tag
FROM raw_facts;

SELECT item_code,
       count(DISTINCT filing_id) AS filings_with_item,
       round(100.0 * count(DISTINCT filing_id) / (SELECT count(*) FROM filings), 1) AS pct_of_filings
FROM financials
JOIN filings f USING (filing_id)
WHERE financials.period_end = f.balance_sheet_date OR item_code = 'employees'
GROUP BY item_code
ORDER BY pct_of_filings DESC;

-- Manual review queue: unmapped variants of the items we care about
CREATE VIEW needs_review AS
SELECT r.tag, r.dimensions, count(*) AS facts
FROM raw_facts r
LEFT JOIN tag_mappings m ON m.tag = r.tag AND m.dimensions = r.dimensions
WHERE m.mapping_id IS NULL
  AND r.tag IN (SELECT tag FROM tag_mappings)
GROUP BY r.tag, r.dimensions
ORDER BY facts DESC;

SELECT * FROM needs_review LIMIT 8;
