"""Warm the ChEMBL cache with drug-like intervention names from every registry (in-scope trials only)."""
import build
import chembl as C
import tags as T

trials, ids, ivs, *_ = build.load()
scope = {t["registry_id"] for t in trials if t["tier"]}
DRUGLIKE = {"drug", "biological", "combination_product", "dietary_supplement", "genetic"}
names = set()
for iv in ivs:
    if iv["registry_id"] in scope and iv["intervention_type"] in DRUGLIKE and not T.is_placebo(iv["name_raw"]):
        names.add(iv["name_raw"])
        names.update(o for o in (iv["other_names"] or "").split("; ") if o and not T.is_placebo(o))
for t in trials:
    if t["registry_id"] in scope:
        names.update(x for x in (t.get("mesh_interventions") or "").split("|") if x)
print("raw names", len(names))
C.resolve(names)
