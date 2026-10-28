"""Results watch: finished phase 2-4 trials whose results we cannot find anywhere, a year or more after the end.

A trial is listed only after four checks fail to find results:
  1. posted results in any registry (ClinicalTrials.gov, the EU portal CTIS);
  2. the EU Clinical Trials Register results page (checked live, trial by trial);
  3. papers that cite the trial's registry number (Europe PMC, registry links) or that we have already read;
  4. a search for papers that do NOT cite the number: by drug, condition and design, published after the trial
     started; a model decides whether a candidate reports THIS trial, quoting the sentence word for word.
Readers can report results we missed; those go in ../curation/results_known.csv and override everything.

Outputs ../data/results_watch.parquet. Caches: ../readouts/results_watch_cache.json (committed: paid model calls),
../raw/eu_results_cache.json. Env: ANTHROPIC_API_KEY for check 4 (without it, check 4 is skipped and the trial is
marked "not fully checked").
Usage: python results_watch_layer.py
"""
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA, RAW = ROOT / "data", ROOT / "raw"
CACHE = ROOT / "readouts" / "results_watch_cache.json"
EU_CACHE = RAW / "eu_results_cache.json"
KNOWN = ROOT / "curation" / "results_known.csv"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("RESULTS_WATCH_MODEL", "claude-sonnet-5-5")
PHASES = {"phase2", "phase3", "phase2|phase3", "phase4", "phase1|phase2"}
FINISHED = {"completed", "terminated", "completed_inferred"}
GRACE_MONTHS = 12          # US (FDAAA) and EU rules both expect results within 12 months of the end of the trial
VERSION = "rw_v1"

MATCH_PROMPT = """Does this paper report the results of the clinical trial described below? A paper reports the trial
only if it is the same study: same treatment, same condition, a matching design and size, and run by the same group
or sponsor. Secondary analyses of the same trial also count. A different trial of the same drug does NOT count.

TRIAL
Title: {title}
Registry IDs: {ids}
Sponsor: {sponsor}
Phase: {phase}; participants: {n}; started: {start}; ended: {end}
Treatment: {drugs}

PAPER
Title: {ptitle} ({pyear}, {journal})
Abstract: {abstract}

Reply with JSON only: {{"same_trial": true/false, "quote": "one sentence copied exactly from the abstract that shows
it (design, size or sponsor), or empty"}}"""


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip().lower()


def get(url, **kw):
    for k in range(3):
        try:
            r = requests.get(url, timeout=45, **kw)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    return None


def eu_results(eudract, cache):
    """True if the EU Clinical Trials Register shows posted results for this EudraCT number."""
    if eudract in cache and cache[eudract].get("checked") >= (date.today() - timedelta(days=28)).isoformat():
        return cache[eudract]
    r = get(f"https://www.clinicaltrialsregister.eu/ctr-search/trial/{eudract}/results")
    if r is None:
        return cache.get(eudract) or {"has": None}
    m = re.search(r"First version publication date\s*(?:<[^>]+>\s*)*([0-9]{1,2} [A-Za-z]{3} [0-9]{4})", r.text)
    cache[eudract] = {"has": "Results version number" in r.text, "first": m.group(1) if m else None,
                      "checked": date.today().isoformat()}
    time.sleep(0.4)
    return cache[eudract]


def search_papers(t):
    """Papers about the same drug and condition, published after the trial started, that may report it."""
    drugs = [d for d in str(t.drugs or "").split("|") if len(d) >= 5][:3]
    if not drugs:   # names not matched to ChEMBL (e.g. "Nanocurcumin"): use the registered names, doses removed
        for raw in str(t.interventions_raw or "").split("|"):
            name = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|µg|ml|iu|%)\b.*", "", raw, flags=re.I).strip(" ,-")
            name = " ".join(name.split()[:3])
            if len(name) >= 5 and not re.search(r"placebo|sham|standard|usual care", name, re.I):
                drugs.append(name)
        drugs = list(dict.fromkeys(drugs))[:3]
    def field(x):   # title or abstract only: full-text matches bring in reviews and unrelated trials
        return f'(TITLE:"{x}" OR ABSTRACT:"{x}")'
    terms = [field(d) for d in drugs]
    if isinstance(t.acronym, str) and re.fullmatch(r"[A-Za-z0-9-]{4,}", t.acronym):
        terms.append(field(t.acronym))
    if not terms:
        return []
    cond = "(" + " OR ".join(field(c) for c in ("multiple sclerosis", "neuromyelitis", "NMOSD", "MOGAD",
                                                  "optic neuritis")) + ")"
    start = str(t.start_date or "")[:10] or "2000-01-01"
    q = (f"({' OR '.join(terms)}) AND {cond} AND (PUB_TYPE:\"clinical trial\" OR PUB_TYPE:\"randomized controlled "
         f"trial\" OR ABSTRACT:\"randomized\" OR ABSTRACT:\"randomised\" OR ABSTRACT:\"open-label\") AND "
         f"FIRST_PDATE:[{start} TO 3000-01-01]")
    r = get(EPMC, params={"query": q, "format": "json", "resultType": "core", "pageSize": 8})
    if r is None:
        return []
    out = []
    for p in r.json().get("resultList", {}).get("result", []):
        types = [x.lower() for x in (p.get("pubTypeList") or {}).get("pubType", [])]
        if any("review" in x for x in types) or not p.get("abstractText"):
            continue
        out.append({"pmid": p.get("pmid"), "doi": p.get("doi"), "title": p.get("title"),
                    "year": p.get("pubYear"), "journal": ((p.get("journalInfo") or {}).get("journal") or {})
                    .get("medlineAbbreviation"), "abstract": p.get("abstractText")})
    return out[:5]


def ask(prompt):
    key = os.environ["ANTHROPIC_API_KEY"]
    for k in range(4):
        r = requests.post(API, timeout=90, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                   "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            text = "".join(b.get("text", "") for b in r.json()["content"])
            m = re.search(r"\{.*\}", text, re.S)
            try:
                return json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                return None
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (k + 1))
            continue
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:200]}")
    return None


def main():
    t = pd.read_parquet(DATA / "trials.parquet")
    ids = pd.read_parquet(DATA / "trial_registry_ids.parquet")
    p1 = pd.read_parquet(DATA / "trial_publications.parquet")
    p2 = pd.read_parquet(DATA / "trial_publications_europepmc.parquet")
    rd = pd.read_parquet(DATA / "trial_readouts.parquet") if (DATA / "trial_readouts.parquet").exists() \
        else pd.DataFrame(columns=["msf_trial_id", "readout", "reason"])
    known = pd.read_csv(KNOWN) if KNOWN.exists() else pd.DataFrame(columns=["msf_trial_id", "url", "note"])
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    eu_cache = json.loads(EU_CACHE.read_text()) if EU_CACHE.exists() else {}
    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    today = pd.Timestamp(date.today())
    t = t[(t.study_type == "interventional") & t.phase.isin(PHASES) & t.status.isin(FINISHED)].copy()
    t["end"] = pd.to_datetime(t.primary_completion_date.fillna(t.completion_date), errors="coerce")
    t = t[t.end.notna() & (t.end >= pd.Timestamp("2008-01-01"))
          & (t.end <= today - pd.DateOffset(months=GRACE_MONTHS))]

    result_papers = set(p1[p1.ref_type.astype(str).str.lower().isin(["result", "resultsarticle", "derived"])]
                        .msf_trial_id) | set(p2[p2.is_trial_report_type == True].msf_trial_id)  # noqa: E712
    read = set(rd[rd.readout.isin(["met", "not_met", "mixed", "equivalent", "not_efficacy"])].msf_trial_id)
    eud = ids[ids.other_id.astype(str).str.fullmatch(r"\d{4}-\d{6}-\d{2}")].groupby("msf_trial_id").other_id.agg(list)

    rows, n_calls = [], 0
    for r in t.itertuples():
        uid = r.msf_trial_id
        where, found = [], None
        if bool(r.has_posted_results):
            found = ("registry", r.url)
        elif uid in result_papers or uid in read:
            found = ("paper_citing_registry_number", None)
        else:
            where.append("registries")
            where.append("papers citing its registry number")
            for e in eud.get(uid, []):
                res = eu_results(e, eu_cache)
                if res.get("has"):
                    found = ("eu_register", f"https://www.clinicaltrialsregister.eu/ctr-search/trial/{e}/results")
                    break
            if eud.get(uid):
                where.append("EU Clinical Trials Register results")
        if not found and uid in set(known.msf_trial_id):
            k = known[known.msf_trial_id == uid].iloc[0]
            found = ("reported_by_reader", k.url)
        fully_checked = True
        if not found:
            key = f"{uid}|{VERSION}"
            if key not in cache and have_key:
                cands = search_papers(r)
                match = None
                for c in cands:
                    j = ask(MATCH_PROMPT.format(title=r.official_title or r.title, ids=r.registry_ids,
                                                sponsor=r.lead_sponsor, phase=r.phase, n=r.enrollment,
                                                start=r.start_date, end=str(r.end)[:10], drugs=r.drugs,
                                                ptitle=c["title"], pyear=c["year"], journal=c["journal"],
                                                abstract=norm(c["abstract"])[:3000])) or {}
                    n_calls += 1
                    q = (j.get("quote") or "").strip()
                    if j.get("same_trial") and len(q) >= 20 and norm(q) in norm(c["abstract"]):
                        match = {**{k2: c[k2] for k2 in ("pmid", "doi", "title", "year", "journal")}, "quote": q}
                        break
                cache[key] = {"searched_on": date.today().isoformat(), "n_candidates": len(cands), "match": match}
            entry = cache.get(key)
            if entry is None:
                fully_checked = False
            else:
                where.append("a search for papers that do not cite its number")
                if entry.get("match"):
                    m = entry["match"]
                    found = ("unlinked_paper", f"https://pubmed.ncbi.nlm.nih.gov/{m['pmid']}/" if m.get("pmid")
                             else f"https://doi.org/{m.get('doi')}")
        months = int((today - r.end).days // 30.44)
        rows.append({
            "msf_trial_id": uid, "acronym": r.acronym, "title": r.title, "phase": r.phase, "status": r.status,
            "lead_sponsor": r.lead_sponsor, "sponsor_class": r.sponsor_class, "enrollment": r.enrollment,
            "registry_ids": r.registry_ids, "end_date": str(r.end)[:10], "months_since_end": months,
            "results_found": bool(found), "found_where": found[0] if found else None,
            "found_link": found[1] if found else None, "fully_checked": fully_checked,
            "checked_sources": "; ".join(where) if not found else None,
            "watch_status": ("results_found" if found else "no_results_found" if fully_checked
                             else "not_fully_checked"),
            "as_of": date.today().isoformat(),
        })
        if n_calls and n_calls % 40 == 0:
            CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    EU_CACHE.write_text(json.dumps(eu_cache))
    df = pd.DataFrame(rows)
    df.to_parquet(DATA / "results_watch.parquet", index=False)
    print(f"results watch: {len(df)} finished trials; {df.watch_status.value_counts().to_dict()}; "
          f"{n_calls} model checks this run")


if __name__ == "__main__":
    main()
