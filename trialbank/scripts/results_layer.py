"""Results layer: every posted outcome measure (per arm) and per-arm safety totals from ClinicalTrials.gov.

Source data is structured registry results, so nothing here is extracted by a language model.
Writes data/trial_results.parquet and data/trial_arm_safety.parquet (+ CSV).
Usage: python results_layer.py   (run after build.py)
"""
import json
import re
from pathlib import Path

import pandas as pd

import tags as T

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "raw", ROOT / "data"


def main():
    trials = pd.read_parquet(OUT / "trials.parquet")
    rid_to_uid = {}
    drugs_by_uid = {}
    for _, t in trials.iterrows():
        for rid in (t.registry_ids or "").split("|"):
            rid_to_uid[rid] = t.msf_trial_id
        drugs_by_uid[t.msf_trial_id] = [d for d in (t.drugs or "").split("|") if d] + \
                                       [d for d in (t.comparator_drugs or "").split("|") if d]

    rows, safety = [], []
    for line in open(RAW / "ctgov_studies.jsonl"):
        rec = json.loads(line)
        uid = rid_to_uid.get(rec["nct_id"])
        res = rec["study"].get("resultsSection")
        if not uid or not res:
            continue
        drugs = drugs_by_uid.get(uid, [])

        def arm_drugs(title, desc):
            # the arm title names the arm's drug; descriptions often also mention matching placebos of other drugs
            for text in (title.lower(), desc.lower()):
                hit = "|".join(d for d in drugs if d and d.lower() in text)
                if hit:
                    return hit
            return ""

        for m in res.get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
            groups = {g["id"]: g for g in m.get("groups", [])}
            denoms = {}
            for dn in m.get("denoms", []):
                for c in dn.get("counts", []):
                    denoms[c["groupId"]] = c.get("value")
            # one p-value summary per outcome (first superiority analysis), carried on each row
            p_raw = p_val = est_type = est = ci_l = ci_u = None
            for a in m.get("analyses", []):
                if re.search(r"NON_INFERIORITY|EQUIVALENCE", a.get("nonInferiorityType") or ""):
                    continue
                p_raw = a.get("pValue")
                p_val, _ = T.parse_p(p_raw)
                est_type, est = a.get("paramType"), a.get("paramValue")
                ci_l, ci_u = a.get("ciLowerLimit"), a.get("ciUpperLimit")
                break
            etags = "|".join(T.tag_endpoint(f"{m.get('title', '')} {m.get('description', '')}"))
            for cls in m.get("classes", []):
                for cat in cls.get("categories", []):
                    for meas in cat.get("measurements", []):
                        g = groups.get(meas.get("groupId"), {})
                        gt, gd = g.get("title", ""), g.get("description", "")
                        rows.append({
                            "msf_trial_id": uid, "registry_id": rec["nct_id"],
                            "outcome_type": (m.get("type") or "").lower(),
                            "outcome_title": (m.get("title") or "")[:300],
                            "endpoint_tags": etags,
                            "time_frame": (m.get("timeFrame") or "")[:200],
                            "class_title": (cls.get("title") or "")[:120] or None,
                            "category_title": (cat.get("title") or "")[:120] or None,
                            "arm_title": gt[:200],
                            "arm_is_placebo": T.is_placebo(gt) and not arm_drugs(gt, ""),
                            "arm_drugs": arm_drugs(gt, gd) or None,
                            "n_analysed": _int(denoms.get(meas.get("groupId"))),
                            "param_type": (m.get("paramType") or "").lower(),
                            "value": _num(meas.get("value")), "value_raw": meas.get("value"),
                            "unit": (m.get("unitOfMeasure") or "")[:120],
                            "dispersion_type": m.get("dispersionType"),
                            "spread": _num(meas.get("spread")),
                            "lower_limit": _num(meas.get("lowerLimit")), "upper_limit": _num(meas.get("upperLimit")),
                            "analysis_p_value_raw": p_raw, "analysis_p_value": p_val,
                            "analysis_estimate_type": est_type, "analysis_estimate": est,
                            "analysis_ci_lower": ci_l, "analysis_ci_upper": ci_u,
                            "source": "clinicaltrials.gov posted results",
                            "extraction_method": "registry_structured",
                        })

        for g in res.get("adverseEventsModule", {}).get("eventGroups", []):
            gt, gd = g.get("title", ""), g.get("description", "")
            safety.append({
                "msf_trial_id": uid, "registry_id": rec["nct_id"], "arm_title": gt[:200],
                "arm_is_placebo": T.is_placebo(gt) and not arm_drugs(gt, ""), "arm_drugs": arm_drugs(gt, gd) or None,
                "at_risk": g.get("seriousNumAtRisk") or g.get("otherNumAtRisk"),
                "serious_affected": g.get("seriousNumAffected"),
                "deaths": g.get("deathsNumAffected"),
                "other_affected": g.get("otherNumAffected"),
                "source": "clinicaltrials.gov posted results",
            })

    r = pd.DataFrame(rows)
    s = pd.DataFrame(safety)
    for name, df in (("trial_results", r), ("trial_arm_safety", s)):
        df.to_parquet(OUT / f"{name}.parquet", index=False)
        df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"results: {len(r)} rows from {r.msf_trial_id.nunique()} trials; arm safety: {len(s)} rows")


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


if __name__ == "__main__":
    main()
