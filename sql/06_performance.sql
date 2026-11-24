-- 06_performance.sql: does an index help? Same query before and after.
-- Query: all balance sheet figures of one company (what an analyst looks up most often)
SET search_path TO sme;
DROP INDEX IF EXISTS idx_filings_company;
DROP INDEX IF EXISTS idx_raw_facts_filing_tag;
ANALYZE;

\echo '--- before indexes ---'
EXPLAIN (ANALYZE, COSTS OFF, TIMING ON)
SELECT r.tag, r.period_end, r.value
FROM filings f
JOIN raw_facts r USING (filing_id)
WHERE f.company_number = '10722905'
  AND r.tag IN ('CurrentAssets', 'Creditors', 'NetAssetsLiabilities');

CREATE INDEX idx_filings_company      ON filings (company_number);
CREATE INDEX idx_raw_facts_filing_tag ON raw_facts (filing_id, tag);
ANALYZE;

\echo '--- after indexes ---'
EXPLAIN (ANALYZE, COSTS OFF, TIMING ON)
SELECT r.tag, r.period_end, r.value
FROM filings f
JOIN raw_facts r USING (filing_id)
WHERE f.company_number = '10722905'
  AND r.tag IN ('CurrentAssets', 'Creditors', 'NetAssetsLiabilities');
