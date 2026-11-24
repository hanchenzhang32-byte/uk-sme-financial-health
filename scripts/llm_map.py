"""Ask a large language model to map every balance sheet tag to a standard item.

Usage (from the project folder):
    python3 scripts/llm_map.py

Needs an API key in a file called .env in the project folder, one of:
    ANTHROPIC_API_KEY=...
    OPENAI_API_KEY=...
Optional: LLM_MODEL=... to choose a different model.

Reads  data/tag_list.csv   (1,133 tag and dimension combinations with how often they appear)
Writes results/llm_mapping.csv and results/llm_usage.json

Only tag names and dimension names are sent, never company data.
Uses only the Python standard library, so nothing needs to be installed.
"""

import csv
import json
import os
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ITEMS = {
    "cash": "Cash at bank and in hand (total)",
    "debtors": "Debtors: total amounts owed to the company, due within one year",
    "current_assets": "Current assets (total)",
    "fixed_assets": "Fixed assets (total of tangible, intangible and investments)",
    "creditors_within_1y": "Creditors: amounts falling due within one year (total)",
    "creditors_after_1y": "Creditors: amounts falling due after more than one year (total)",
    "net_current_assets": "Net current assets or liabilities (total)",
    "total_assets_less_cl": "Total assets less current liabilities (total)",
    "net_assets": "Net assets or liabilities, which equals total equity",
    "prepayments_outside_ca": "Prepayments and accrued income shown as a separate line outside current assets",
    "accruals_outside_cl": "Accruals and deferred income shown as a separate line outside creditors",
    "provisions": "Provisions for liabilities (total)",
}
BATCH = 60


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_prompt(rows):
    items = "\n".join(f"- {code}: {desc}" for code, desc in ITEMS.items())
    lines = "\n".join(f'{i}. tag="{r["tag"]}" dimensions="{r["dimensions"] or "(none)"}"'
                      for i, r in enumerate(rows))
    return f"""You are mapping UK company accounts (iXBRL, FRS 102 / FRS 105 taxonomy) to standard balance sheet items.

Standard items:
{items}

Rules:
- Map a tag only if it reports the TOTAL of that item. Parts of a total (for example trade creditors, share capital, plant and machinery) are "none".
- Dimensions matter: a dimension that splits a total into classes or directors makes it a part, so "none".
- If you are unsure, still answer, but give a low confidence.

For each numbered line below, return JSON only, in this exact form:
{{"results": [{{"id": 0, "item_code": "<one of the codes above or none>", "confidence": 0.0}}]}}

Lines:
{lines}"""


def post_json(url, headers, body):
    """POST a JSON body and return the JSON reply.

    Some Python installs on macOS have no root certificates, so HTTPS fails with
    CERTIFICATE_VERIFY_FAILED. In that case fall back to the system curl, which uses
    the macOS certificate store. The key is passed to curl on stdin, not on the command line.
    """
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
        return json.load(urllib.request.urlopen(req, timeout=180))
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, ssl.SSLError) as e:
        if "CERTIFICATE" not in str(e).upper():
            raise
    config = "".join(f'header = "{k}: {v}"\n' for k, v in headers.items())
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(json.dumps(body))
        body_path = f.name
    try:
        out = subprocess.run(["curl", "-sS", "--max-time", "180", "-K", "-", "--data-binary", f"@{body_path}", url],
                             input=config, capture_output=True, text=True)
    finally:
        os.remove(body_path)
    if out.returncode != 0:
        raise urllib.error.URLError(out.stderr.strip())
    data = json.loads(out.stdout)
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(f"API error: {data['error']}")
    return data


def call_anthropic(prompt, key, model):
    body = {"model": model, "max_tokens": 8000,
            "messages": [{"role": "user", "content": prompt}]}
    data = post_json("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, body)
    text = "".join(block.get("text", "") for block in data["content"])
    usage = data.get("usage", {})
    return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def call_openai(prompt, key, model):
    body = {"model": model, "max_completion_tokens": 16000,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}]}
    data = post_json("https://api.openai.com/v1/chat/completions",
                     {"Authorization": f"Bearer {key}", "content-type": "application/json"}, body)
    usage = data.get("usage", {})
    return data["choices"][0]["message"]["content"], usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def parse(text, n):
    start, end = text.find("{"), text.rfind("}")
    results = json.loads(text[start:end + 1])["results"]
    out = {}
    for r in results:
        code = r.get("item_code", "none")
        out[int(r["id"])] = (code if code in ITEMS else "none", float(r.get("confidence", 0)))
    missing = [i for i in range(n) if i not in out]
    if missing:
        raise ValueError(f"model skipped lines {missing[:5]}")
    return out


def main():
    load_env()
    if os.environ.get("ANTHROPIC_API_KEY"):
        provider, key, call = "anthropic", os.environ["ANTHROPIC_API_KEY"], call_anthropic
        model = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
    elif os.environ.get("OPENAI_API_KEY"):
        provider, key, call = "openai", os.environ["OPENAI_API_KEY"], call_openai
        model = os.environ.get("LLM_MODEL", "gpt-5.6-luna")
    else:
        raise SystemExit("No ANTHROPIC_API_KEY or OPENAI_API_KEY found in .env")

    rows = list(csv.DictReader(open("data/tag_list.csv")))
    print(f"{provider} / {model}: mapping {len(rows)} tag combinations in batches of {BATCH}")
    labels, tokens_in, tokens_out, started = [], 0, 0, time.time()
    for b in range(0, len(rows), BATCH):
        chunk = rows[b:b + BATCH]
        for attempt in range(3):
            try:
                text, t_in, t_out = call(build_prompt(chunk), key, model)
                result = parse(text, len(chunk))
                break
            except (ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError) as e:
                detail = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else str(e)
                print(f"  batch {b // BATCH + 1} attempt {attempt + 1} failed: {detail}")
                time.sleep(3)
        else:
            raise SystemExit("Giving up after 3 failed attempts.")
        tokens_in, tokens_out = tokens_in + t_in, tokens_out + t_out
        labels += [result[i] for i in range(len(chunk))]
        print(f"  batch {b // BATCH + 1}/{(len(rows) + BATCH - 1) // BATCH} done")

    os.makedirs("results", exist_ok=True)
    with open("results/llm_mapping.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tag", "dimensions", "facts", "llm_label", "confidence"])
        for r, (code, conf) in zip(rows, labels):
            w.writerow([r["tag"], r["dimensions"], r["facts"], code, conf])
    usage = {"provider": provider, "model": model, "input_tokens": tokens_in, "output_tokens": tokens_out,
             "seconds": round(time.time() - started, 1), "run_at": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(usage, open("results/llm_usage.json", "w"), indent=2)
    print(json.dumps(usage, indent=2))
    print("Saved results/llm_mapping.csv. Check the exact cost on your provider's billing page.")


if __name__ == "__main__":
    main()
