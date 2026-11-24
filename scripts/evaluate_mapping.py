"""Compare the hand-written rules with the LLM mapping.

Usage: python3 scripts/evaluate_mapping.py

1. On the 100 most common tag combinations (data/gold_labels.csv, labels checked by hand),
   how often does each method give the right standard item?
2. On the 1,033 rarer combinations that the rules leave out, what extra mappings does the
   LLM suggest? A random sample of 30 is written out for checking by hand.
"""

import csv
import json
import random

gold = {(r["tag"], r["dimensions"]): r for r in csv.DictReader(open("data/gold_labels.csv"))}
tags = {(r["tag"], r["dimensions"]): r for r in csv.DictReader(open("data/tag_list.csv"))}
llm = {(r["tag"], r["dimensions"]): r for r in csv.DictReader(open("results/llm_mapping.csv"))}
usage = json.load(open("results/llm_usage.json"))

scored = [k for k, g in gold.items() if g["gold_label"] != "ambiguous"]
lines = [f"# Rules vs LLM ({usage['provider']} {usage['model']})", ""]


def accuracy(method):
    right = [k for k in scored if method(k) == gold[k]["gold_label"]]
    facts_all = sum(int(gold[k]["facts"]) for k in scored)
    facts_right = sum(int(gold[k]["facts"]) for k in right)
    return len(right), 100 * facts_right / facts_all


r_n, r_w = accuracy(lambda k: tags[k]["rule_label"])
l_n, l_w = accuracy(lambda k: llm[k]["llm_label"])
lines += [f"Top 100 combinations ({len(scored)} scored, 2 left out as ambiguous):", "",
          "| Method | Correct | Weighted by number of figures |", "| --- | --- | --- |",
          f"| Rules | {r_n}/{len(scored)} | {r_w:.1f}% |",
          f"| LLM | {l_n}/{len(scored)} | {l_w:.1f}% |", ""]

wrong = [k for k in scored if llm[k]["llm_label"] != gold[k]["gold_label"]]
if wrong:
    lines += ["LLM mistakes on the top 100:", "", "| Tag | Dimensions | Correct | LLM said | Confidence |",
              "| --- | --- | --- | --- | --- |"]
    lines += [f"| {k[0]} | {k[1] or '(none)'} | {gold[k]['gold_label']} | {llm[k]['llm_label']} | {llm[k]['confidence']} |"
              for k in wrong]
    lines.append("")

amb = [k for k, g in gold.items() if g["gold_label"] == "ambiguous"]
lines += ["Ambiguous combinations (left to a person):", ""]
lines += [f"- {k[0]} {k[1] or '(none)'}: LLM said {llm[k]['llm_label']} (confidence {llm[k]['confidence']})" for k in amb]

tail = [k for k in tags if k not in gold and tags[k]["rule_label"] == "none" and llm[k]["llm_label"] != "none"]
lines += ["", f"Long tail: the LLM suggested a mapping for {len(tail)} of the {len(tags) - len(gold)} rarer combinations, "
          f"covering {sum(int(tags[k]['facts']) for k in tail):,} figures that the rules leave out.",
          "A random sample of 30 is in results/llm_tail_sample_for_review.csv. Fill in the 'correct' column by hand.",
          "", f"Tokens: {usage['input_tokens']:,} in, {usage['output_tokens']:,} out, {usage['seconds']} seconds."]

random.seed(42)
sample = random.sample(tail, min(30, len(tail)))
with open("results/llm_tail_sample_for_review.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["tag", "dimensions", "facts", "llm_label", "confidence", "correct"])
    for k in sample:
        w.writerow([k[0], k[1], tags[k]["facts"], llm[k]["llm_label"], llm[k]["confidence"], ""])

open("results/mapping_comparison.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
