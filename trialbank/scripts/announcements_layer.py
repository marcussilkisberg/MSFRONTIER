"""Company and conference announcements as provisional readouts.

Sponsors announce trial results in press releases months before a paper exists (fenebrutinib FENhance, PIPE-307
VISTA, foralumab INFORM-MS). This script reads the news items the daily run has collected (news/items.json) and the
conference reports (data/conference_reports.parquet), finds the ones that report a result of a trial in the bank,
and records what they say: met, not met, mixed, safety, or other. Every row is marked as provisional: it is shown on
the trial page as "Reported by the sponsor" or "Reported at a conference", and it never changes a hypothesis status
(HYPOTHESES.md). When the paper or registry result arrives, the trial readout takes over.

Matching: a news item is linked to a trial when its title or text names the trial's acronym, or a medicine tested in
the trial together with a word for the trial's population and a result word. Reading: Claude extracts the result,
and every number in its summary must appear in the source text (the same rule as the news summaries).

Writes data/trial_announcements.parquet (+ CSV). Cache and log: readouts/announcements_cache.json and
readouts/announcements_log.json, committed with the readouts so a run can be inspected afterwards.
Env: ANTHROPIC_API_KEY (reading; without it nothing new is read), ANN_MAX (default 60 new readings per run).
Usage: python announcements_layer.py
"""
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import literature_layer as lit  # noqa: E402
from conference_layer import MEETING_MONTH  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW, DATA, NEWS = ROOT / "raw", ROOT / "data", ROOT / "news" / "items.json"
CACHE = ROOT / "readouts" / "announcements_cache.json"   # versioned in the repository with the readouts
LOG = ROOT / "readouts" / "announcements_log.json"       # what this run decided, and any error, for inspection
VERSION = "ann_v2"
MODEL = os.environ.get("ANN_MODEL", "claude-sonnet-5-5")
MAX_NEW = int(os.environ.get("ANN_MAX", "60"))
RESULT_RX = re.compile(r"\b(results?|topline|top-line|met|missed|did not meet|primary endpoint|efficacy|positive|"
                       r"negative|reduc\w+|significan\w+|failed|succeed\w*)\b", re.I)
POP_RX = {"relapsing": r"relapsing|\bRRMS\b|\bRMS\b", "progressive": r"progressive|\bSPMS\b|\bPPMS\b|\bnrSPMS\b",
          "relapsing_and_progressive": r"relapsing|progressive", "early_cis_ris": r"clinically isolated|\bCIS\b|\bRIS\b",
          "nmosd": r"neuromyelitis|NMOSD", "mogad": r"MOGAD|MOG antibod", "unspecified": r"multiple sclerosis|\bMS\b"}
PROMPT = """You read an announcement about a clinical trial in multiple sclerosis for MSFrontier, a database of MS
research. Say what the announcement reports about the trial named below. Use only the text given.

Trial: {acronym} ({msf_trial_id}), testing {drugs} in {population}
Announcement source: {source}, {date}
Title: {title}
Text: {text}

Reply with JSON only:
{{"about_this_trial": true/false,   // does the text report results of THIS trial (not another trial of the medicine)?
  "result": "met|not_met|mixed|safety|no_result|other",   // met = main goal met; not_met = main goal missed;
                                                          // mixed = some measures yes, others no; safety = a safety
                                                          // finding or a stop; no_result = no result reported yet
  "measure": "...",                 // the main measure named, in a few words, or ""
  "summary": "...",                 // one or two plain sentences, at most 40 words, only facts in the text,
                                    // no hype words, numbers only if they appear in the text
  "peer_reviewed": true/false}}     // is this a journal publication (true) or a press release, abstract or news (false)?"""


def read_one(prompt):
    """One reading by Claude, as a dict, or None when the API call failed. A comment after a value ("// ...")
    is stripped before parsing, but not the "//" of a web address."""
    for model in (MODEL, lit.MODEL):
        try:
            text = lit.call(prompt, model=model)
        except Exception as e:   # one bad reading must not stop the run
            log(f"reading failed: {type(e).__name__} {str(e)[:200]}")
            if "404" in str(e) or "not_found" in str(e):
                continue   # the requested model does not exist for this key: try the default one
            return None
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
        m = re.search(r"\{.*\}", re.sub(r"(?<![:\w])//[^\n]*", "", text), re.S)
        if not m:
            log("reading failed: no JSON in reply: " + text[:160].replace("\n", " "))
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as e:
            log(f"reading failed: bad JSON: {str(e)[:80]}")
            return None
    return None


def numbers_ok(summary, source):
    nums = set(re.findall(r"\d+(?:[.,]\d+)?", summary))
    return all(n in source for n in nums)


def load_news():
    if not NEWS.exists():
        return []
    store = json.loads(NEWS.read_text())
    items = list(store.values()) if isinstance(store, dict) else store
    return [i for i in items if i.get("title")]


LOG_ROWS = []


def log(line):
    print(line)
    LOG_ROWS.append(line)


def main():
    RAW.mkdir(exist_ok=True)
    CACHE.parent.mkdir(exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    trials = pd.read_parquet(DATA / "trials.parquet", columns=["msf_trial_id", "acronym", "title", "population_group",
                                                                "drugs", "status", "phase", "primary_completion_date"])
    # trials worth reading announcements for: phase 2 or later, interventional, with a medicine or a name
    acr = {}
    for r in trials.itertuples():
        a = re.sub(r"\s*\(.*?\)\s*$", "", str(r.acronym or "").strip())
        if 4 <= len(a) <= 20 and re.search(r"[A-Za-z]{3}", a) and not re.fullmatch(r"[A-Z]{1,3}\d+.*", a):
            acr.setdefault(a.upper(), []).append(r)
    acr_rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, acr), key=len, reverse=True)) + r")\b") if acr else None
    rx, bank_names = lit.drug_matcher()
    by_drug = {}
    for r in trials.itertuples():
        ds = list(r.drugs) if r.drugs is not None and not isinstance(r.drugs, str) else str(r.drugs or "").split("|")
        for dname in ds:
            if dname:
                by_drug.setdefault(str(dname).lower(), []).append(r)

    # candidate (announcement, trial) pairs
    cands = []
    for it in load_news():
        text = f"{it['title']} {it.get('description') or ''}"
        if not RESULT_RX.search(text):
            continue
        found = {}
        if acr_rx:
            for m in acr_rx.findall(text):
                for r in acr[m.upper()]:
                    found[r.msf_trial_id] = (r, "acronym")
        if not found and rx:
            drugs = {bank_names[m.lower()][1] for m in rx.findall(text)}
            for dname in drugs:
                rs = [r for r in by_drug.get(dname, []) if r.status not in ("withdrawn",)
                      and re.search(POP_RX.get(r.population_group, "multiple sclerosis"), text, re.I)
                      and any(p in str(r.phase) for p in ("phase2", "phase3"))]
                if 1 <= len(rs) <= 3:   # a medicine with one or a few trials in that population
                    for r in rs:
                        found[r.msf_trial_id] = (r, "medicine_and_population")
        for tid, (r, how) in found.items():
            cands.append((it, r, how))
    # conference reports are already matched: read their results text the same way
    conf = pd.read_parquet(DATA / "conference_reports.parquet") if (DATA / "conference_reports.parquet").exists() else pd.DataFrame()
    tmap = {r.msf_trial_id: r for r in trials.itertuples()}
    for c in conf.itertuples():
        if c.kind in ("trial_result", "late_breaking") and c.msf_trial_id in tmap and c.results_text:
            month = MEETING_MONTH.get(str(c.meeting).upper(), 6)
            cands.append(({"id": c.report_id, "source": f"{c.meeting} {c.year}", "title": c.title, "link": c.url,
                           "published_at": f"{c.year}-{month:02d}-01", "description": f"{c.results_text} {c.conclusion_text}",
                           "source_type": "conference"}, tmap[c.msf_trial_id], c.match_rule))

    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    n_new, n_failed, rows = 0, 0, []
    for it, r, how in cands:
        key = f"{it['id']}:{r.msf_trial_id}"
        if key not in cache or cache[key].get("version") != VERSION:
            if not have_key or n_new >= MAX_NEW:
                continue
            ds = list(r.drugs) if r.drugs is not None and not isinstance(r.drugs, str) else str(r.drugs or "").split("|")
            prompt = PROMPT.format(acronym=r.acronym or "(no acronym)", msf_trial_id=r.msf_trial_id,
                                   drugs=", ".join(d for d in ds if d) or "an intervention",
                                   population=str(r.population_group).replace("_", " "), source=it.get("source"),
                                   date=str(it.get("published_at") or "")[:10], title=it["title"],
                                   text=(it.get("description") or "(none)")[:5000])
            j = read_one(prompt)
            n_new += 1
            if j is None:   # the API failed: leave the item uncached so the next run tries again
                n_failed += 1
                if n_failed >= 5:
                    log("announcements: five readings failed in a row, stopping new readings this run")
                    have_key = False
                continue
            n_failed = 0
            src_text = f"{it['title']} {it.get('description') or ''}"
            about, result = bool(j.get("about_this_trial")), j.get("result")
            nums = numbers_ok(j.get("summary") or "", src_text)
            ok = about and result in ("met", "not_met", "mixed", "safety") and nums
            why = "ok" if ok else ("not about this trial" if not about else f"result {result}" if result not in (
                "met", "not_met", "mixed", "safety") else "a number in the summary is not in the source")
            log(f"  {r.acronym or r.msf_trial_id} <- {it.get('source')}: {str(it['title'])[:60]!r}: {why}")
            cache[key] = {"ok": ok, "result": result, "measure": j.get("measure"), "summary": j.get("summary"),
                          "peer_reviewed": bool(j.get("peer_reviewed")), "why": why, "version": VERSION}
            CACHE.write_text(json.dumps(cache))
        c = cache[key]
        if not c.get("ok"):
            continue
        rows.append({"announcement_id": key, "msf_trial_id": r.msf_trial_id, "source": it.get("source"),
                     "source_type": "conference" if it.get("source_type") == "conference" else "announcement",
                     "title": it["title"], "url": it.get("link"), "published_at": str(it.get("published_at") or "")[:10] or None,
                     "result": c["result"], "measure": (c.get("measure") or "")[:200], "summary": (c.get("summary") or "")[:400],
                     "peer_reviewed": c.get("peer_reviewed", False), "match_rule": how, "read_by": MODEL,
                     "provisional": True})
    df = pd.DataFrame(rows).drop_duplicates("announcement_id") if rows else pd.DataFrame(columns=[
        "announcement_id", "msf_trial_id", "source", "source_type", "title", "url", "published_at", "result",
        "measure", "summary", "peer_reviewed", "match_rule", "read_by", "provisional"])
    df.to_parquet(DATA / "trial_announcements.parquet", index=False)
    df.to_csv(DATA / "trial_announcements.csv", index=False)
    log(f"announcements: {len(cands)} candidates, {n_new} read this run, {len(df)} results for "
        f"{df.msf_trial_id.nunique() if len(df) else 0} trials")


if __name__ == "__main__":
    import datetime
    import traceback
    err = None
    try:
        main()
    except Exception:   # the log must be written even when the step fails
        err = traceback.format_exc()
        log("announcements: FAILED\n" + err)
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text(json.dumps({"run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                               "have_key": bool(os.environ.get("ANTHROPIC_API_KEY")), "model": MODEL,
                               "lines": LOG_ROWS[-400:], "error": err}, indent=1))
    if err:
        raise SystemExit(1)
