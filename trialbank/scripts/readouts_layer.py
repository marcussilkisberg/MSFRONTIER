"""Paper readouts: for completed randomised phase 2/3 trials whose registry entry has no primary result, read the
abstracts of the linked papers and record whether the trial met its main goal.

Gates (all must pass, otherwise the readout is stored as 'unclear' with the reason, and is not used for verdicts):
  1. the reader returns valid JSON naming one of the supplied papers as the main results paper;
  2. its supporting sentence appears word for word in that paper's abstract;
  3. a second, independent model, shown only the outcome, the abstract and the sentence, reaches the same answer.

Runs only when ANTHROPIC_API_KEY is set. Cached in ../raw/readouts_cache.json, keyed by trial and paper set, so each
trial is read once unless new papers are linked. Spend is capped by READOUT_MAX_TRIALS per run (default 150).
Writes ../data/trial_readouts.parquet.
Usage: python readouts_layer.py
"""
import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA, RAW = ROOT / "data", ROOT / "raw"
# The readouts cache is committed to the repository by the weekly workflow: it is paid for, and it is the audit
# trail of every machine-read result. Abstracts are re-fetchable and live in the Actions cache.
CACHE, ABSTRACTS = ROOT / "readouts" / "readouts_cache.json", RAW / "abstracts_cache.json"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
API = "https://api.anthropic.com/v1/messages"
READER = os.environ.get("READOUT_MODEL", "claude-sonnet-5-5")
CHECKER = os.environ.get("READOUT_CHECK_MODEL", "claude-haiku-5-5")
MAX_TRIALS = int(os.environ.get("READOUT_MAX_TRIALS", "150"))
PROMPT_VERSION = "readout_v1"
P23 = {"phase2", "phase3", "phase2|phase3"}
DECIDED = ("primary_p_lt_0.05", "primary_p_ge_0.05")
OUTCOMES = {"met", "not_met", "mixed", "unclear"}

READER_PROMPT = """You check what a clinical trial found. Below are a trial's registry details and the abstracts of \
papers linked to it.

Task: decide whether the trial MET ITS PRIMARY ENDPOINT, using only the abstracts.
- Use the paper that reports the main results of THIS trial (not a protocol, sub-study, extension, pooled \
analysis or review). If none does, answer "unclear".
- "met": the primary endpoint showed a statistically significant benefit of the experimental treatment.
- "not_met": the primary endpoint did not show a significant benefit (including non-significant trends).
- "mixed": the trial had several primary endpoints or co-primary comparisons with different results.
- "unclear": anything else.
- "quote": copy ONE sentence from that abstract, exactly as written, that states the primary result.

Reply with JSON only: {{"pmid": "...", "is_main_results_paper": true, "readout": "met|not_met|mixed|unclear", \
"quote": "..."}}

TRIAL
Title: {title}
Acronym: {acronym}
Registry IDs: {ids}
Phase: {phase}
Experimental: {drugs}
Comparator: {comparator}
Primary outcome (registry): {primary}

ABSTRACTS
{abstracts}"""

CHECK_PROMPT = """A trial's primary outcome was: {primary}

Abstract:
{abstract}

Sentence from the abstract: "{quote}"

Did the trial meet its primary endpoint (statistically significant benefit of the experimental treatment)? \
Answer with one word: met, not_met, mixed or unclear."""


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[‐-―−]", "-", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def call(model, prompt, max_tokens=400):
    key = os.environ["ANTHROPIC_API_KEY"]
    for k in range(5):
        r = requests.post(API, timeout=120, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                    "content-type": "application/json"},
                          json={"model": model, "max_tokens": max_tokens,
                                "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            return "".join(b.get("text", "") for b in r.json()["content"])
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (k + 1))
            continue
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:300]}")
    raise RuntimeError("Anthropic API: too many retries")


def fetch_abstracts(pmids, cache):
    todo = [p for p in pmids if p not in cache]
    for k in range(0, len(todo), 25):
        chunk = todo[k:k + 25]
        q = "(" + " OR ".join(f"EXT_ID:{p}" for p in chunk) + ") AND SRC:MED"
        try:
            r = requests.get(EPMC, params={"query": q, "format": "json", "resultType": "core", "pageSize": 100},
                             timeout=90)
            for h in r.json().get("resultList", {}).get("result", []):
                cache[str(h.get("pmid"))] = {"title": h.get("title"), "year": h.get("pubYear"),
                                             "abstract": h.get("abstractText") or "",
                                             "pub_types": (h.get("pubTypeList") or {}).get("pubType", [])}
            for p in chunk:
                cache.setdefault(p, {"title": None, "year": None, "abstract": "", "pub_types": []})
        except requests.RequestException:
            time.sleep(3)
    return cache


def candidates():
    t = pd.read_parquet(DATA / "trials.parquet")
    t = t[(t.study_type == "interventional") & t.phase.isin(P23)
          & t.allocation.fillna("").str.lower().str.startswith("random")
          & t.status.isin(["completed", "terminated", "unknown"])
          & ~t.result_signal.fillna("").isin(DECIDED)
          & ~t.result_signal.fillna("").str.contains("futility|safety")]
    t = t[t.drugs.fillna("") != ""]
    pri = (t.population_group == "progressive").astype(int) * 2 + t.phase.isin({"phase3", "phase2|phase3"}).astype(int)
    return t.assign(_p=pri).sort_values(["_p", "start_year"], ascending=[False, False])


def papers_for(uid, reg, epmc):
    rows = []
    for r in reg[reg.msf_trial_id == uid].itertuples():
        if str(r.ref_type).lower() in ("result", "resultsarticle", "derived"):
            rows.append((0 if str(r.ref_type).lower() != "derived" else 1, str(r.pmid)))
    for r in epmc[(epmc.msf_trial_id == uid)].itertuples():
        if r.pmid and str(r.pmid) != "None":
            rows.append((0 if r.is_trial_report_type else 2, str(r.pmid)))
    seen, out = set(), []
    for _, p in sorted(rows):
        if p not in seen and p.isdigit():
            seen.add(p)
            out.append(p)
    return out[:6]


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def read_trial(t, pmids, abstracts, outcomes, reader=call):
    usable = [(p, abstracts[p]) for p in pmids if len(abstracts.get(p, {}).get("abstract") or "") > 200][:4]
    base = {"msf_trial_id": t.msf_trial_id, "pmids_considered": [p for p, _ in usable]}
    if not usable:
        return {**base, "readout": "unclear", "reason": "no abstract available"}
    primary = "; ".join(outcomes.get(t.msf_trial_id, [])[:3]) or "not stated"
    block = "\n\n".join(f"[PMID {p}] {a['title']} ({a['year']})\n{clean(a['abstract'])}"
                        for p, a in usable)
    prompt = READER_PROMPT.format(title=t.title, acronym=t.acronym or "-", ids=t.registry_ids, phase=t.phase,
                                  drugs=t.drugs or "-", comparator=t.comparator_drugs or "placebo or none listed",
                                  primary=primary, abstracts=block)
    j = parse_json(reader(READER, prompt))
    if not j or j.get("readout") not in OUTCOMES:
        return {**base, "readout": "unclear", "reason": "invalid reader response"}
    pmid, quote = str(j.get("pmid") or ""), (j.get("quote") or "").strip()
    if j["readout"] == "unclear" or not j.get("is_main_results_paper"):
        return {**base, "readout": "unclear", "pmid": pmid or None, "reason": "no main results paper found"}
    if pmid not in dict(usable):
        return {**base, "readout": "unclear", "reason": "reader cited a paper that was not supplied"}
    if len(quote) < 20 or norm(quote) not in norm(abstracts[pmid]["abstract"]):
        return {**base, "readout": "unclear", "pmid": pmid, "reason": "quote not found word for word in abstract"}
    check = reader(CHECKER, CHECK_PROMPT.format(primary=primary, abstract=clean(abstracts[pmid]["abstract"]),
                                                quote=quote), 10).strip().lower().replace(" ", "_")
    check = next((o for o in ("not_met", "met", "mixed", "unclear") if check.startswith(o)), "unclear")
    if check != j["readout"]:
        return {**base, "readout": "unclear", "pmid": pmid, "quote": quote, "reader_said": j["readout"],
                "checker_said": check, "reason": "second model disagreed"}
    return {**base, "readout": j["readout"], "pmid": pmid, "quote": quote, "reader_said": j["readout"],
            "checker_said": check, "reason": None}


def main():
    CACHE.parent.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    abstracts = json.loads(ABSTRACTS.read_text()) if ABSTRACTS.exists() else {}
    reg = pd.read_parquet(DATA / "trial_publications.parquet")
    epmc = pd.read_parquet(DATA / "trial_publications_europepmc.parquet")
    out_rows = pd.read_parquet(DATA / "trial_outcomes.parquet")
    outcomes = out_rows[out_rows.outcome_kind == "primary"].groupby("msf_trial_id").measure.agg(list).to_dict()
    cand = candidates()
    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"readout candidates: {len(cand)}; API key {'set' if have_key else 'NOT set: reusing cached readouts only'}")

    plan = [(t, papers_for(t.msf_trial_id, reg, epmc)) for t in cand.itertuples()]
    plan = [(t, p) for t, p in plan if p]
    fetch_abstracts(sorted({x for _, p in plan for x in p}), abstracts)
    ABSTRACTS.write_text(json.dumps(abstracts))

    n_new = 0
    for t, pmids in plan:
        key = f"{t.msf_trial_id}|{PROMPT_VERSION}|" + hashlib.sha1(",".join(sorted(pmids)).encode()).hexdigest()[:10]
        if key in cache or not have_key or n_new >= MAX_TRIALS:
            continue
        try:
            cache[key] = {**read_trial(t, pmids, abstracts, outcomes), "reader_model": READER,
                          "checker_model": CHECKER, "prompt_version": PROMPT_VERSION, "read_on": date.today().isoformat()}
            n_new += 1
        except RuntimeError as e:
            print("stopping readouts:", e)
            break
        if n_new % 20 == 0:
            CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))

    # latest readout per trial (a newer paper set or prompt version supersedes older ones)
    latest = {}
    for k, v in cache.items():
        uid = k.split("|")[0]
        if uid not in latest or v.get("read_on", "") >= latest[uid].get("read_on", ""):
            latest[uid] = v
    df = pd.DataFrame(latest.values()) if latest else pd.DataFrame(columns=["msf_trial_id", "readout"])
    for c in ("pmid", "quote", "reader_said", "checker_said", "reason", "reader_model", "checker_model",
              "prompt_version", "read_on"):
        if c not in df.columns:
            df[c] = None
    df["pmids_considered"] = df.get("pmids_considered", pd.Series([[]] * len(df))).apply(
        lambda x: list(x) if isinstance(x, (list, tuple)) else [])
    df.to_parquet(DATA / "trial_readouts.parquet", index=False)
    print(f"readouts: {n_new} new this run, {len(df)} stored; "
          f"{df.readout.value_counts().to_dict() if len(df) else {}}")


if __name__ == "__main__":
    main()
