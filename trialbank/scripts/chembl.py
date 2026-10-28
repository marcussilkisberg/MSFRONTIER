"""Normalise intervention names to ChEMBL molecules, with mechanisms, targets and ATC classes.

Results are cached in raw/chembl_cache.json so reruns only look up new names.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = "https://www.ebi.ac.uk/chembl/api/data"
CACHE = Path(__file__).resolve().parent.parent / "raw" / "chembl_cache.json"
_lock = threading.Lock()
_session = requests.Session()

DOSE = re.compile(r"\b\d+(\.\d+)?\s*(mg|µg|ug|mcg|g|ml|iu|units?|%|mg/kg|mg/m2|mmol|kg)\b(/\w+)?", re.I)
NOISE = re.compile(
    r"\b(tablets?|capsules?|oral|injections?|infusions?|intravenous(ly)?|iv|sc|subcutaneous(ly)?|intramuscular(ly)?|im|"
    r"extended[- ]release|delayed[- ]release|prolonged[- ]release|film[- ]coated|solution|suspension|powder|"
    r"pre-?filled syringe|auto-?injector|pen|daily|weekly|monthly|once|twice|dose|doses|dosing|high|low|"
    r"treatment|therapy|arm|group|cohort|part [a-z0-9]|regimen|drug|study|active|open[- ]label|"
    r"formulation|generic|biosimilar|tiw|qd|bid|tid|qod|q\d+w|days?|weeks?|months?|every|per|"
    r"\bfor\b|\bof\b|\bwith\b|\bthe\b|and\s*$)\b", re.I)


ALIASES = [
    (r"interferon[- ]?beta[- ]?-?(1a|1b)|ifn[- ]?(?:beta|b)[- ]?(1a|1b)", lambda m: "interferon beta-" + (m.group(1) or m.group(2)).lower()),
    (r"(alpha[- ])?lipoic acid|\bala\b", "thioctic acid"),
    (r"n-?acetyl[- ]?cysteine|\bnac\b", "acetylcysteine"),
    (r"botulinum toxin( type)? a|onabotulinum|botox", "onabotulinumtoxina"),
    (r"fingolimodi", "fingolimod"), (r"\bivmp\b|iv methylprednisolone", "methylprednisolone"),
    (r"\bratg\b|anti-?thymocyte", "anti-thymocyte globulin (rabbit)"), (r"aclasta", "zoledronic acid"),
    (r"ceterizine", "cetirizine"), (r"3,4-diaminopyridine", "amifampridine"), (r"fampridine[- ]?sr", "fampridine"),
    (r"vitamin d3?\b", "cholecalciferol"), (r"\bdmf\b", "dimethyl fumarate"), (r"\bthc\b", "dronabinol"),
    (r"\bcbd\b", "cannabidiol"), (r"\bivig\b|intravenous immunoglobulin", "immune globulin"),
    (r"epigallocatechin|sunphenon|\begcg\b", "epigallocatechin gallate"), (r"daclizumab", "daclizumab"),
    (r"mitoxantrone", "mitoxantrone"), (r"teriflunomide", "teriflunomide"), (r"alemtuzumab", "alemtuzumab"),
    (r"vidofludimus", "vidofludimus"), (r"^glatiramer$", "glatiramer acetate"), (r"ceralifimod|ono-4641", "ceralifimod"),
]


SALT = re.compile(r"\b(?:hemi|mono|di|tri|sesqui)?hydrate\b|\banhydrous\b|\b(?:hydrochloride|dihydrochloride|"
                  r"hydrobromide|sulfate|sulphate|phosphate|maleate|tartrate|citrate|mesylate|"
                  r"besylate|sodium|potassium|calcium|magnesium)\b", re.I)


def _aliases(raw):
    out = []
    for rx, rep in ALIASES:
        m = re.search(rx, raw, re.I)
        if m:
            out.append(rep(m) if callable(rep) else rep)
    return out


def clean_name(raw):
    """Return candidate lookup strings for a raw intervention name, most specific first."""
    if not raw:
        return []
    out = []
    parens = re.findall(r"\(([^)]{3,60})\)", raw)
    base = re.sub(r"\([^)]*\)", " ", raw)
    whole = re.sub(r"\s+", " ", re.sub(r"[®™]", "", raw)).strip().lower()
    if 3 <= len(whole) <= 60:
        out.append(whole)
    for s in [base, *parens]:
        for part in re.split(r"\s*(?:\+|/|,|;|\bplus\b|\band\b|\bvs\.?\b|\bor\b)\s*", s, flags=re.I):
            p = DOSE.sub(" ", part)
            p = NOISE.sub(" ", p)
            p = re.sub(r"[®™]", "", p)
            p = re.sub(r"[^\w\s\-]", " ", p)
            p = re.sub(r"\s+", " ", p).strip(" -").lower()
            if len(p) >= 3 and not re.fullmatch(r"[\d\s\-]+", p) and p not in out:
                out.append(p)
    # EU registries give substances with their salt or hydrate ("INDAPAMIDE HEMIHYDRATE"): also try the bare name
    for p in list(out):
        bare = SALT.sub(" ", p)
        bare = re.sub(r"\s+", " ", bare).strip()
        if len(bare) >= 4 and bare != p and bare not in out:
            out.append(bare)
    for a in _aliases(raw):
        if a not in out:
            out.append(a)
    return out


def _get(path, params):
    for attempt in range(4):
        try:
            r = _session.get(f"{API}/{path}.json", params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
    return None


def lookup_molecule(name):
    """Exact synonym or preferred-name match; returns the parent molecule record or None."""
    fields = "molecule_chembl_id,pref_name,molecule_type,max_phase,atc_classifications,molecule_hierarchy"
    for key in ("pref_name__iexact", "molecule_synonyms__molecule_synonym__iexact"):
        d = _get("molecule", {key: name, "only": fields})
        if d and d.get("molecules"):
            mols = d["molecules"]
            # prefer the parent / highest phase record
            mols.sort(key=lambda m: -(float(m.get("max_phase") or 0)))
            m = mols[0]
            parent = (m.get("molecule_hierarchy") or {}).get("parent_chembl_id")
            if parent and parent != m["molecule_chembl_id"]:
                d2 = _get("molecule", {"molecule_chembl_id": parent, "only": fields})
                if d2 and d2.get("molecules"):
                    m = d2["molecules"][0]
            return {k: m.get(k) for k in ("molecule_chembl_id", "pref_name", "molecule_type", "max_phase", "atc_classifications")}
    return None


def mechanisms(chembl_id):
    d = _get("mechanism", {"molecule_chembl_id": chembl_id, "only": "mechanism_of_action,action_type,target_chembl_id"})
    return d.get("mechanisms", []) if d else []


def target_names(target_ids):
    out = {}
    ids = [t for t in target_ids if t]
    for i in range(0, len(ids), 40):
        d = _get("target", {"target_chembl_id__in": ",".join(ids[i:i + 40]), "only": "target_chembl_id,pref_name,target_type", "limit": 1000})
        for t in (d or {}).get("targets", []):
            out[t["target_chembl_id"]] = t["pref_name"]
    return out


def atc_names(codes):
    out = {}
    codes = sorted({c for c in codes if c})
    for i in range(0, len(codes), 40):
        d = _get("atc_class", {"level5__in": ",".join(codes[i:i + 40]), "limit": 1000})
        for a in (d or {}).get("atc", []):
            out[a["level5"]] = {"level5": a.get("who_name"), "level3": a.get("level3_description"),
                                "level2": a.get("level2_description"), "level1": a.get("level1_description")}
    return out


def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {"names": {}, "mech": {}, "targets": {}, "atc": {}}


def save_cache(c):
    CACHE.write_text(json.dumps(c))


def resolve(names, workers=6):
    """Map each raw name -> molecule dict (or None). Fills mechanism/target/ATC caches."""
    cache = load_cache()
    todo = sorted({n for raw in names for n in clean_name(raw)} - set(cache["names"]))
    print(f"chembl: {len(todo)} new lookup strings")

    def one(n):
        m = lookup_molecule(n)
        with _lock:
            cache["names"][n] = m

    with ThreadPoolExecutor(workers) as ex:
        for i, _ in enumerate(ex.map(one, todo)):
            if i and i % 250 == 0:
                print(f"  {i}/{len(todo)}")
                with _lock:
                    save_cache(cache)
    save_cache(cache)

    mol_ids = sorted({m["molecule_chembl_id"] for m in cache["names"].values() if m} - set(cache["mech"]))
    print(f"chembl: {len(mol_ids)} molecules need mechanisms")

    def mech(cid):
        r = mechanisms(cid)
        with _lock:
            cache["mech"][cid] = r

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(mech, mol_ids))
    save_cache(cache)
    tids = {x["target_chembl_id"] for ms in cache["mech"].values() for x in ms if x.get("target_chembl_id")} - set(cache["targets"])
    cache["targets"].update(target_names(sorted(tids)))
    codes = {c for m in cache["names"].values() if m for c in (m.get("atc_classifications") or [])} - set(cache["atc"])
    cache["atc"].update(atc_names(sorted(codes)))
    save_cache(cache)
    return cache


def best_match(raw, cache):
    """First candidate string for this raw name that resolved to a molecule."""
    for n in clean_name(raw):
        m = cache["names"].get(n)
        if m:
            return n, m
    return None, None
