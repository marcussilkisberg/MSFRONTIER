"""Effect sizes: how much a treatment changed the main measures, from the registry's posted results and from the
result papers already read by the readouts step. No new reading happens here.

Two sources, normalised into one table:
  registry  ClinicalTrials.gov posted results (data/trial_results.parquet): per arm values, the sponsor's analysis
            (estimate type, estimate, confidence interval, p-value). The landmark trials (OPERA, ORATORIO, ASCLEPIOS,
            HERCULES) are here.
  paper     The readouts (readouts/readouts_cache.json): the primary effect the result paper's abstract reports,
            every number verified word for word against the abstract. Older trials (AFFIRM) are here.

Each row is one comparison on one measure: the measure's family (relapse, disability_progression, mri_lesions,
walking_mobility and so on, from the endpoint tags), the kind of effect (hazard_ratio, rate_ratio, odds_ratio,
risk_ratio, mean_difference, percent_difference), the estimate with its interval and p-value, the comparator
(placebo, or the active medicine), and for ratio effects on bad events the relative reduction in per cent. Arm
values are kept where the registry gives them, so a relapse rate of 0.156 against 0.292 can be shown as "14 fewer
relapses per 100 people per year". The direction a result favours is set only where it is unambiguous: a ratio
below 1 on a bad event (relapses, progression, lesions) with p < 0.05 favours the treatment. Mean differences are
kept as reported and not given a direction, because which sign is good depends on the measure.

Writes data/trial_effects.parquet (+ CSV). Usage: python effects_layer.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VERSION = "effects_v1"
NUM = re.compile(r"-?\d+(?:\.\d+)?")
BAD_EVENT = {"relapse", "disability_progression", "mri_lesions", "brain_atrophy"}
VEHICLE = {"sodium chloride", "saline", "water", "glucose", "dextrose", "mannitol", "nan", "none", ""}   # not medicines


def drug_list(v):
    return [x for x in dict.fromkeys(str(v or "").split("|")) if x and x.lower() not in VEHICLE]


def experimental(t):
    """The trial's own medicines, without its comparators."""
    comp = set(drug_list(t.comparator_drugs))
    return [x for x in drug_list(t.drugs) if x not in comp] or drug_list(t.drugs)
FAMILY_WORDS = [  # for paper effects, whose measure is free text: first match wins
    ("relapse", r"relapse"), ("disability_progression", r"disability|progression|\bEDSS\b|\bCDP\b|\bCDW\b|\bPIRA\b"),
    ("mri_lesions", r"lesion|gadolinium|\bT2\b|\bT1\b|GdE|enhancing"), ("brain_atrophy", r"brain volume|atrophy"),
    ("walking_mobility", r"walk|T25FW|gait|6MWT|mobility"), ("upper_limb", r"9-?HPT|peg|hand|upper limb"),
    ("cognition", r"cognit|SDMT|PASAT|memory|processing speed"), ("fatigue", r"fatigue|MFIS|FSS"),
    ("spasticity", r"spastic|Ashworth"), ("pain", r"\bpain\b"), ("bladder_bowel_sexual", r"bladder|urin|bowel|sexual"),
    ("mood_sleep", r"depress|anxiety|sleep|mood"), ("quality_of_life_pro", r"quality of life|MSIS|SF-36|MSQOL"),
    ("vision", r"visual|vision|acuity"), ("fluid_biomarker", r"neurofilament|\bNfL\b|\bGFAP\b|biomarker"),
    ("remyelination", r"remyelinat|VEP|latency|myelin"), ("immune_response", r"antibod|B[- ]cell|lymphocyte|titre|titer")]
EFFECT_TYPES = [
    ("hazard_ratio", r"hazard"), ("rate_ratio", r"rate ratio|rate\s*ratio|relapse rate ratio|\bRR\b.*rate|lesion ratio|ratio of (?:adjusted )?(?:mean|annual)"),
    ("odds_ratio", r"odds"), ("risk_ratio", r"risk ratio|relative risk|\bRR\b"), ("percent_difference", r"percent|%|relative reduction|reduction"),
    ("mean_difference", r"mean|difference|\bLS\b|least squares|change|estimate|effect size|median|net")]


def num(v):
    """A number from the registry's or the paper's text: '0.536', '.029', '−0.097', '72%', '0·76'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).replace("−", "-").replace("–", "-").replace("·", ".").replace(",", "").strip()
    m = NUM.search(s)
    return float(m.group()) if m else None


def family_of(tags, measure):
    """The measure's own words first (an "Annualized Relapse Rate" is a relapse measure whatever the trial's tags
    say), then the endpoint tags."""
    for fam, rx in FAMILY_WORDS:
        if re.search(rx, str(measure or ""), re.I):
            return fam
    for tg in str(tags or "").split("|"):
        if tg and tg not in ("safety_tolerability", "pharmacokinetics", "feasibility", "physical_function", "neurophysiology"):
            return tg
    return "other"


def effect_type_of(text):
    t = str(text or "")
    for et, rx in EFFECT_TYPES:
        if re.search(rx, t, re.I):
            return et
    return "other"


def favours(effect_type, estimate, family, p):
    """Only where the direction is beyond doubt."""
    if estimate is None or family not in BAD_EVENT or effect_type not in ("hazard_ratio", "rate_ratio", "odds_ratio", "risk_ratio"):
        return None
    if p is not None and p >= 0.05:
        return "neither"
    if p is None:
        return None
    return "treatment" if estimate < 1 else "comparator"


def orient(a, b, t, effect_type, est):
    """Which of two active arms is the treatment. The registry's comparator drugs decide when exactly one arm is
    made of them; otherwise, for a ratio, the orientation that reproduces the estimate from the arm values; otherwise
    the registry's order (the experimental arm is listed first)."""
    import math
    comp = set(str(t.comparator_drugs or "").split("|")) - {""}
    a_d, b_d = set(str(a.arm_drugs or "").split("|")) - {""}, set(str(b.arm_drugs or "").split("|")) - {""}
    a_c, b_c = bool(a_d) and a_d <= comp, bool(b_d) and b_d <= comp
    if a_c != b_c:
        return (b, a) if a_c else (a, b)
    va, vb = num(a.value), num(b.value)
    if effect_type in ("hazard_ratio", "rate_ratio", "odds_ratio", "risk_ratio") and va and vb and va > 0 and vb > 0 and est and est > 0:
        if abs(math.log(va / vb) - math.log(est)) > abs(math.log(vb / va) - math.log(est)):
            return b, a
    return a, b


def registry_effects(results, trials):
    rows = []
    res = results[results.analysis_estimate.notna()].copy()
    for (uid, title, tf), g in res.groupby(["msf_trial_id", "outcome_title", "time_frame"], dropna=False):
        if uid not in trials.index:
            continue
        t = trials.loc[uid]
        arms = g.drop_duplicates("arm_title")
        first = g.iloc[0]
        et = effect_type_of(first.analysis_estimate_type)
        if et == "risk_ratio" and re.search(r"\brate\b", str(title), re.I):
            et = "rate_ratio"
        if re.search(r"reduction", str(first.analysis_estimate_type or ""), re.I) and re.search(r"%|percent", str(first.analysis_estimate_type or ""), re.I):
            et = "percent_reduction"
        est, lo, hi = num(first.analysis_estimate), num(first.analysis_ci_lower), num(first.analysis_ci_upper)
        p = num(first.analysis_p_value) if pd.notna(first.analysis_p_value) else None
        if est is None:
            continue
        plc = arms[arms.arm_is_placebo == True]   # noqa: E712
        act = arms[arms.arm_is_placebo != True]   # noqa: E712
        comparator = "placebo" if len(plc) else None
        trt_value = ctrl_value = trt_n = ctrl_n = None
        trt_drug = None
        if len(arms) == 2:
            if len(plc) == 1:
                trt, ctrl = act.iloc[0], plc.iloc[0]
            else:
                trt, ctrl = orient(arms.iloc[0], arms.iloc[1], t, et, est)
                comp_drugs = set(str(t.comparator_drugs or "").split("|")) - {""}
                ctrl_drugs = drug_list(ctrl.arm_drugs)
                named = [x for x in ctrl_drugs if x in comp_drugs] or ctrl_drugs
                comparator = ", ".join(named) or str(ctrl.arm_title)[:60]
            trt_value, ctrl_value = num(trt.value), num(ctrl.value)
            trt_n, ctrl_n = (int(trt.n_analysed) if pd.notna(trt.n_analysed) else None), (int(ctrl.n_analysed) if pd.notna(ctrl.n_analysed) else None)
            comp_drugs = set(str(t.comparator_drugs or "").split("|")) - {""}
            trt_list = drug_list(trt.arm_drugs)
            trt_drug = ", ".join([x for x in trt_list if x not in comp_drugs] or trt_list) or None
        if comparator is None:
            comparator = ", ".join(drug_list(t.comparator_drugs)) or "other arm"
        fam = family_of(first.endpoint_tags, title)
        key = hashlib.md5(f"{title}|{tf}".encode()).hexdigest()[:10]
        rows.append({"effect_id": f"reg:{uid}:{key}", "msf_trial_id": uid, "source": "registry",
                     "pmid": None, "outcome_type": str(first.outcome_type or "").lower(), "measure": str(title)[:300],
                     "time_frame": (str(tf)[:120] if pd.notna(tf) else None), "family": fam, "effect_type": et,
                     "effect_type_raw": str(first.analysis_estimate_type or "")[:80], "estimate": est, "ci_low": lo,
                     "ci_high": hi, "p_value": p, "comparator": comparator, "comparator_is_placebo": comparator == "placebo",
                     "treatment": (trt_drug or ", ".join(experimental(t)))[:120] or None,
                     "treatment_value": trt_value, "comparator_value": ctrl_value, "treatment_n": trt_n, "comparator_n": ctrl_n,
                     "value_unit": (str(first.unit)[:60] if pd.notna(first.unit) else None), "n_arms": int(len(arms)),
                     "favours": favours(et, est, fam, p), "quote": None, "version": VERSION})
    return rows


def paper_effects(readouts, trials):
    rows = []
    for v in readouts:
        res = v.get("result") if isinstance(v.get("result"), dict) else None
        if not res or not isinstance(res.get("effect"), dict) or not res["effect"].get("value"):
            continue
        uid = v["msf_trial_id"]
        if uid not in trials.index:
            continue
        t = trials.loc[uid]
        e = res["effect"]
        raw_val = str(e.get("value"))
        est = num(raw_val)
        if est is None:
            continue
        et = effect_type_of(e.get("type") or "") if not raw_val.strip().endswith("%") else "percent_difference"
        p = num(res.get("p")) if res.get("p") else None
        if p is not None and re.search(r"<\s*0?\.0", str(res.get("p"))):
            p = min(p, 0.049)   # "p < 0.001" is below the threshold
        fam = family_of(str(t.primary_endpoint_tags or ""), res.get("measure"))
        groups = res.get("groups") or []
        plc = [g for g in groups if re.search(r"placebo|sham", str(g.get("group")), re.I)]
        comparator = "placebo" if plc else (", ".join(drug_list(t.comparator_drugs)) or "other arm")
        rows.append({"effect_id": f"pap:{uid}:{v.get('pmid')}", "msf_trial_id": uid, "source": "paper", "pmid": str(v.get("pmid") or "") or None,
                     "outcome_type": "primary", "measure": (res.get("measure") or "")[:300], "time_frame": (res.get("follow_up") or None),
                     "family": fam, "effect_type": et, "effect_type_raw": str(e.get("type") or "")[:80], "estimate": est,
                     "ci_low": num(e.get("ci_lower")), "ci_high": num(e.get("ci_upper")), "p_value": p, "comparator": comparator,
                     "comparator_is_placebo": comparator == "placebo",
                     "treatment": ", ".join(experimental(t))[:120] or None,
                     "treatment_value": None, "comparator_value": None, "treatment_n": None, "comparator_n": None,
                     "value_unit": None, "n_arms": len(groups) or None, "favours": favours(et, est, fam, p),
                     "quote": (v.get("quote") or "")[:500] or None, "version": VERSION})
    return rows


def main():
    trials = pd.read_parquet(DATA / "trials.parquet").set_index("msf_trial_id")
    results = pd.read_parquet(DATA / "trial_results.parquet")
    cache_path = ROOT / "readouts" / "readouts_cache.json"
    readouts = []
    if cache_path.exists():
        c = json.loads(cache_path.read_text())
        readouts = list(c.values()) if isinstance(c, dict) else c
    rows = registry_effects(results, trials) + paper_effects(readouts, trials)
    df = pd.DataFrame(rows)
    if len(df):
        # a ratio below 1 on a bad event is a relative reduction
        ratio = df.effect_type.isin(["hazard_ratio", "rate_ratio", "odds_ratio", "risk_ratio"]) & df.family.isin(BAD_EVENT)
        sig = (df.p_value < 0.05) | (df.p_value.isna() & (df.ci_high < 1))
        df["relative_reduction_pct"] = ((1 - df.estimate) * 100).round(0).where(ratio & sig & (df.estimate > 0) & (df.estimate < 1))
        pr = (df.effect_type == "percent_reduction") & df.family.isin(BAD_EVENT) & sig & (df.estimate > 0)
        df.loc[pr, "relative_reduction_pct"] = df.loc[pr, "estimate"].round(0)
        # absolute difference per 100 people, where both arm values are rates or proportions
        both = df.treatment_value.notna() & df.comparator_value.notna() & df.family.isin(BAD_EVENT)
        df["absolute_diff_per_100"] = ((df.comparator_value - df.treatment_value) * 100).round(1).where(both)
        df = df[df.treatment.notna()].drop_duplicates("effect_id")
    DATA.mkdir(exist_ok=True)
    df.to_parquet(DATA / "trial_effects.parquet", index=False)
    df.to_csv(DATA / "trial_effects.csv", index=False)
    n_reg, n_pap = int((df.source == "registry").sum()) if len(df) else 0, int((df.source == "paper").sum()) if len(df) else 0
    print(f"effects: {len(df)} rows for {df.msf_trial_id.nunique() if len(df) else 0} trials ({n_reg} registry, {n_pap} paper); "
          f"{int(df.relative_reduction_pct.notna().sum()) if len(df) else 0} with a relative reduction")


if __name__ == "__main__":
    main()
