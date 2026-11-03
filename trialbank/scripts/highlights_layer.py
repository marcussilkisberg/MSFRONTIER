"""Trials to watch: the running trials most likely to change what is known, chosen by fixed rules.

Three themes:
  progressive  trials in progressive MS that measure disability, walking, arm function or brain tissue loss
  repair       trials of myelin repair or nerve protection
  remission    trials aiming at lasting remission without lifelong treatment, or at preventing MS: stem-cell
               transplant, immune reconstitution, CAR-T and other cell therapies, tolerance, EBV-targeted treatment,
               and treatment of early MS (CIS or RIS) to prevent it

A trial qualifies when it is interventional, running or about to start, phase 2 or later (not phase 1/2), randomised
(or placebo-controlled where the registry does not state allocation), not in healthy volunteers, has at least
40 participants, has no known main result yet, and its main results are not more than six months overdue. Strategy
trials that involve more than six medicines (stopping treatment, infection care) are left out. Each qualifying trial gets a score from its phase, its size,
how soon its main results are due, and whether it tests an approach that is not yet confirmed for that group of
people (a confirmed approach tested again is less likely to change what is known). The top eight per theme are kept.
Every highlight carries a sentence built from the same facts, so readers can see why it was chosen.

Outputs ../data/trial_highlights.parquet. Usage: python highlights_layer.py
"""
import math
import re
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TODAY = pd.Timestamp(date.today())
RUNNING = {"recruiting", "active_not_recruiting", "not_yet_recruiting", "enrolling_by_invitation", "ongoing",
           "ongoing_inferred"}
PROG_POPS = {"progressive", "relapsing_and_progressive"}
PROG_ENDPOINTS = {"disability_progression", "walking_mobility", "upper_limb", "brain_atrophy",
                  "smouldering_inflammation"}
REPAIR_NODES = {"remyelination", "axonal_neuroprotection", "mitochondrial_oxidative"}
REMISSION_NODES = {"immune_reconstitution", "cell_therapy_tolerance", "antiviral_ebv", "nd-cell_or_transplant"}
IGNORE_NODES = {"imaging_tracer", "corticosteroid", "spasticity", "bladder", "pain_mood_cognition",
                "fatigue_wakefulness", "walking_k_channel"}   # premedication, contrast agents and symptom care
THEMES = {"progressive": "Progressive MS", "repair": "Repair and protection", "remission": "Towards lasting remission"}
POP_LABEL = {"progressive": "progressive MS", "relapsing_and_progressive": "relapsing and progressive MS",
             "relapsing": "relapsing MS", "early_cis_ris": "early MS (CIS or RIS)", "unspecified": "MS",
             "nmosd": "NMOSD", "mogad": "MOGAD"}


def split(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return []
    if isinstance(v, str):
        return [x for x in v.split("|") if x]
    return [str(x) for x in v]


def phase_of(p):
    p = "|".join(split(p))
    return "phase3" if "phase3" in p else "phase2" if "phase2" in p else None


AIM_PHRASE = {"progressive": "slows disability worsening", "repair": "protects nerves or repairs myelin",
              "remission": "can stop the disease for years without continuous treatment"}


def short_name(acronym, drugs, phase_label):
    """The trial's acronym when it reads as a name, else "<medicine>, <phase>". A code such as ZB020-03-002 or
    CFTY720D2311 (digits, or no vowels, or longer than 20 characters) is not a name."""
    a = "" if acronym is None or (isinstance(acronym, float) and math.isnan(acronym)) else str(acronym).strip()
    a = re.sub(r"\s*\(.*?\)\s*$", "", a)            # "OCTOPUS (PLATYPUS in Australia)" -> "OCTOPUS"
    a = re.sub(r"[_ ]v\d+(\.\d+)*$", "", a, flags=re.I)
    code = (not a or a.upper() == "ND" or len(a) < 3 or len(a) > 20 or len(re.findall(r"\d", a)) >= 3
            or not re.search(r"[aeiouyAEIOUY]", a))
    if not code:
        return a
    d = re.split(r",| and ", drugs or "")[0].strip()
    return f"{d[:1].upper()}{d[1:]}, {phase_label}" if d else f"Trial, {phase_label}"


def main():
    t = pd.read_parquet(DATA / "trials.parquet")
    t = t[(t.study_type == "interventional") & t.status.isin(RUNNING)].copy()
    t["ph"] = t.phase.map(phase_of)
    t = t[t.ph.notna()]
    t["n"] = pd.to_numeric(t.enrollment, errors="coerce").fillna(0)
    unstated = t.allocation.isna() | (t.allocation == "")   # some registries (ISRCTN) do not state it ("na" = single arm)
    t = t[(t.n >= 40) & ((t.allocation == "randomized") |
                         (unstated & (t.has_placebo_or_sham.fillna(False).astype(bool) | (t.ph == "phase3"))))]
    t = t[~t.phase.map(lambda p: "|".join(split(p))).isin(["phase1|phase2"])]           # first-in-human dose finding
    t = t[~t.title.fillna("").str.contains(r"healthy (?:subjects|volunteers|participants)", case=False)]
    # leave out trials whose main result is already known, or whose main results were due more than six months ago
    t = t[~t.result_signal.isin(["primary_p_lt_0.05", "primary_p_ge_0.05"])]
    if (DATA / "trial_readouts.parquet").exists():
        rd = pd.read_parquet(DATA / "trial_readouts.parquet")
        t = t[~t.msf_trial_id.isin(rd[rd.readout.isin(["met", "not_met", "mixed", "equivalent"])].msf_trial_id)]
    due_all = pd.to_datetime(t.primary_completion_date, errors="coerce")
    t = t[due_all.isna() | (due_all >= TODAY - pd.Timedelta(days=183))]

    confirmed = set()
    if (DATA / "hypotheses.parquet").exists():
        h = pd.read_parquet(DATA / "hypotheses.parquet")
        confirmed = set(zip(h[h.outcome == "confirmed"].approach_group, h[h.outcome == "confirmed"].population))
    labels = {}
    if (DATA / "mechanism_nodes.parquet").exists():
        labels = pd.read_parquet(DATA / "mechanism_nodes.parquet").set_index("node_id").label.to_dict()

    rows = []
    for r in t.itertuples():
        nodes = (set(split(r.mechanism_nodes)) | set(split(r.nondrug_categories))) - IGNORE_NODES
        tested = [d for d in split(r.drugs) if d not in set(split(r.comparator_drugs))]
        if len(split(r.drugs)) > 6:
            continue   # strategy trials that switch between many medicines (stopping treatment, infection care)
        ends = set(split(r.primary_endpoint_tags))
        pop = r.population_group
        themes = []
        if (pop in PROG_POPS or "progressive" in str(r.title).lower()) and ends & PROG_ENDPOINTS:
            themes.append("progressive")
        if nodes & REPAIR_NODES or "remyelination" in ends:
            themes.append("repair")
        car_t = "car-t" in str(r.title).lower() or "car t" in str(r.title).lower() or "chimeric antigen" in str(
            r.official_title).lower()
        if nodes & REMISSION_NODES or car_t or (pop == "early_cis_ris" and r.ph == "phase3" and tested):
            themes.append("remission")
        if not themes:
            continue
        due = pd.to_datetime(r.primary_completion_date, errors="coerce")
        months = (due - TODAY).days / 30.4 if pd.notna(due) else None
        groups = sorted([n for n in nodes if not n.startswith("nd-")] or list(nodes))
        tested_pop = "progressive" if pop in PROG_POPS else pop
        new_for_group = not any((g, p) in confirmed for g in groups
                                for p in ({tested_pop, "spms", "ppms"} if tested_pop == "progressive" else {tested_pop}))
        score = (3 if r.ph == "phase3" else 1.5) + math.log10(max(r.n, 1)) + (1 if new_for_group else 0) \
            + (1 if months is not None and 0 <= months <= 24 else 0.5 if months is not None and months <= 48 else 0)
        main = next((g for g in groups if g in REMISSION_NODES | REPAIR_NODES), groups[0] if groups else None)
        approach = labels.get(main, (main or "").replace("nd-", "").replace("_", " ")) if main else (
            "CAR-T cell therapy" if car_t else "a new approach")
        drugs = " and ".join(tested[:2]) if len(tested) <= 2 else ", ".join(tested[:2]) + " and others"
        plain = re.sub(r"\s*\(.*\)$", "", approach or "").strip()
        what = drugs or (plain[:1].lower() + plain[1:] if plain and not plain[:2].isupper() else plain)
        kind = ""
        phase_label = "phase 3" if r.ph == "phase3" else "phase 2"
        name = short_name(r.acronym, drugs or approach, phase_label)
        for th in themes:
            why = f"Tests whether {what}{kind} {AIM_PHRASE[th]} in {POP_LABEL.get(pop, 'MS')}."
            if new_for_group:
                why += " No medicine of this kind is yet confirmed for this group."
            rows.append({"theme": th, "theme_label": THEMES[th], "msf_trial_id": r.msf_trial_id,
                         "name": name, "phase": r.ph,
                         "enrollment": int(r.n), "population_group": pop, "drugs": "|".join(split(r.drugs)),
                         "approach": approach, "primary_completion_date": due.date() if pd.notna(due) else None,
                         "new_for_group": new_for_group, "score": round(score, 3), "why": why,
                         "as_of": date.today().isoformat()})
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["theme", "score"], ascending=[True, False]).groupby("theme").head(8)
        df["rank"] = df.groupby("theme").cumcount() + 1
        # two trials of the same medicine and phase: add the group of people to tell them apart
        dup = df.duplicated(["theme", "name"], keep=False)
        df.loc[dup, "name"] = df.loc[dup].apply(lambda r: f"{r['name']}, {POP_LABEL.get(r['population_group'], 'MS')}",
                                                axis=1)
    df.to_parquet(DATA / "trial_highlights.parquet", index=False)
    print(f"highlights: {len(df)} trials to watch ({df.theme.value_counts().to_dict() if len(df) else {}})")


if __name__ == "__main__":
    main()
