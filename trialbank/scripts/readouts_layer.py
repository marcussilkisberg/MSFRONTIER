"""Paper readouts: for finished randomised trials whose registry entry has no primary result, read the abstracts of
the linked papers and record whether the trial met its main goal.

Scope (READOUT_SCOPE):
  all       every finished randomised trial past phase 1: medicines in any later phase, and trials of treatments that
            are not medicines (exercise, rehabilitation, devices, therapy), which have no phase. Default since
            November 2026. Medicine trials in phase 2 and 3 are still read first.
  p23_drug  the scope before November 2026: phase 2 and 3 trials of a medicine only.

Papers: each trial has a first list (registry result papers, papers the results watch matched, and papers Europe PMC
types as a trial report) and a second list (the other papers linked to the trial). The second list is read only when
the first has no main results paper, or is empty.

Gates (all must pass, otherwise the readout is stored as 'unclear' with the reason, and is not used for verdicts):
  1. the reader returns valid JSON naming one of the supplied papers as the main results paper;
  2. its supporting sentence appears word for word in that paper's abstract;
  3. a second, independent model, shown only the outcome, the abstract and the sentence, reaches the same answer.

Runs only when ANTHROPIC_API_KEY is set. Cached in ../readouts/readouts_cache.json, keyed by trial, prompt version and
paper list, so each list is read once unless new papers are linked. Spend is capped by READOUT_MAX_TRIALS readings
per run (default 400). A reading is one call to the reader and, when it names a paper, one call to the checker.
Writes ../data/trial_readouts.parquet.
Usage: python readouts_layer.py
"""
import hashlib
import html as htmllib
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
MAX_TRIALS = int(os.environ.get("READOUT_MAX_TRIALS", "400"))
# v2: abstracts keep "p < 0.001" (v1 stripped it as if it were HTML); equivalence and non-efficacy trials separated
PROMPT_VERSION = "readout_v2"
# v2n: the same prompt for a trial with no medicine the bank recognises (exercise, devices, therapy, or a medicine
# not matched to ChEMBL). Only the list of possible controls differs (adds sham, usual care, a waiting list). Trials
# of a recognised medicine keep readout_v2 and its exact text, so nothing already read is read again.
PROMPT_VERSION_NONDRUG = "readout_v2n"
VERSIONS = {PROMPT_VERSION, PROMPT_VERSION_NONDRUG}
SCOPE = os.environ.get("READOUT_SCOPE", "all")
SKIP_PHASES = {"phase1", "early_phase1"}
CONTROLS = {PROMPT_VERSION: "placebo, no treatment or another drug",
            PROMPT_VERSION_NONDRUG: "placebo, sham, usual care, a waiting list, no treatment or another treatment"}
NO_MAIN_PAPER = ("no main results paper found", "no abstract available")
# v2b: v2's checker had a 60-token reply limit, so explanations were cut off and read as "unclear" (94 of 117
# readings rejected, ORATORIO among them). Readings rejected by an older checker are read again.
CHECKER_VERSION = "check_v2b"
P23 = {"phase2", "phase3", "phase2|phase3"}
DECIDED = ("primary_p_lt_0.05", "primary_p_ge_0.05")
OUTCOMES = {"met", "not_met", "mixed", "equivalent", "not_efficacy", "unclear"}

READER_PROMPT = """You check what a clinical trial found. Below are a trial's registry details and the abstracts of \
papers linked to it.

Task: decide what the trial found for its PRIMARY ENDPOINT, using only the abstracts.
- Use the paper that reports the main results of THIS trial (not a protocol, sub-study, extension, pooled \
analysis or review). If none does, answer "unclear".
- "met": the primary endpoint showed a statistically significant BENEFIT of the experimental treatment over the \
control ({controls}).
- "not_met": the primary endpoint did not show a significant benefit (including non-significant trends), or the \
experimental treatment did worse.
- "mixed": several primary endpoints or co-primary comparisons with different results.
- "equivalent": the trial was designed to show non-inferiority, equivalence or biosimilarity (e.g. generic vs \
brand, subcutaneous vs intravenous, new drug "as good as" an old one) and showed it.
- "not_efficacy": the primary endpoint was not about treatment benefit: safety, tolerability, adherence, \
pharmacokinetics, drug levels, B-cell or other cell counts, vaccine response, or feasibility.
- "unclear": anything else.
- "quote": copy ONE sentence from that abstract, exactly as written, that states the primary result.
- "result": the primary result's numbers, copied exactly as they appear in the abstract (keep the original text of
  each number, e.g. "0.76", "32.9%", "-0.21"). Leave out anything the abstract does not state. Fields:
  "measure" (the primary measure, in the abstract's words), "n_randomised" (total participants),
  "groups" (list of {{"group": name, "n": number, "value": the result for that group}}),
  "effect" ({{"type": e.g. "hazard ratio", "rate ratio", "mean difference", "odds ratio", "value": ...,
  "ci_lower": ..., "ci_upper": ...}}), "p": the p-value text, "follow_up": the time point.

Reply with JSON only: {{"pmid": "...", "is_main_results_paper": true, \
"readout": "met|not_met|mixed|equivalent|not_efficacy|unclear", "quote": "...", "result": {{...}}}}

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

CHECK_PROMPT = """You check one sentence about a clinical trial.

Trial: {title}
Experimental: {drugs}. Comparator: {comparator}.
Primary outcome (registry): {primary}

Abstract:
{abstract}

Sentence from the abstract: "{quote}"

What did the trial find for its primary endpoint? Choose one:
- met: statistically significant benefit of the experimental treatment over the control
- not_met: no significant benefit, or worse
- mixed: several primary endpoints with different results
- equivalent: designed to show non-inferiority or equivalence, and showed it
- not_efficacy: the primary endpoint was safety, pharmacokinetics, cell counts, vaccine response or feasibility
- unclear: the abstract does not say

Reply with exactly one line of JSON and nothing else, for example {{"readout": "met"}}"""


TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")   # real HTML tags only: keeps "p < 0.001" and "p<0.05"


def clean(text):
    return re.sub(r"\s+", " ", htmllib.unescape(TAG.sub(" ", text or ""))).strip()


def norm(s):
    s = unicodedata.normalize("NFKC", clean(s)).lower()
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def call(model, prompt, max_tokens=900):
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


def is_drug_trial(t):
    return bool(str(getattr(t, "drugs", "") or "").strip())


def version_for(t):
    return PROMPT_VERSION if is_drug_trial(t) else PROMPT_VERSION_NONDRUG


def experimental(t):
    """What the trial tested, for the prompts: its medicines, or for other treatments the registry's own wording."""
    if is_drug_trial(t):
        return t.drugs
    raw = str(getattr(t, "interventions_raw", "") or "").replace("|", "; ").strip()
    return raw[:300] or "-"


def candidates(scope=None):
    """Finished randomised trials with no primary result the registry lets software judge. Phase 2 and 3 trials of a
    medicine come first, in the order they always had, then the rest with the largest trials first."""
    scope = scope or SCOPE
    t = pd.read_parquet(DATA / "trials.parquet")
    t = t[(t.study_type == "interventional")
          & t.allocation.fillna("").str.lower().str.startswith("random")
          & t.status.isin(["completed", "terminated", "unknown"])
          & ~t.result_signal.fillna("").isin(DECIDED)
          & ~t.result_signal.fillna("").str.contains("futility|safety")]
    core = t.phase.isin(P23) & (t.drugs.fillna("") != "")
    t = t[core] if scope == "p23_drug" else t[core | ~t.phase.isin(SKIP_PHASES)]
    core = core.reindex(t.index)
    pri = (t.population_group == "progressive").astype(int) * 2 + t.phase.isin({"phase3", "phase2|phase3"}).astype(int)
    size = pd.to_numeric(t.enrollment, errors="coerce").fillna(0)
    key = t.start_year.where(core, size)
    return t.assign(is_core=core.astype(int), _p=pri, _k=key).sort_values(["is_core", "_p", "_k"],
                                                                          ascending=[False, False, False])


def search_matches():
    """Results papers the results watch found by search for trials whose registry entry does not link them (MAESTRO-01:
    MBP8298 phase 3, Neurology 2011). Read from last run's committed cache, keyed by trial."""
    p = ROOT / "readouts" / "results_watch_cache.json"
    out = {}
    if p.exists():
        # newest matching rules first (rw_v3 accepts only papers that report the main result)
        for k, v in sorted(json.loads(p.read_text()).items(), key=lambda kv: kv[0].split("|")[-1], reverse=True):
            m = (v or {}).get("match") or {}
            if m.get("pmid"):
                out.setdefault(k.split("|")[0], m["pmid"])
    return out


def papers_for(uid, reg, epmc, found=None):
    """Candidate papers, the likeliest main results paper first. Protocols and reviews are left out: MS-STAT2's
    Lancet results paper used to sit sixth behind its protocol and secondary analyses and was never read."""
    meta = {str(r.pmid): (str(r.pub_type or "").lower(), str(r.title or "").lower(), r.pub_year)
            for r in epmc[epmc.msf_trial_id == uid].itertuples() if r.pmid and str(r.pmid) != "None"}
    rank = {}

    def add(pmid, rk):
        pmid = str(pmid)
        if not pmid.isdigit():
            return
        pt, title, _ = meta.get(pmid, ("", "", None))
        if "review" in pt or "protocol" in pt or re.search(r"\bprotocol\b|study design|rationale and design", title):
            return
        rank[pmid] = min(rank.get(pmid, 9), rk)

    if found and found.get(uid):
        add(found[uid], 0)
    for r in reg[reg.msf_trial_id == uid].itertuples():
        rt = str(r.ref_type).lower()
        if rt in ("result", "resultsarticle"):
            add(r.pmid, 0)
        elif rt == "derived":
            add(r.pmid, 3)
    for pmid, (pt, title, _) in meta.items():
        if "clinical trial, phase" in pt or "randomized controlled trial" in pt:
            add(pmid, 1)
    # oldest first within a rank: the main results paper comes before later secondary analyses (ORATORIO 2017)
    order = sorted(rank, key=lambda p: (rank[p], int(meta.get(p, ("", "", 0))[2] or 9999), p))
    return order[:6]


NOT_A_REPORT = re.compile(r"review|protocol|case report|comment|editorial|letter|erratum|retract|news|guideline")


def more_papers(uid, epmc, first, acronym=None):
    """The second list: papers linked to the trial that the first list left out. Many main results papers are typed
    only "Journal Article" in Europe PMC, so they never reached the reader (98 phase 2 and 3 medicine trials had
    linked papers and an empty first list). Papers that name the trial's acronym in the title come first, then the
    oldest."""
    acr = str(acronym or "").strip().lower()
    acr = acr if len(acr) >= 4 else ""
    rows = []
    for r in epmc[epmc.msf_trial_id == uid].itertuples():
        pmid = str(r.pmid)
        if not pmid.isdigit() or pmid in first:
            continue
        pt, title = str(r.pub_type or "").lower(), str(r.title or "").lower()
        if NOT_A_REPORT.search(pt) or re.search(r"\bprotocol\b|study design|rationale and design|\bcase report\b", title):
            continue
        try:
            year = int(r.pub_year)
        except (TypeError, ValueError):
            year = 9999
        rows.append((0 if acr and acr in title else 1, year, pmid))
    out = []
    for _, _, pmid in sorted(rows):
        if pmid not in out:
            out.append(pmid)
    return out[:6]


def checker_answer(text):
    """The checker's verdict from its reply, tolerating explanation text around the JSON."""
    text = text or ""
    m = re.findall(r'"readout"\s*:\s*"([a-z_]+)"', text)
    if m and m[-1] in OUTCOMES:
        return m[-1]
    return "unclear"   # no JSON verdict: never guess from free text ("did not meet" contains "met")


def parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def read_trial(t, pmids, abstracts, outcomes, reader=call):
    usable = [(p, abstracts[p]) for p in pmids if len(abstracts.get(p, {}).get("abstract") or "") > 200][:5]
    base = {"msf_trial_id": t.msf_trial_id, "pmids_considered": [p for p, _ in usable]}
    if not usable:
        return {**base, "readout": "unclear", "reason": "no abstract available"}
    primary = "; ".join(outcomes.get(t.msf_trial_id, [])[:3]) or "not stated"
    block = "\n\n".join(f"[PMID {p}] {a['title']} ({a['year']})\n{clean(a['abstract'])}"
                        for p, a in usable)
    version = version_for(t)
    exp = experimental(t)
    comparator = t.comparator_drugs or ("placebo or none listed" if version == PROMPT_VERSION
                                        else "placebo, sham, usual care or none listed")
    prompt = READER_PROMPT.format(title=t.title, acronym=t.acronym or "-", ids=t.registry_ids, phase=t.phase,
                                  drugs=exp or "-", comparator=comparator, controls=CONTROLS[version],
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
    cj = (reader(CHECKER, CHECK_PROMPT.format(
        title=t.title, drugs=exp or "-", comparator=comparator,
        primary=primary, abstract=clean(abstracts[pmid]["abstract"]), quote=quote), 600))
    check = checker_answer(cj)
    if check != j["readout"]:
        return {**base, "readout": "unclear", "pmid": pmid, "quote": quote, "reader_said": j["readout"],
                "checker_said": check, "reason": "second model disagreed",
                "reader_result": verified_numbers(j.get("result"), abstracts[pmid]["abstract"])}
    return {**base, "readout": j["readout"], "pmid": pmid, "quote": quote, "reader_said": j["readout"],
            "checker_said": check, "reason": None,
            "result": verified_numbers(j.get("result"), abstracts[pmid]["abstract"])}


NUM = re.compile(r"[-−–]?\d+(?:[.,·]\d+)?%?")


def verified_numbers(result, abstract):
    """Keep only numbers that appear word for word in the abstract; drop anything else. Text fields (measure, group
    names, effect type) are kept only if they also appear in the abstract."""
    if not isinstance(result, dict):
        return None
    text = norm(abstract)
    nums_in_abstract = {n.replace("−", "-").replace("–", "-").replace("·", ".") for n in NUM.findall(clean(abstract))}
    # "0·40–0·66" is a range, not a negative number: accept the unsigned form too
    nums_in_abstract |= {n.lstrip("-") for n in nums_in_abstract}

    def num_ok(v):
        if v is None:
            return None
        v = str(v).strip().replace("−", "-").replace("–", "-").replace("·", ".")
        found = NUM.findall(v)
        return v if found and all(f in nums_in_abstract for f in found) else None

    def text_ok(v, limit=160):
        v = (str(v).strip() if v is not None else "")
        return v[:limit] if v and norm(v) in text else None

    out = {"measure": text_ok(result.get("measure"), 300), "n_randomised": num_ok(result.get("n_randomised")),
           "p": num_ok(result.get("p")), "follow_up": text_ok(result.get("follow_up"))}
    groups = []
    for g in result.get("groups") or []:
        if isinstance(g, dict):
            row = {"group": text_ok(g.get("group")), "n": num_ok(g.get("n")), "value": num_ok(g.get("value"))}
            if row["group"] and row["value"]:
                groups.append(row)
    out["groups"] = groups or None
    e = result.get("effect") if isinstance(result.get("effect"), dict) else {}
    eff = {"type": text_ok(e.get("type"), 60) or (str(e.get("type"))[:60] if e.get("type") else None),
           "value": num_ok(e.get("value")), "ci_lower": num_ok(e.get("ci_lower")), "ci_upper": num_ok(e.get("ci_upper"))}
    out["effect"] = eff if eff["value"] else None
    out = {k: v for k, v in out.items() if v}
    return out or None


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

    found = search_matches()
    plan = []
    for t in cand.itertuples():
        first = papers_for(t.msf_trial_id, reg, epmc, found)
        more = more_papers(t.msf_trial_id, epmc, first, t.acronym)
        if first or more:
            plan.append((t, first, more))
    fetch_abstracts(sorted({x for _, first, more in plan for x in first + more}), abstracts)
    ABSTRACTS.write_text(json.dumps(abstracts))
    n_core = sum(1 for t, _, _ in plan if t.is_core)
    print(f"scope '{SCOPE}': {len(plan)} candidates have a linked paper "
          f"({n_core} phase 2 or 3 medicine trials, {len(plan) - n_core} others)")

    def key_for(t, pmids):
        return f"{t.msf_trial_id}|{version_for(t)}|" + hashlib.sha1(",".join(sorted(pmids)).encode()).hexdigest()[:10]

    def read(t, pmids, which):
        cache[key_for(t, pmids)] = {**read_trial(t, pmids, abstracts, outcomes), "reader_model": READER,
                                    "checker_model": CHECKER, "checker_version": CHECKER_VERSION,
                                    "prompt_version": version_for(t), "paper_list": which,
                                    "read_on": date.today().isoformat()}

    n_new = n_left = 0
    for t, first, more in plan:
        prefix, linked = f"{t.msf_trial_id}|{version_for(t)}|", set(first) | set(more)
        # an accepted reading whose paper is still among this trial's papers stays valid when the lists change;
        # no need to pay for it again
        if any(k.startswith(prefix) and not v.get("reason") and v.get("pmid") in linked for k, v in cache.items()):
            continue
        todo = []
        k1 = key_for(t, first) if first else None
        if first and (k1 not in cache or (cache[k1].get("reason") == "second model disagreed"
                                          and cache[k1].get("checker_version") != CHECKER_VERSION)):
            todo.append((first, "first"))
        # the second list is read when the first one is empty or held no main results paper
        if more and key_for(t, more) not in cache:
            todo.append((more, "second"))
        stop = False
        for pmids, which in todo:
            if which == "second" and first and cache.get(k1, {}).get("reason") not in NO_MAIN_PAPER:
                continue      # the first list gave an answer, or has not been read yet
            if not have_key or n_new >= MAX_TRIALS:
                n_left += 1
                continue
            try:
                read(t, pmids, which)
                n_new += 1
            except RuntimeError as e:
                print("stopping readouts:", e)
                stop = True
                break
            if n_new % 20 == 0:
                CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
        if stop:
            break
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    if n_left:
        print(f"{n_left} readings left for a later run (READOUT_MAX_TRIALS={MAX_TRIALS}"
              f"{'' if have_key else ', no API key'})")

    # latest readout per trial (a newer paper set or prompt version supersedes older ones)
    latest = {}
    rank = lambda v: (v.get("prompt_version") in VERSIONS, not v.get("reason"), v.get("read_on", ""))
    for k, v in cache.items():
        uid = k.split("|")[0]
        if uid not in latest or rank(v) >= rank(latest[uid]):
            latest[uid] = v
    df = pd.DataFrame(latest.values()) if latest else pd.DataFrame(columns=["msf_trial_id", "readout"])
    df["result_json"] = df["result"].apply(lambda r: json.dumps(r) if isinstance(r, dict) else None) \
        if "result" in df.columns else None
    df = df.drop(columns=["result", "reader_result", "checker_version"], errors="ignore")
    df = df.drop(columns=["paper_list"], errors="ignore")
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
