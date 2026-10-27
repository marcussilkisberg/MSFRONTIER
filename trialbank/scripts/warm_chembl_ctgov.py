"""Warm the ChEMBL cache with drug-like intervention names from ClinicalTrials.gov tier 1/2 trials."""
import chembl as C
import parse_ctgov as P
import tags as T

trials, _, ivs, *_ = P.parse("../raw/ctgov_studies.jsonl")
scope = {t["registry_id"] for t in trials if t["tier"]}
DRUGLIKE = {"drug", "biological", "combination_product", "dietary_supplement", "genetic"}
names = set()
for iv in ivs:
    if iv["registry_id"] in scope and iv["intervention_type"] in DRUGLIKE and not T.is_placebo(iv["name_raw"]):
        names.add(iv["name_raw"])
        for o in (iv["other_names"] or "").split("; "):
            if o and not T.is_placebo(o):
                names.add(o)
for t in trials:
    if t["registry_id"] in scope:
        names.update(x for x in t["mesh_interventions"].split("|") if x)
print("raw names", len(names))
C.resolve(names)
