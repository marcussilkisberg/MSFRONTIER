"""Genetic leads: genes linked to MS by human genetics (Open Targets), and whether any drug acting on them has been
tested in an MS trial in the bank. Every link is computed through ChEMBL IDs; nothing is linked by hand.

Writes ../data/genetic_leads.parquet and ../data/drug_targets.parquet. Cache: ../raw/opentargets_cache.json.
Usage: python genetics_layer.py
"""
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA, RAW = ROOT / "data", ROOT / "raw"
CACHE = RAW / "opentargets_cache.json"
API = "https://api.platform.opentargets.org/api/v4/graphql"
# Open Targets files MS under this node (labelled "multiple sclerosis symptom measurement", with RRMS and chronic
# progressive MS as children). Checked on every run; MONDO_0005301 is the fallback.
DISEASE_IDS = ["EFO_0803536", "MONDO_0005301", "EFO_0003885"]
MIN_GENETIC_SCORE = 0.1
# Ligand-receptor partners: a drug that blocks the partner tests the same pathway (e.g. frexalimab binds CD40L,
# not CD40). A rule list in code, applied to every gene; not a per-hypothesis link.
PARTNERS = {"CD40": ["CD40LG"], "CD40LG": ["CD40"], "TNFRSF1A": ["TNF"], "TNF": ["TNFRSF1A", "TNFRSF1B"],
            "IL7R": ["IL7"], "CD58": ["CD2"], "CD2": ["CD58"], "IL2RA": ["IL2"], "IL12A": ["IL12RB1", "IL12RB2"],
            "IL12B": ["IL12RB1", "IL23R"], "IFNGR2": ["IFNG"], "IFNGR1": ["IFNG"], "TNFSF14": ["TNFRSF14", "LTBR"],
            "CD86": ["CTLA4", "CD28"], "CD80": ["CTLA4", "CD28"], "CD6": ["ALCAM"], "IL6R": ["IL6"],
            "VCAM1": ["ITGA4"], "ITGA4": ["VCAM1"], "CXCR4": ["CXCL12"], "IL21R": ["IL21"], "IL23R": ["IL23A"],
            "CD226": ["PVR"], "TNFRSF14": ["TNFSF14"], "LTBR": ["LTB", "TNFSF14"], "IL22RA2": ["IL22"]}
MOA_FALLBACK = {"frexalimab": ["CD40LG"], "remibrutinib": ["BTK"], "divozilimab": ["MS4A1"], "laquinimod": ["AHR"],
                "oditrasertib": ["RIPK1"], "rapcabtagene autoleucel": ["CD19"], "zolacabtagene autoleucel": ["CD19"]}
STAGE_RANK = {"APPROVAL": 5, "PHASE_4": 5, "PHASE_3": 4, "PHASE_2_3": 3.5, "PHASE_2": 3, "PHASE_1_2": 2.5,
              "PHASE_1": 2, "EARLY_PHASE_1": 1.5, "PRECLINICAL": 1, "WITHDRAWAL": 4.5}


def gql(query, variables=None, tries=4):
    for k in range(tries):
        try:
            r = requests.post(API, json={"query": query, "variables": variables or {}}, timeout=120)
            j = r.json()
            if "errors" in j:
                raise RuntimeError(j["errors"][0]["message"][:300])
            return j["data"]
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(3 * (k + 1))


def pick_disease():
    for did in DISEASE_IDS:
        d = gql('query($id:String!){ disease(efoId:$id){ id name children{ name } } }', {"id": did})["disease"]
        if d and (did != "EFO_0803536" or any("relapsing-remitting multiple sclerosis" in c["name"]
                                                 for c in d["children"])):
            return d["id"], d["name"]
    raise SystemExit("no Open Targets disease node for MS found")


def associations(did):
    rows, idx = [], 0
    q = '''query($id:String!,$i:Int!){ disease(efoId:$id){ associatedTargets(page:{index:$i,size:2000}){ count
           rows{ score target{ id approvedSymbol approvedName } datatypeScores{ id score } } } } }'''
    while True:
        a = gql(q, {"id": did, "i": idx})["disease"]["associatedTargets"]
        rows += a["rows"]
        idx += 1
        if len(rows) >= a["count"] or not a["rows"]:
            return rows


def target_drugs(ensembl_ids, cache):
    todo = [e for e in ensembl_ids if e not in cache]
    q = '''query($ids:[String!]!){ targets(ensemblIds:$ids){ id drugAndClinicalCandidates{ rows{ maxClinicalStage
           drug{ id name } } } } }'''
    for k in range(0, len(todo), 40):
        for t in gql(q, {"ids": todo[k:k + 40]})["targets"]:
            cache[t["id"]] = [{"chembl_id": r["drug"]["id"], "name": r["drug"]["name"], "stage": r["maxClinicalStage"]}
                              for r in (t["drugAndClinicalCandidates"] or {}).get("rows", [])]
        for e in todo[k:k + 40]:
            cache.setdefault(e, [])
    return cache


def drug_moa(chembl_ids, cache):
    key = lambda c: "drug:" + c
    todo = [c for c in chembl_ids if key(c) not in cache]
    q = '''query($ids:[String!]!){ drugs(chemblIds:$ids){ id parentMolecule{ id }
           mechanismsOfAction{ rows{ mechanismOfAction actionType targets{ id approvedSymbol } } } } }'''
    for k in range(0, len(todo), 50):
        got = {d["id"]: d for d in gql(q, {"ids": todo[k:k + 50]})["drugs"] if d}
        for c in todo[k:k + 50]:
            d = got.get(c)
            rows = ((d or {}).get("mechanismsOfAction") or {}).get("rows") or []
            cache[key(c)] = [{"ensembl_id": t["id"], "symbol": t["approvedSymbol"], "moa": r["mechanismOfAction"],
                              "action_type": r["actionType"]} for r in rows for t in r["targets"]]
    return {c: cache[key(c)] for c in chembl_ids}


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    did, dname = pick_disease()
    rows = associations(did)
    print(f"Open Targets {did} ({dname}): {len(rows)} associated targets")

    leads = []
    for r in rows:
        g = next((x["score"] for x in r["datatypeScores"] if x["id"] == "genetic_association"), 0.0)
        if g >= MIN_GENETIC_SCORE:
            leads.append({"ensembl_id": r["target"]["id"], "symbol": r["target"]["approvedSymbol"],
                          "name": r["target"]["approvedName"], "genetic_score": round(g, 3),
                          "overall_score": round(r["score"], 3)})
    leads = pd.DataFrame(leads)

    # bank drugs -> targets (Ensembl), through Open Targets' copy of ChEMBL mechanisms
    drugs = pd.read_parquet(DATA / "drugs.parquet")
    moa = drug_moa(sorted(drugs.chembl_id.dropna().unique()), cache)
    dt = pd.DataFrame([{"chembl_id": c, **m, "target_source": "Open Targets / ChEMBL"} for c, ms in moa.items()
                       for m in ms]).drop_duplicates()
    # newer MS drugs that ChEMBL has not yet annotated with a mechanism (gene symbols from the developers' labels)
    have = set(dt.chembl_id)
    extra = [{"chembl_id": r.chembl_id, "ensembl_id": None, "symbol": s, "moa": None, "action_type": None,
              "target_source": "MSFrontier rule list"}
             for r in drugs.itertuples() if r.chembl_id not in have for s in MOA_FALLBACK.get(r.drug_name, [])]
    dt = pd.concat([dt, pd.DataFrame(extra)], ignore_index=True)
    dt = dt.merge(drugs[["chembl_id", "drug_name"]], on="chembl_id", how="left")
    dt.to_parquet(DATA / "drug_targets.parquet", index=False)
    dt.to_csv(DATA / "drug_targets.csv", index=False)

    trials = pd.read_parquet(DATA / "trials.parquet")
    trials = trials[trials.study_type == "interventional"]
    trial_by_drug = {}
    for r in trials.itertuples():
        for c in (r.chembl_ids or "").split("|"):
            if c:
                trial_by_drug.setdefault(c, set()).add(r.msf_trial_id)
    phase_of = dict(zip(trials.msf_trial_id, trials.phase))

    target_drugs(list(leads.ensembl_id), cache)
    CACHE.write_text(json.dumps(cache))

    out = []
    for r in leads.itertuples():
        existing = cache.get(r.ensembl_id, [])
        bank_drugs = sorted(set(dt[(dt.ensembl_id == r.ensembl_id) | (dt.symbol == r.symbol)].chembl_id) |
                            {d["chembl_id"] for d in existing if d["chembl_id"] in trial_by_drug})
        tids = sorted(set().union(*[trial_by_drug.get(c, set()) for c in bank_drugs])) if bank_drugs else []
        names = sorted(set(dt[dt.chembl_id.isin(bank_drugs)].drug_name.dropna()) |
                       {d["name"].lower() for d in existing if d["chembl_id"] in bank_drugs})
        best = max((STAGE_RANK.get(d["stage"], 0) for d in existing), default=0)
        approved_elsewhere = sorted({d["name"].lower() for d in existing if d["stage"] in ("APPROVAL", "PHASE_4")})
        partners = PARTNERS.get(r.symbol, [])
        p_drugs = sorted(set(dt[dt.symbol.isin(partners)].chembl_id))
        p_tids = sorted(set().union(*[trial_by_drug.get(c, set()) for c in p_drugs])) if p_drugs else []
        p_names = sorted(set(dt[dt.chembl_id.isin(p_drugs) & dt.chembl_id.isin(list(trial_by_drug))].drug_name.dropna()))
        status = ("tested_in_ms_trials" if tids else
                  "pathway_tested_via_partner" if p_tids else
                  "drugs_exist_not_tested_in_ms" if existing else "no_drugs_yet")
        out.append({
            "ensembl_id": r.ensembl_id, "symbol": r.symbol, "name": r.name,
            "genetic_score": r.genetic_score, "overall_score": r.overall_score,
            "genetic_strength": "strong" if r.genetic_score >= 0.7 else "moderate" if r.genetic_score >= 0.5 else "weak",
            "lead_status": status,
            "n_existing_drugs": len(existing), "existing_drugs": [d["name"].lower() for d in existing][:15],
            "approved_drugs_any_disease": approved_elsewhere[:15],
            "max_stage_any_drug": next((k for k, v in STAGE_RANK.items() if v == best), None) if best else None,
            "bank_chembl_ids": bank_drugs, "bank_drug_names": names[:15],
            "n_ms_trials": len(tids), "ms_trial_ids": tids[:200],
            "max_ms_phase": max((phase_of.get(t) or "" for t in tids), default=None) or None,
            "partner_genes": partners, "partner_drug_names": p_names[:15], "n_ms_trials_via_partner": len(p_tids),
            "partner_trial_ids": p_tids[:200],
            "source": f"Open Targets Platform ({did}); genetic association score",
            "ot_url": f"https://platform.opentargets.org/evidence/{r.ensembl_id}/{did}",
            "as_of": date.today().isoformat(),
        })
    out = pd.DataFrame(out).sort_values("genetic_score", ascending=False)
    out.to_parquet(DATA / "genetic_leads.parquet", index=False)
    out.drop(columns=["ms_trial_ids", "partner_trial_ids"]).to_csv(DATA / "genetic_leads.csv", index=False)
    s = out[out.genetic_score >= 0.5].lead_status.value_counts().to_dict()
    print(f"genetic leads: {len(out)} (score >= 0.5: {s})")


if __name__ == "__main__":
    main()
