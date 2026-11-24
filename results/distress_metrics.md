# Distress prediction results
Companies: 38,352 with positive net assets last year (accounts registered 14 to 23 Nov 2026). Turned negative this year: 2,069 (5.39%).
Split: 75% train (28,764), 25% test (9,588), stratified, seed 42.
Base rate in test set: 5.39%, so a random ranking has PR-AUC about 0.054 and catches 10% of cases in the top 10%.

## Test set
| model | pr_auc | roc_auc | top10_caught | top10_capture_rate | top10_precision | top10_lift |
|---|---|---|---|---|---|---|
| Rule: lowest equity ratio | 0.118 | 0.722 | 144 | 27.9% | 15.0% | 2.78x |
| Logistic regression | 0.143 | 0.771 | 158 | 30.6% | 16.5% | 3.06x |
| Gradient boosting | 0.162 | 0.806 | 170 | 32.9% | 17.7% | 3.29x |
| Gradient boosting, no sign fix | 0.158 | 0.792 | 165 | 31.9% | 17.2% | 3.19x |

95% bootstrap intervals on the test set (1,000 resamples):

- Rule: lowest equity ratio: PR-AUC 0.105 to 0.135, top 10% capture 23.8% to 31.2%
- Logistic regression: PR-AUC 0.127 to 0.166, top 10% capture 27.5% to 35.1%
- Gradient boosting: PR-AUC 0.144 to 0.186, top 10% capture 29.5% to 37.2%

## 5-fold cross-validation on the training set
| model | pr_auc | roc_auc | top10_caught | top10_capture_rate | top10_precision | top10_lift |
|---|---|---|---|---|---|---|
| Logistic regression | 0.142 | 0.770 | 464 | 29.9% | 16.1% | 2.99x |
| Gradient boosting | 0.145 | 0.786 | 460 | 29.6% | 16.0% | 2.96x |

Training labels changed by the sign fix: 290 of 28,764.

## Permutation importance (gradient boosting, drop in test PR-AUC)
| feature | drop | std |
|---|---|---|
| equity_ratio | 0.0717 | 0.0048 |
| log_total_assets | 0.0498 | 0.0044 |
| section | 0.0059 | 0.0042 |
| working_capital_ratio | 0.0057 | 0.0022 |
| fixed_asset_ratio | 0.0041 | 0.0023 |
| short_term_debt_ratio | 0.0036 | 0.0016 |
| long_term_debt_ratio | 0.0030 | 0.0008 |
| current_ratio | 0.0028 | 0.0020 |
| company_age_years | 0.0023 | 0.0043 |
| cash_missing | 0.0000 | 0.0000 |
| micro_entity | -0.0001 | 0.0012 |
| cash_ratio | -0.0007 | 0.0024 |
