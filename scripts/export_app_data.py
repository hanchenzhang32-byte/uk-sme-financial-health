"""Export the data used by the review web app (separate repository: sme-review-app).

Usage: python scripts/export_app_data.py ../sme-review-app/data

Writes three CSV files:
  companies.csv     test-set companies from the distress model, with last year's and this year's
                    balance sheet and the model's risk score (scored without seeing this year)
  data_issues.csv   data quality issues found by sql/04_checks.sql for those filings
  review_queue.csv  LLM tag mappings that a person should check: the LLM disagrees with a rule,
                    is unsure (confidence below 0.6), or suggests a mapping the rules do not have
Needs the database built by run.sh and data/distress_dataset.csv from sql/07_features.sql.
"""
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_distress as td  # noqa: E402


def sql(query):
    out = subprocess.check_output(["psql", "-X", "-v", "ON_ERROR_STOP=1", "--csv", "-c", query])
    return pd.read_csv(io.StringIO(out.decode()), keep_default_na=False, na_values=[""])


def main(out_dir="../sme-review-app/data"):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Same population, split and model as scripts/train_distress.py, so the scores are out of sample
    df = pd.read_csv("data/distress_dataset.csv")
    df = df[df.in_population == 1].reset_index(drop=True)
    train, test = train_test_split(df, test_size=0.25, stratify=df.label, random_state=td.SEED)
    model = td.boosting_model().fit(train[td.FEATURES], train.label)
    test = test.assign(risk_score=model.predict_proba(test[td.FEATURES])[:, 1])
    test["risk_percentile"] = (test.risk_score.rank(pct=True) * 100).round(1)
    ids = ",".join(str(i) for i in test.filing_id)

    sheets = sql(f"""
        WITH cur AS (SELECT * FROM sme.clean_balance_sheets WHERE is_current_year AND filing_id IN ({ids})),
        pri AS (SELECT DISTINCT ON (c.filing_id) c.* FROM sme.clean_balance_sheets c JOIN sme.filings f USING (filing_id)
                WHERE NOT c.is_current_year AND c.filing_id IN ({ids})
                  AND c.period_end BETWEEN f.balance_sheet_date - 400 AND f.balance_sheet_date - 330
                ORDER BY c.filing_id, abs((f.balance_sheet_date - c.period_end) - 365))
        SELECT cur.filing_id, co.company_number, co.name, coalesce(s.section_name, 'Unknown') AS sector,
               co.incorporation_date, co.account_category,
               cur.period_end AS period_end, pri.period_end AS prior_period_end,
               cur.cash, cur.current_assets, cur.fixed_assets, cur.creditors_within_1y,
               cur.creditors_after_1y, cur.net_current_assets, cur.net_assets AS net_assets_as_filed,
               cur.net_assets_clean AS net_assets,
               pri.cash AS prior_cash, pri.current_assets AS prior_current_assets,
               pri.fixed_assets AS prior_fixed_assets, pri.creditors_within_1y AS prior_creditors_within_1y,
               pri.creditors_after_1y AS prior_creditors_after_1y,
               pri.net_current_assets AS prior_net_current_assets, pri.net_assets_clean AS prior_net_assets
        FROM cur JOIN pri USING (filing_id)
        JOIN sme.companies co ON co.company_number = cur.company_number
        LEFT JOIN sme.sic_sections s ON substr(co.sic_code, 1, 2) ~ '^[0-9]{{2}}$'
             AND substr(co.sic_code, 1, 2)::int BETWEEN s.first_div AND s.last_div""")
    companies = sheets.merge(test[["filing_id", "risk_score", "risk_percentile"]], on="filing_id")
    companies["risk_score"] = companies.risk_score.round(4)
    companies.to_csv(out / "companies.csv", index=False)

    issues = sql(f"SELECT filing_id, check_name, detail FROM sme.data_issues WHERE filing_id IN ({ids}) "
                 "ORDER BY filing_id, check_name")
    issues.to_csv(out / "data_issues.csv", index=False)

    # 2. Review queue
    llm = pd.read_csv("results/llm_mapping.csv", keep_default_na=False)
    rules = sql("SELECT tag, dimensions, item_code AS rule_label FROM sme.tag_mappings")
    rules["dimensions"] = rules.dimensions.fillna("")
    q = llm.merge(rules, on=["tag", "dimensions"], how="left")
    q["rule_label"] = q.rule_label.fillna("")
    has_rule = q.rule_label != ""
    q = q[(~has_rule & (q.llm_label != "none"))
          | (has_rule & ((q.confidence < 0.6) | (q.llm_label != q.rule_label)))]
    q = q.sort_values("facts", ascending=False)
    q.to_csv(out / "review_queue.csv", index=False)

    print(f"companies: {len(companies):,}  issues: {len(issues):,}  review queue: {len(q)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
