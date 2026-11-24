# Rules vs LLM (anthropic claude-haiku-5-5)

Top 100 combinations (98 scored, 2 left out as ambiguous):

| Method | Correct | Weighted by number of figures |
| --- | --- | --- |
| Rules | 98/98 | 100.0% |
| LLM | 92/98 | 93.2% |

LLM mistakes on the top 100:

| Tag | Dimensions | Correct | LLM said | Confidence |
| --- | --- | --- | --- | --- |
| Creditors | FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments | creditors_within_1y | none | 0.4 |
| Creditors | FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments;MaturitiesOrExpirationPeriodsDimension=WithinOneYear | creditors_within_1y | none | 0.4 |
| Creditors | FinancialInstrumentCurrentNon-currentDimension=Non-currentFinancialInstruments | creditors_after_1y | none | 0.5 |
| Debtors | FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments;MaturitiesOrExpirationPeriodsDimension=WithinOneYear | debtors | none | 0.4 |
| Debtors | FinancialInstrumentCurrentNon-currentDimension=CurrentFinancialInstruments | debtors | none | 0.9 |
| Creditors | FinancialInstrumentCurrentNon-currentDimension=Non-currentFinancialInstruments;MaturitiesOrExpirationPeriodsDimension=AfterOneYear | creditors_after_1y | none | 0.8 |

Ambiguous combinations (left to a person):

- Creditors (none): LLM said creditors_within_1y (confidence 0.5)
- AccruedLiabilitiesDeferredIncome (none): LLM said none (confidence 0.4)

Long tail: the LLM suggested a mapping for 20 of the 1033 rarer combinations, covering 532 figures that the rules leave out.
All 20 suggestions are in results/llm_tail_sample_for_review.csv. Checked by hand: 5 correct, 15 wrong (10 of them consolidated group figures).

Tokens: 83,174 in, 49,971 out, 179.5 seconds.
