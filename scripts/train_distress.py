"""Predict which UK small companies will slip into negative net assets next year.

Input : data/distress_dataset.csv (built by sql/07_features.sql)
Output: results/distress_metrics.md, results/distress_importance.csv,
        results/distress_pr_curve.png

Features come only from last year's balance sheet, so the model never sees the answer.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

SEED = 42
NUMERIC = ["company_age_years", "log_total_assets", "equity_ratio", "current_ratio",
           "cash_ratio", "long_term_debt_ratio", "fixed_asset_ratio", "short_term_debt_ratio",
           "working_capital_ratio", "micro_entity", "cash_missing"]
CATEGORICAL = ["section"]
FEATURES = NUMERIC + CATEGORICAL


def clip_ratios(X):
    # ratios can be extreme for tiny balance sheets; clip so the linear model is not dominated
    return np.clip(X, -10, 10)


def logistic_model():
    num = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                    ("clip", FunctionTransformer(clip_ratios)),
                    ("scale", StandardScaler())])
    cat = OneHotEncoder(handle_unknown="ignore", min_frequency=50)
    pre = ColumnTransformer([("num", num, NUMERIC), ("cat", cat, CATEGORICAL)])
    return Pipeline([("pre", pre),
                     ("clf", LogisticRegression(max_iter=2000, class_weight="balanced"))])


def boosting_model():
    pre = ColumnTransformer([("num", "passthrough", NUMERIC),
                             ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50,
                                                   sparse_output=False), CATEGORICAL)])
    clf = HistGradientBoostingClassifier(learning_rate=0.05, max_iter=400, max_leaf_nodes=31,
                                         min_samples_leaf=40, l2_regularization=1.0,
                                         early_stopping=True, validation_fraction=0.15,
                                         random_state=SEED)
    return Pipeline([("pre", pre), ("clf", clf)])


def top_k_stats(y, score, frac=0.10):
    k = int(round(len(y) * frac))
    idx = np.argsort(-score, kind="stable")[:k]
    caught = y[idx].sum()
    return {"top_share": frac, "flagged": k, "caught": int(caught),
            "capture_rate": caught / y.sum(), "precision": caught / k,
            "lift": (caught / k) / y.mean()}


def bootstrap_ci(y, score, n=1000, seed=SEED):
    """95% interval for test PR-AUC and top-10% capture, resampling test companies."""
    rng = np.random.default_rng(seed)
    ap, cap = [], []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() == 0:
            continue
        ap.append(average_precision_score(y[i], score[i]))
        cap.append(top_k_stats(y[i], score[i])["capture_rate"])
    return np.percentile(ap, [2.5, 97.5]), np.percentile(cap, [2.5, 97.5])


def evaluate(name, y, score):
    out = {"model": name, "pr_auc": average_precision_score(y, score),
           "roc_auc": roc_auc_score(y, score)}
    out.update({f"top10_{k}": v for k, v in top_k_stats(y, score).items() if k != "top_share"})
    return out


def main(data_path="data/distress_dataset.csv", out_dir="results"):
    out = Path(out_dir)
    df = pd.read_csv(data_path)
    df = df[df.in_population == 1].reset_index(drop=True)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    print(f"{len(df):,} companies, {df.label.sum():,} turned negative ({df.label.mean():.2%})")

    train, test = train_test_split(df, test_size=0.25, stratify=df.label, random_state=SEED)
    X_tr, y_tr = train[FEATURES], train.label.to_numpy()
    X_te, y_te = test[FEATURES], test.label.to_numpy()

    rows, cv_rows = [], []
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)

    # Baseline 1: rank by last year's equity ratio alone (thinner equity = riskier)
    rule_score = -X_te.equity_ratio.fillna(1).to_numpy()
    rows.append(evaluate("Rule: lowest equity ratio", y_te, rule_score))

    models = {"Logistic regression": logistic_model(), "Gradient boosting": boosting_model()}
    fitted, test_scores = {}, {}
    for name, model in models.items():
        cv_score = cross_val_predict(model, X_tr, y_tr, cv=cv, method="predict_proba")[:, 1]
        cv_rows.append(evaluate(name, y_tr, cv_score))
        model.fit(X_tr, y_tr)
        fitted[name] = model
        test_scores[name] = model.predict_proba(X_te)[:, 1]
        rows.append(evaluate(name, y_te, test_scores[name]))

    # What skipping the sign fix costs: train on the uncorrected equity ratio and labels,
    # then judge against the corrected labels on the same test companies.
    noisy = boosting_model()
    X_tr_noisy = X_tr.copy()
    X_tr_noisy["equity_ratio"] = train.equity_ratio_as_tagged.to_numpy()
    noisy.fit(X_tr_noisy, train.label_as_tagged.to_numpy())
    X_te_noisy = X_te.copy()
    X_te_noisy["equity_ratio"] = test.equity_ratio_as_tagged.to_numpy()
    rows.append(evaluate("Gradient boosting, no sign fix", y_te,
                         noisy.predict_proba(X_te_noisy)[:, 1]))
    ci = {"Rule: lowest equity ratio": bootstrap_ci(y_te, rule_score)}
    ci.update({k: bootstrap_ci(y_te, v) for k, v in test_scores.items()})
    label_flips = int((train.label != train.label_as_tagged).sum())

    # Which inputs matter: drop in PR-AUC when a column is shuffled (test set)
    imp = permutation_importance(fitted["Gradient boosting"], X_te, y_te,
                                 scoring="average_precision", n_repeats=10,
                                 random_state=SEED, n_jobs=-1)
    importance = (pd.DataFrame({"feature": FEATURES, "pr_auc_drop": imp.importances_mean,
                                "std": imp.importances_std})
                  .sort_values("pr_auc_drop", ascending=False))
    importance.to_csv(out / "distress_importance.csv", index=False)

    test_df = pd.DataFrame(rows)
    cv_df = pd.DataFrame(cv_rows)
    fmt = {"pr_auc": "{:.3f}", "roc_auc": "{:.3f}", "top10_capture_rate": "{:.1%}",
           "top10_precision": "{:.1%}", "top10_lift": "{:.2f}x"}

    def table(d):
        d = d.copy()
        for c, f in fmt.items():
            d[c] = d[c].map(f.format)
        cols = ["model", "pr_auc", "roc_auc", "top10_caught", "top10_capture_rate",
                "top10_precision", "top10_lift"]
        head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
        return head + "".join("| " + " | ".join(str(r[c]) for c in cols) + " |\n"
                              for _, r in d[cols].iterrows())

    md = [
        "# Distress prediction results\n",
        f"Companies: {len(df):,} with positive net assets last year "
        f"(accounts registered 14 to 23 Nov 2026). "
        f"Turned negative this year: {df.label.sum():,} ({df.label.mean():.2%}).\n",
        f"Split: 75% train ({len(train):,}), 25% test ({len(test):,}), stratified, seed {SEED}.\n",
        f"Base rate in test set: {y_te.mean():.2%}, so a random ranking has PR-AUC about "
        f"{y_te.mean():.3f} and catches 10% of cases in the top 10%.\n",
        "\n## Test set\n", table(test_df),
        "\n95% bootstrap intervals on the test set (1,000 resamples):\n\n",
        "".join(f"- {k}: PR-AUC {a[0]:.3f} to {a[1]:.3f}, top 10% capture {c[0]:.1%} to {c[1]:.1%}\n"
                for k, (a, c) in ci.items()),
        "\n## 5-fold cross-validation on the training set\n", table(cv_df),
        f"\nTraining labels changed by the sign fix: {label_flips:,} of {len(train):,}.\n",
        "\n## Permutation importance (gradient boosting, drop in test PR-AUC)\n",
        "| feature | drop | std |\n|---|---|---|\n",
        "".join(f"| {r.feature} | {r.pr_auc_drop:.4f} | {r.std:.4f} |\n"
                for r in importance.itertuples()),
    ]
    (out / "distress_metrics.md").write_text("".join(md))
    (out / "distress_metrics.json").write_text(json.dumps(
        {"test": rows, "cv": cv_rows, "n": len(df), "positives": int(df.label.sum())},
        indent=2, default=float))

    # Precision-recall chart for the test set
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.4), dpi=150)
    styles = {"Gradient boosting": ("#2a6fdb", "-"), "Logistic regression": ("#e07b39", "-")}
    for name, (color, ls) in styles.items():
        p, r, _ = precision_recall_curve(y_te, test_scores[name])
        ap = average_precision_score(y_te, test_scores[name])
        ax.plot(r, p, color=color, lw=2, ls=ls, label=f"{name} (PR-AUC {ap:.3f})")
    ax.axhline(y_te.mean(), color="#888888", lw=1.2, ls="--",
               label=f"Random ({y_te.mean():.3f})")
    ax.set_xlabel("Recall (share of distressed companies caught)")
    ax.set_ylabel("Precision")
    ax.set_title("Predicting negative net assets one year ahead", loc="left", fontsize=11)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(color="#e5e5e5", lw=0.8)
    ax.legend(frameon=False, fontsize=8.5)
    fig.text(0.01, 0.01, "Test set, Companies House accounts registered 14 to 23 Nov 2026",
             fontsize=7, color="#666666")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "distress_pr_curve.png")
    print((out / "distress_metrics.md").read_text())


if __name__ == "__main__":
    main(*sys.argv[1:])
