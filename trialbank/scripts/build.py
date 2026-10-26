"""Merge registries, normalise interventions, tag, and write the MSF trial bank v0.

Usage: python build.py   (reads ../raw, writes ../data)
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import chembl as C
import mechanisms as M
import parse_ctgov
import parse_euctr
import parse_isrctn
import tags as T

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "raw", ROOT / "data"
OUT.mkdir(exist_ok=True)
TODAY = date.today()
BUILD = {"version": "0.1.0", "built_at": TODAY.isoformat(), "tag_method": T.TAG_METHOD, "mechanism_map": M.VERSION}
REGISTRY_RANK = {"ctgov": 0, "euctr": 1, "isrctn": 2}
ONGOING = {"recruiting", "active_not_recruiting", "not_yet_recruiting", "enrolling_by_invitation", "ongoing",
           "ongoing_inferred", "suspended", "transitioned_to_ctis"}


# ------------------------------------------------------------------ load
def load():
    ct = parse_ctgov.parse(RAW / "ctgov_studies.jsonl")
    eu = parse_euctr.parse(RAW / "euctr_full.txt")
    isr = parse_isrctn.parse(str(RAW / "isrctn_*.xml"))
    trials = ct[0] + eu[0] + isr[0]
    ids = ct[1] + eu[1] + isr[1]
    ivs = ct[2] + eu[2] + isr[2]
    outcomes = ct[3] + eu[3] + isr[3]
    analyses = ct[4]
    refs = ct[5] + isr[4]
    return trials, ids, ivs, outcomes, analyses, refs


# ------------------------------------------------------------------ dedupe
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def dedupe(trials, ids):
    present = {t["registry_id"] for t in trials}
    uf = UF()
    for t in trials:
        uf.find(t["registry_id"])
    for r in ids:
        if r["other_id"] in present and r["other_id"] != r["registry_id"]:
            uf.union(r["registry_id"], r["other_id"])
    groups = defaultdict(list)
    for t in trials:
        groups[uf.find(t["registry_id"])].append(t)
    return list(groups.values())


MERGE_UNION = ("countries", "phenotypes", "diseases", "primary_endpoint_tags", "interventions_raw")


def merge_group(group):
    group = sorted(group, key=lambda t: REGISTRY_RANK[t["registry"]])
    base = dict(group[0])
    base["registries"] = "|".join(t["registry"] for t in group)
    base["registry_ids"] = "|".join(t["registry_id"] for t in group)
    for other in group[1:]:
        for k, v in other.items():
            if k.startswith("_"):
                continue
            if base.get(k) in (None, "", []) and v not in (None, "", []):
                base[k] = v
        for k in MERGE_UNION:
            vals = set(filter(None, (base.get(k) or "").split("|"))) | set(filter(None, (other.get(k) or "").split("|")))
            base[k] = "|".join(sorted(vals))
        base["n_result_pmids"] = (base.get("n_result_pmids") or 0) + (other.get("n_result_pmids") or 0)
        base["_prim_ps"] = base["_prim_ps"] + other["_prim_ps"]
    base["n_countries"] = len([c for c in base["countries"].split("|") if c])
    tiers = [t["tier"] for t in group if t["tier"]]
    base["tier"] = min(tiers) if tiers else None
    base["population_group"] = T.population_group(base["phenotypes"].split("|"), base["diseases"].split("|"))
    return base


# ------------------------------------------------------------------ derived tags
def infer_status(t):
    if t["status"]:
        return t["status"], False
    end = t.get("completion_date")
    if end:
        return ("completed_inferred" if end < TODAY.isoformat() else "ongoing_inferred"), True
    return None, True


def result_signal(t):
    """Machine-derived result status. Not a judgement of benefit: see data dictionary."""
    st = t["status"] or ""
    if st == "stopped":
        st = t["status"] = "terminated"
    if st in ("terminated", "withdrawn"):
        return f"{st}:{t['why_stopped_class'] or 'reason_not_given'}"
    ps = t["_prim_ps"]
    if ps:
        sup = [(p, op) for p, op, ni in ps if not re.search(r"NON_INFERIORITY|EQUIVALENCE", ni or "")]
        if not sup:
            return "primary_tested_noninferiority"
        sig = [p for p, op in sup if (op in ("<", "≤", "<=") and p <= 0.05) or (op == "=" and p < 0.05)]
        return "primary_p_lt_0.05" if sig else "primary_p_ge_0.05"
    if t.get("has_posted_results"):
        return "results_posted_no_primary_test"
    if t.get("n_result_pmids"):
        return "publication_linked"
    if t.get("_epmc_trial_reports"):
        return "publication_found_europepmc"
    if st in ONGOING:
        return "ongoing"
    end = t.get("primary_completion_date") or t.get("completion_date")
    if st.startswith("completed") and t["study_type"] == "interventional" and end and \
            end < (TODAY - timedelta(days=730)).isoformat():
        return "completed_no_results_found"
    if st.startswith("completed"):
        return "completed_recent_or_undated"
    if st in ("unknown", ""):
        return "status_unknown"
    return st


# ------------------------------------------------------------------ main
def main():
    trials, ids, ivs, outcomes, analyses, refs = load()
    print("parsed:", Counter(t["registry"] for t in trials))
    groups = dedupe(trials, ids)
    merged = [merge_group(g) for g in groups]
    rid_to_uid = {}
    for m in merged:
        uid = "MSFT-" + m["registry_ids"].split("|")[0]
        m["msf_trial_id"] = uid
        for rid in m["registry_ids"].split("|"):
            rid_to_uid[rid] = uid
    scope = [m for m in merged if m["tier"]]
    print(f"merged {len(trials)} registry records -> {len(merged)} trials; in scope (tier 1/2): {len(scope)}")

    # ---- interventions -> ChEMBL -> mechanism nodes
    drug_types = {"drug", "biological", "combination_product", "dietary_supplement", "genetic"}
    cache = C.load_cache()
    scope_rids = {rid for m in scope for rid in m["registry_ids"].split("|")}
    iv_rows = []
    for iv in ivs:
        if iv["registry_id"] not in scope_rids:
            continue
        uid = rid_to_uid[iv["registry_id"]]
        row = {"msf_trial_id": uid, "registry_id": iv["registry_id"], "registry": iv["registry"],
               "intervention_type": iv["intervention_type"], "name_raw": iv["name_raw"],
               "other_names": iv["other_names"], "role": iv["role"],
               "is_comparator": iv["role"] != "experimental"}
        mol = None
        if iv["intervention_type"] in drug_types and iv["role"] != "placebo_or_sham":
            _, mol = C.best_match(iv["name_raw"], cache)
            if not mol:
                for o in (iv["other_names"] or "").split("; "):
                    _, mol = C.best_match(o, cache)
                    if mol:
                        break
        if mol:
            cid = mol["molecule_chembl_id"]
            mechs = cache["mech"].get(cid, [])
            targets = sorted({cache["targets"].get(x["target_chembl_id"], "") for x in mechs} - {""})
            atc = [cache["atc"].get(c, {}) for c in (mol.get("atc_classifications") or [])]
            row.update({
                "chembl_id": cid, "drug_name": (mol.get("pref_name") or "").lower() or None,
                "molecule_type": mol.get("molecule_type"), "max_phase_any_indication": mol.get("max_phase"),
                "mechanism_of_action": "|".join(sorted({x["mechanism_of_action"] for x in mechs if x.get("mechanism_of_action")})),
                "action_type": "|".join(sorted({x["action_type"] for x in mechs if x.get("action_type")})),
                "targets": "|".join(targets),
                "atc_codes": "|".join(mol.get("atc_classifications") or []),
                "atc_level3": "|".join(sorted({a.get("level3") or "" for a in atc} - {""})),
                "normalisation": "chembl_exact_name",
            })
            # nodes come from the canonical molecule only; raw names can describe combinations
            match_text = " ".join(filter(None, [row["drug_name"], row["mechanism_of_action"], row["targets"], row["atc_level3"]]))
            if not M.assign(match_text):
                match_text += " " + " ".join(filter(None, [iv["name_raw"], iv["other_names"]]))
        else:
            row.update({"chembl_id": None, "drug_name": None, "molecule_type": None, "max_phase_any_indication": None,
                        "mechanism_of_action": None, "action_type": None, "targets": None, "atc_codes": None,
                        "atc_level3": None,
                        "normalisation": "unmatched" if iv["intervention_type"] in drug_types and iv["role"] != "placebo_or_sham" else "not_a_drug"})
            match_text = " ".join(filter(None, [iv["name_raw"], iv["other_names"]]))
        nodes = [] if iv["role"] == "placebo_or_sham" else M.assign(match_text)
        row["mechanism_nodes"] = "|".join(n for n, _ in nodes)
        row["mechanism_families"] = "|".join(sorted({f for _, f in nodes}))
        row["nondrug_category"] = None if iv["intervention_type"] in drug_types else \
            M.nondrug_category(iv["intervention_type"], f"{iv['name_raw']} {iv.get('description', '')}")
        iv_rows.append(row)
    ivdf = pd.DataFrame(iv_rows)

    # ---- trial-level rollups
    comp_drugs = ivdf[ivdf.role == "active_comparator"].groupby("msf_trial_id").drug_name \
        .agg(lambda x: "|".join(sorted(set(x.dropna())))).to_dict()
    by_uid = ivdf[ivdf.role == "experimental"].groupby("msf_trial_id")
    roll = {}
    for uid, g in by_uid:
        roll[uid] = {
            "comparator_drugs": comp_drugs.get(uid, ""),
            "drugs": "|".join(sorted(set(g.drug_name.dropna()))),
            "chembl_ids": "|".join(sorted(set(g.chembl_id.dropna()))),
            "mechanism_nodes": "|".join(sorted({n for x in g.mechanism_nodes if x for n in x.split("|")})),
            "mechanism_families": "|".join(sorted({n for x in g.mechanism_families if x for n in x.split("|")})),
            "nondrug_categories": "|".join(sorted(set(g.nondrug_category.dropna()))),
            "n_unmatched_drug_names": int((g.normalisation == "unmatched").sum()),
        }
    epmc_path = RAW / "europepmc_cache.json"
    epmc = json.loads(epmc_path.read_text()) if epmc_path.exists() else {}
    all_ids_by_uid = defaultdict(set)
    for r in ids:
        if r["registry_id"] in rid_to_uid:
            all_ids_by_uid[rid_to_uid[r["registry_id"]]].add(r["other_id"])
    epmc_rows = []
    for m in scope:
        seen, reports = set(), 0
        for x in sorted(all_ids_by_uid[m["msf_trial_id"]]):
            for h in epmc.get(x) or []:
                key = h.get("pmid") or h.get("id")
                if key in seen:
                    continue
                seen.add(key)
                pt = (h.get("pubType") or "").lower()
                is_report = bool(re.search(r"clinical trial|randomized controlled trial", pt)) and "review" not in pt
                reports += is_report
                epmc_rows.append({"msf_trial_id": m["msf_trial_id"], "matched_registry_id": x, "pmid": h.get("pmid"),
                                  "pmcid": h.get("pmcid"), "doi": h.get("doi"), "title": (h.get("title") or "")[:300],
                                  "journal": h.get("journalTitle"), "pub_year": h.get("pubYear"), "pub_type": h.get("pubType"),
                                  "is_trial_report_type": is_report, "source": "europepmc_registry_id_mention"})
        m["_epmc_trial_reports"] = reports
        m["n_europepmc_mentions"] = len(seen)
        m["n_europepmc_trial_reports"] = reports
    rows = []
    for m in scope:
        status, inferred = infer_status(m)
        m["status"] = status
        m["status_inferred"] = inferred
        r = {k: v for k, v in m.items() if not k.startswith("_")}
        r.update(roll.get(m["msf_trial_id"], {"drugs": "", "chembl_ids": "", "mechanism_nodes": "", "mechanism_families": "",
                                               "nondrug_categories": "", "n_unmatched_drug_names": 0,
                                               "comparator_drugs": comp_drugs.get(m["msf_trial_id"], "")}))
        r["result_signal"] = result_signal(m)
        r["start_year"] = int(m["start_date"][:4]) if m.get("start_date") and re.match(r"\d{4}", m["start_date"]) else None
        r["tag_method"] = T.TAG_METHOD
        r["review_status"] = "machine_tagged"
        rows.append(r)
    trials_df = pd.DataFrame(rows)
    # ---- hand-curated overrides (each carries a source)
    trials_df["curation_note"] = None
    trials_df["curated_fields"] = None
    ov_path = ROOT / "curation" / "overrides.csv"
    if ov_path.exists():
        ov = pd.read_csv(ov_path)
        for _, o in ov.iterrows():
            mask = trials_df.msf_trial_id == o.msf_trial_id
            if not mask.any():
                print("override for unknown trial:", o.msf_trial_id)
                continue
            trials_df.loc[mask, o.field] = o.value
            prev = trials_df.loc[mask, "curated_fields"].iloc[0]
            trials_df.loc[mask, "curated_fields"] = "|".join(filter(None, [prev, o.field]))
            trials_df.loc[mask, "review_status"] = "partly_curated"
    first = ["msf_trial_id", "registry_ids", "registries", "url", "title", "acronym", "tier", "diseases", "ms_focus",
             "population_group", "phenotypes", "study_type", "phase", "status", "status_inferred", "result_signal",
             "start_year", "start_date", "primary_completion_date", "completion_date", "enrollment", "enrollment_type",
             "allocation", "masking", "has_placebo_or_sham", "primary_purpose", "drugs", "comparator_drugs", "chembl_ids", "mechanism_families",
             "mechanism_nodes", "nondrug_categories", "intervention_types", "primary_endpoint_class", "primary_endpoint_tags",
             "lead_sponsor", "sponsor_class", "n_countries", "countries", "why_stopped", "why_stopped_class",
             "has_posted_results", "results_first_posted", "n_result_pmids"]
    trials_df = trials_df[first + [c for c in trials_df.columns if c not in first]]
    trials_df = trials_df.drop(columns=["registry", "registry_id"])
    trials_df = trials_df.sort_values(["tier", "start_date"], ascending=[True, False], na_position="last")

    # ---- side tables
    keep = set(trials_df.msf_trial_id)
    id_df = pd.DataFrame(ids).drop_duplicates()
    id_df["msf_trial_id"] = id_df.registry_id.map(rid_to_uid)
    id_df = id_df[id_df.msf_trial_id.isin(keep)][["msf_trial_id", "registry", "registry_id", "id_type", "other_id"]]
    out_df = pd.DataFrame(outcomes)
    out_df["msf_trial_id"] = out_df.registry_id.map(rid_to_uid)
    out_df = out_df[out_df.msf_trial_id.isin(keep)]
    an_df = pd.DataFrame(analyses)
    an_df["msf_trial_id"] = an_df.registry_id.map(rid_to_uid)
    an_df = an_df[an_df.msf_trial_id.isin(keep)]
    ref_df = pd.DataFrame(refs).drop_duplicates(["registry_id", "pmid"])
    ref_df["msf_trial_id"] = ref_df.registry_id.map(rid_to_uid)
    ref_df = ref_df[ref_df.msf_trial_id.isin(keep)]

    # ---- drug table
    comp_count = ivdf[(ivdf.role == "active_comparator") & ivdf.chembl_id.notna()].groupby("chembl_id").msf_trial_id.nunique()
    d = ivdf[ivdf.chembl_id.notna() & (ivdf.role == "experimental")]
    tmap = trials_df.set_index("msf_trial_id")
    drug_rows = []
    for cid, g in d.groupby("chembl_id"):
        uids = sorted(set(g.msf_trial_id))
        sub = tmap.loc[uids]
        drug_rows.append({
            "chembl_id": cid, "drug_name": g.drug_name.iloc[0], "molecule_type": g.molecule_type.iloc[0],
            "max_phase_any_indication": g.max_phase_any_indication.iloc[0],
            "mechanism_of_action": g.mechanism_of_action.iloc[0], "targets": g.targets.iloc[0],
            "atc_level3": g.atc_level3.iloc[0], "mechanism_nodes": g.mechanism_nodes.iloc[0],
            "mechanism_families": g.mechanism_families.iloc[0],
            "n_trials": len(uids), "n_trials_as_comparator": int(comp_count.get(cid, 0)),
            "n_interventional": int((sub.study_type == "interventional").sum()),
            "n_phase3": int(sub.phase.fillna("").str.contains("phase3").sum()),
            "n_progressive_population": int(sub.population_group.isin(["progressive", "relapsing_and_progressive"]).sum()),
            "n_terminated": int(sub.status.isin(["terminated"]).sum()),
            "n_primary_p_lt_005": int((sub.result_signal == "primary_p_lt_0.05").sum()),
            "n_primary_p_ge_005": int((sub.result_signal == "primary_p_ge_0.05").sum()),
            "first_trial_start": sub.start_date.dropna().min() if sub.start_date.notna().any() else None,
            "latest_trial_start": sub.start_date.dropna().max() if sub.start_date.notna().any() else None,
            "raw_names_seen": "|".join(sorted(set(g.name_raw))[:12]),
            "msf_trial_ids": "|".join(uids),
        })
    drugs_df = pd.DataFrame(drug_rows).sort_values("n_trials", ascending=False)
    unmatched = ivdf[ivdf.normalisation == "unmatched"].groupby("name_raw").msf_trial_id.nunique() \
        .sort_values(ascending=False).rename("n_trials").reset_index()
    nodes_df = pd.DataFrame([{"node_id": i, "family": f, "label": lab, "rule_regex": rx} for i, f, lab, rx in M.NODES])
    nodes_df["n_trials"] = nodes_df.node_id.map(lambda n: int(trials_df.mechanism_nodes.fillna("").str.split("|").map(lambda x: n in x).sum()))

    # ---- write
    tables = {"trials": trials_df, "trial_registry_ids": id_df, "trial_interventions": ivdf[ivdf.msf_trial_id.isin(keep)],
              "trial_outcomes": out_df, "trial_primary_analyses_ctgov": an_df, "trial_publications": ref_df,
              "trial_publications_europepmc": pd.DataFrame(epmc_rows), "drugs": drugs_df, "mechanism_nodes": nodes_df, "unmatched_intervention_names": unmatched}
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        df.to_parquet(OUT / f"{name}.parquet", index=False)
    stats = summarise(trials_df, ivdf, drugs_df, Counter(t["registry"] for t in trials), len(merged))
    (OUT / "build_stats.json").write_text(json.dumps({**BUILD, **stats}, indent=2, default=str))
    print(json.dumps(stats, indent=1, default=str)[:4000])


def summarise(t, ivdf, drugs, reg_counts, n_merged):
    intr = t[t.study_type == "interventional"]
    drug_iv = ivdf[ivdf.intervention_type.isin(["drug", "biological", "combination_product", "dietary_supplement", "genetic"]) & (ivdf.role != "placebo_or_sham")]
    return {
        "registry_records_parsed": dict(reg_counts),
        "unique_trials_after_dedupe": n_merged,
        "trials_in_scope": len(t),
        "by_tier": t.tier.value_counts().to_dict(),
        "by_study_type": t.study_type.value_counts().to_dict(),
        "multi_registry_trials": int(t.registries.str.contains(r"\|").sum()),
        "interventional_by_population": intr.population_group.value_counts().to_dict(),
        "interventional_by_phase": intr.phase.fillna("none").value_counts().to_dict(),
        "interventional_by_status": intr.status.fillna("none").value_counts().head(12).to_dict(),
        "interventional_by_result_signal": intr.result_signal.value_counts().to_dict(),
        "interventional_by_primary_endpoint": intr.primary_endpoint_class.fillna("none").value_counts().to_dict(),
        "interventional_by_mechanism_family": intr.mechanism_families.fillna("").str.split("|").explode().replace("", "none").value_counts().to_dict(),
        "drug_intervention_rows": len(drug_iv),
        "drug_rows_matched_to_chembl": int(drug_iv.chembl_id.notna().sum()),
        "distinct_chembl_molecules": len(drugs),
    }


if __name__ == "__main__":
    main()
