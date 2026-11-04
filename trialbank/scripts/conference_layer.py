"""Conference reports: abstracts presented at the big neurology meetings, matched to the trials in the bank.

Results are presented at meetings 6 to 18 months before they are published, so this is where "what was found" first
appears. The AAN annual meeting publishes every abstract on a public index with sequential numbers
(index.mirasmart.com/AAN<year>/PDFfiles/AAN<year>-<number>.html), which this script sweeps once per meeting and
caches. ECTRIMS and ACTRIMS abstracts are published in a journal supplement whose website blocks automated readers,
so they are not harvested here. Company announcements and the news searches cover those results.

For each MS abstract: title, authors, the text, the meeting and year, and the trials it reports on, matched by
registry number, trial acronym, or medicine plus population named in the title. Only abstracts that match a trial
are kept. Nothing is judged here: a conference report never changes a hypothesis status (HYPOTHESES.md).

Writes data/conference_reports.parquet (+ CSV). Cache: raw/conference_cache.json.
Env: CONF_MEETINGS (default "AAN2026"), CONF_MAX_ID (default 6500), CONF_WORKERS (default 6).
Usage: python conference_layer.py
"""
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import literature_layer as lit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW, DATA = ROOT / "raw", ROOT / "data"
CACHE = RAW / "conference_cache.json"
VERSION = "conf_v1"
UA = {"User-Agent": "Mozilla/5.0 (compatible; MSFrontierBot/0.1; open MS research data; https://msfrontier.org)"}
MEETINGS = os.environ.get("CONF_MEETINGS", "AAN2026").split(",")
MAX_ID = int(os.environ.get("CONF_MAX_ID", "6500"))
WORKERS = int(os.environ.get("CONF_WORKERS", "6"))
MS_RX = re.compile(r"multiple sclerosis|neuromyelitis|\bNMOSD\b|\bMOGAD\b|MOG antibod|demyelinat|remyelinat|"
                   r"\bRRMS\b|\bSPMS\b|\bPPMS\b|\bCIS\b.*demyelin", re.I)
REG_RX = re.compile(r"\b(NCT\d{8}|ISRCTN\d{8}|\d{4}-\d{6}-\d{2}(?:-\d{2})?|EUCTR\d{4}-\d{6}-\d{2})\b", re.I)
POP_RX = {"relapsing": r"relapsing|\bRRMS\b|\bRMS\b", "progressive": r"progressive|\bSPMS\b|\bPPMS\b|\bnrSPMS\b",
          "early_cis_ris": r"clinically isolated|radiologically isolated|\bCIS\b|\bRIS\b", "nmosd": r"neuromyelitis|NMOSD",
          "mogad": r"MOGAD|MOG antibod"}
S = requests.Session()
S.headers.update(UA)


def strip(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def fetch_abstract(meeting, n):
    """One abstract page from the AAN index, or None when the number does not exist or is not about MS."""
    url = f"https://index.mirasmart.com/{meeting}/PDFfiles/{meeting}-{n:06d}.html"
    for attempt in range(3):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404:
                return {"n": n, "missing": True}
            if r.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    else:
        return None
    text = strip(r.text)
    if not MS_RX.search(text):
        return {"n": n, "ms": False}
    # the page is: "<year> American Academy of Neurology Abstract Website <title> <authors> <affiliations> Objective: ..."
    body = re.sub(r"^.*?Abstract Website\s*", "", text, count=1, flags=re.S)
    m = re.search(r"\b(Objective|Background|Introduction|Purpose)\s*:", body)
    head, abstract = (body[:m.start()], body[m.start():]) if m else (body[:300], body)
    # the title ends where the author list starts (a name followed by an affiliation number)
    t = re.split(r"\s(?=[A-Z][a-z]+(?:\s[A-Z]\.?)*\s[A-Z][A-Za-z'\-]+\s\d+\s?,)", head, maxsplit=1)
    title = t[0].strip()
    authors = t[1].strip()[:400] if len(t) > 1 else ""
    res = re.search(r"\bResults?\s*:\s*(.*?)(?=\bConclusions?\s*:|$)", abstract, flags=re.S)
    con = re.search(r"\bConclusions?\s*:\s*(.*)$", abstract, flags=re.S)
    return {"n": n, "ms": True, "title": title[:400], "authors": authors, "abstract": abstract[:6000],
            "results": (res.group(1).strip() if res else "")[:2500],
            "conclusion": (con.group(1).strip() if con else "")[:1200], "url": url}


def sweep(meeting, cache):
    key = meeting
    done = cache.setdefault(key, {})
    todo = [n for n in range(1, MAX_ID + 1) if str(n) not in done]
    # stop after a long run of missing numbers past the last existing one
    print(f"{meeting}: {len(done)} cached, {len(todo)} to fetch")
    missing_run, last_seen = 0, max((int(k) for k, v in done.items() if not v.get("missing")), default=0)
    with ThreadPoolExecutor(WORKERS) as ex:
        for i in range(0, len(todo), WORKERS * 10):
            batch = todo[i:i + WORKERS * 10]
            if batch[0] > last_seen + 400 and missing_run >= 400:
                break
            for res in ex.map(lambda n: fetch_abstract(meeting, n), batch):
                if res is None:
                    continue
                done[str(res["n"])] = res
                if res.get("missing"):
                    missing_run += 1
                else:
                    missing_run, last_seen = 0, max(last_seen, res["n"])
            CACHE.write_text(json.dumps(cache))
            time.sleep(0.5)
    return [v for v in done.values() if v.get("ms")]


def main():
    RAW.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    # what to match against
    trials = pd.read_parquet(DATA / "trials.parquet", columns=["msf_trial_id", "acronym", "title", "population_group",
                                                                "drugs", "phase", "status"])
    reg = pd.read_parquet(DATA / "trial_registry_ids.parquet")
    reg_map = dict(zip(reg.registry_id.astype(str).str.upper(), reg.msf_trial_id))
    # trial acronyms worth matching: at least five characters, or four with a digit or hyphen, written as the
    # registry writes them (case-sensitive), and never a disease, scale or method abbreviation
    STOP = {"NMOSD", "MOGAD", "EDSS", "MSFC", "SDMT", "PASAT", "PIRA", "NEDA", "RRMS", "SPMS", "PPMS", "CIS", "RIS",
            "ADEM", "AIDP", "CIDP", "MRI", "OCT", "GFAP", "BRAIN", "SPINE", "PAIN", "SLEEP", "HEART", "COVID", "LIFE",
            "STUDY", "TRIAL", "PHASE", "SMART", "POEMS", "MOGAD", "ADEM", "CIDP", "GBS", "ALS", "HIV", "FIRST", "CARE", "HOPE", "TIME", "FOCUS", "IMPACT", "ACTIVE", "EARLY"}
    acr = {}
    for r in trials.itertuples():
        a = re.sub(r"\s*\(.*?\)\s*$", "", str(r.acronym or "").strip())
        ok = (len(a) >= 5 or (len(a) == 4 and re.search(r"[\d\-]", a))) and len(a) <= 20 \
            and re.search(r"[A-Za-z]{3}", a) and not re.fullmatch(r"[A-Z]{1,3}\d+.*", a) and a.upper() not in STOP \
            and not re.fullmatch(r"[A-Z][a-z]+", a)   # a single capitalised word is a word, not an acronym
        if ok:
            acr.setdefault(a, set()).add(r.msf_trial_id)
    acr_rx = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(sorted(map(re.escape, acr), key=len, reverse=True)) + r")(?![A-Za-z0-9])") if acr else None
    rx, bank_names = lit.drug_matcher()
    by_drug_pop = {}
    for r in trials.itertuples():
        if r.status in ("withdrawn",) or not r.drugs:
            continue
        ds = list(r.drugs) if not isinstance(r.drugs, str) else r.drugs.split("|")
        for dname in ds:
            by_drug_pop.setdefault((str(dname).lower(), r.population_group), set()).add(r.msf_trial_id)

    rows = []
    for meeting in MEETINGS:
        year = int(re.search(r"\d{4}", meeting).group())
        society = re.sub(r"\d{4}", "", meeting)
        for a in sweep(meeting, cache):
            text = f"{a['title']} {a['abstract']}"
            matched, how = set(), []
            for m in REG_RX.findall(text):
                if m.upper() in reg_map:
                    matched.add(reg_map[m.upper()]); how.append("registry_number")
            if acr_rx:
                for m in acr_rx.findall(a["title"]):
                    for t in acr.get(m, ()):
                        matched.add(t); how.append("acronym_in_title")
            if not matched and rx:
                drugs = {bank_names[m.lower()][1] for m in rx.findall(a["title"])}
                pops = [p for p, prx in POP_RX.items() if re.search(prx, a["title"], re.I)]
                head = a["title"] + " " + a["abstract"][:400]
                if drugs and len(pops) == 1 and re.search(r"\bphase\s*(2|3|II|III|2b|3b)\b|randomi[sz]ed|placebo", head, re.I) \
                        and not re.search(r"real[- ]world|observational|case (report|series)|registry|retrospective|survey", a["title"], re.I):
                    for dname in drugs:
                        ts = by_drug_pop.get((dname, pops[0]), ())
                        if 1 <= len(ts) <= 3:   # a medicine with a few trials in that population, not a pooled analysis
                            for t in ts:
                                matched.add(t); how.append("medicine_and_population_in_title")
            if not matched:
                continue
            if not re.search(r"\bResults?\s*:", a["abstract"]):
                continue   # a case report or a design abstract, not a result
            kind = ("late_breaking" if re.search(r"late[- ]breaking", text, re.I) else
                    "trial_result" if re.search(r"\bResults?\s*:", a["abstract"]) and re.search(r"randomi[sz]ed|placebo|phase", text, re.I)
                    else "other")
            for t in sorted(matched):
                rows.append({"report_id": f"{meeting}-{a['n']:06d}:{t}", "meeting": society, "year": year,
                             "abstract_number": f"{meeting}-{a['n']:06d}", "msf_trial_id": t, "title": a["title"],
                             "authors": a["authors"], "results_text": a["results"], "conclusion_text": a["conclusion"],
                             "kind": kind, "match_rule": "|".join(sorted(set(how))), "url": a["url"],
                             "harvested_version": VERSION})
    df = pd.DataFrame(rows).drop_duplicates("report_id") if rows else pd.DataFrame(columns=[
        "report_id", "meeting", "year", "abstract_number", "msf_trial_id", "title", "authors", "results_text",
        "conclusion_text", "kind", "match_rule", "url", "harvested_version"])
    DATA.mkdir(exist_ok=True)
    df.to_parquet(DATA / "conference_reports.parquet", index=False)
    df.to_csv(DATA / "conference_reports.csv", index=False)
    print(f"conference reports: {len(df)} matched abstracts for {df.msf_trial_id.nunique() if len(df) else 0} trials")


if __name__ == "__main__":
    main()
