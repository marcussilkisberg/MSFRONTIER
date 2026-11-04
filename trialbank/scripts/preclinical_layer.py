"""Lab evidence: the preclinical layer.

Collects original research since 2015 that tests a treatment or a genetic change in an animal model of MS (EAE,
cuprizone, lysolecithin, Theiler's virus and others) or in human cell and organoid models, from Europe PMC. Each
paper is tagged by machine and linked to the bank's approaches, hypotheses, medicines and genes.

Tagging, per paper:
  1. Rules: the model system (EAE, cuprizone ...), the species, and whether the abstract reports randomisation or
     blinding are read from the abstract with fixed patterns. Medicines named in the text are matched to the bank's
     medicine list.
  2. A model reads the title and abstract and returns: whether it is an original study testing an intervention, the
     intervention names and type, target genes, aims, approach groups, timing of treatment, the direction of the
     main finding, the abstract sentence that states the conclusion, and a plain summary. Intervention names and gene
     symbols are kept only if they appear in the title or abstract, and the conclusion only if it appears word for
     word.
  3. Each intervention name is looked up in ChEMBL. Its mechanism and targets give approach groups by the same rules
     as the trials (mechanisms.py).

Lab evidence is context. It never changes a hypothesis's status, which stays set by trials (HYPOTHESES.md).

Outputs in ../data/:
  preclinical_studies.parquet   one row per paper
  preclinical_links.parquet     paper -> approach group, hypothesis, treatment, gene, frontier
  preclinical_ideas.parquet     one row per intervention, with whether it has reached trials in people
  preclinical_targets.parquet   one row per gene, with lab papers, trial medicines acting on it and human genetics
Caches (committed to the repository, so paid model calls are never repeated):
  ../readouts/preclinical_cache.json, ../readouts/preclinical_papers.json, ../readouts/preclinical_chembl.json

Environment: ANTHROPIC_API_KEY. Optional PRE_MODEL (default claude-haiku-5-5), PRE_MAX_NEW (default 8000 papers per
run), PRE_MAX_MINUTES (default 90: tagging stops after this and continues next run), PRE_WORKERS (default 4).
Usage: python preclinical_layer.py
"""
import json
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import requests

import literature_layer as lit
import mechanisms

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "readouts" / "preclinical_cache.json"
META = ROOT / "readouts" / "preclinical_papers.json"
CHEMBL_CACHE = ROOT / "readouts" / "preclinical_chembl.json"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"
MODEL = os.environ.get("PRE_MODEL") or "claude-haiku-5-5"
MAX_NEW = int(os.environ.get("PRE_MAX_NEW") or 8000)
MAX_MINUTES = float(os.environ.get("PRE_MAX_MINUTES") or 90)
WORKERS = int(os.environ.get("PRE_WORKERS") or 4)
VERSION = "pre_v1"

MODEL_TERMS = ('(TITLE_ABS:"experimental autoimmune encephalomyelitis" OR '
               'TITLE_ABS:"experimental allergic encephalomyelitis" OR TITLE_ABS:"cuprizone" OR '
               'TITLE_ABS:"lysolecithin" OR TITLE_ABS:"lysophosphatidylcholine-induced" OR TITLE_ABS:"Theiler" OR '
               'TITLE_ABS:"TMEV" OR (TITLE_ABS:"multiple sclerosis" AND (TITLE_ABS:"mouse model" OR '
               'TITLE_ABS:"animal model" OR TITLE_ABS:"rat model" OR TITLE_ABS:"organoid" OR TITLE_ABS:"organoids" OR '
               'TITLE_ABS:"induced pluripotent" OR TITLE_ABS:"iPSC")))')
QUERY = (f'{MODEL_TERMS} AND SRC:MED AND HAS_ABSTRACT:y AND NOT PUB_TYPE:"review" '
         f'AND PUB_YEAR:[2015 TO {date.today().year}]')

# fixed patterns, applied to title and abstract
SYSTEMS = [
    ("eae", r"experimental (autoimmune|allergic) encephalomyelitis|\beae\b"),
    ("cuprizone", r"cuprizone"),
    ("lysolecithin", r"lysolecithin|lysophosphatidylcholine|\blpc\b"),
    ("theiler_virus", r"theiler|\btmev\b"),
    ("other_toxin", r"ethidium bromide|kainate-induced demyelination"),
    ("human_cells", r"induced pluripotent|\bipscs?\b|organoids?|human (primary )?(oligodendrocyte|microglia|astrocyte|"
                    r"neuron|t cells|b cells|pbmc|peripheral blood mononuclear)|patient-derived|from (people|patients) "
                    r"with (multiple sclerosis|ms)"),
]
SPECIES = [("mouse", r"\bmice\b|\bmouse\b|murine"), ("rat", r"\brats?\b"), ("marmoset", r"marmoset"),
           ("other_primate", r"macaque|rhesus|non-human primate|nonhuman primate"), ("zebrafish", r"zebrafish"),
           ("human_cells", r"induced pluripotent|\bipscs?\b|organoid|human (primary )?[a-z]+ cells|patient-derived")]
SYSTEM_RX = [(k, re.compile(rx, re.I)) for k, rx in SYSTEMS]
SPECIES_RX = [(k, re.compile(rx, re.I)) for k, rx in SPECIES]
RANDOM_RX = re.compile(r"\brandomi[sz]", re.I)
BLIND_RX = re.compile(r"\bblind", re.I)

NAME_STOP = {"the", "and", "drug", "drugs", "treatment", "compound", "vehicle", "placebo", "control", "saline",
             "mice", "rats", "cells", "eae", "cuprizone", "knockout", "deficiency", "inhibitor", "antibody"}
STUDY_TYPES = ["intervention", "genetic", "mechanism_only", "review", "other"]
INTERVENTION_TYPES = ["small_molecule", "biologic", "cell_therapy", "gene_therapy", "genetic_change", "diet_microbiome",
                      "device_physical", "other"]
AIMS = {"stop_inflammation": "reduce inflammation, disease scores or immune attack",
        "slow_progression": "slow chronic or progressive disease",
        "protect_nerves": "protect nerve cells and axons",
        "repair": "repair myelin (remyelination)",
        "restore_function": "restore function or treat a symptom",
        "reset": "reset or retrain the immune system (tolerance)"}
DOSING = ["preventive", "after_onset", "both", "not_stated", "not_applicable"]
DIRECTIONS = ["benefit", "no_benefit", "mixed", "harm", "not_applicable"]
AIM_FRONTIER = {"stop_inflammation": "stopping-inflammation", "slow_progression": "why-ms-progresses",
                "protect_nerves": "repair-and-protection", "repair": "repair-and-protection",
                "restore_function": "symptoms-and-function", "reset": "resetting-the-immune-system"}
GROUP_LABELS = {i: lab for i, fam, lab, _ in mechanisms.NODES if fam != "diagnostic"}

PROMPT = """You tag laboratory research papers for MSFrontier, a database of multiple sclerosis research. Read the paper
below and return tags chosen ONLY from the lists given.

Title: {title}
Journal and year: {journal}, {year}
Abstract: {abstract}

Return one line of JSON with these keys:
- "relevant": true only if this is an original study (not a review) that uses an animal model of MS or
  demyelination, or human cells or organoids, to study MS
- "study_type": one of {study_types}. "intervention" if it tests a treatment (a drug, antibody, cells, diet, gene
  therapy or other) on the disease or on myelin repair. "genetic" if it tests what happens when a gene is removed,
  blocked or added in the animals. "mechanism_only" if it only describes the disease without testing a treatment or
  a genetic change
- "interventions": up to three names of the treatments or genes tested, copied exactly as written in the abstract,
  otherwise []
- "intervention_type": one of {itypes}
- "target_genes": up to three human gene symbols (for example BTK, CD40LG, LINGO1) that the treatment acts on or
  that were changed, only if the symbol or protein is named in the abstract, otherwise []
- "mechanism": at most eight plain words on how the treatment works, for example "blocks B-cell activation"
- "aims": list from {aims}
- "approach_groups": list from this list of id: label pairs, or [] if none fits:
{groups}
- "dosing": one of {dosing}. "preventive" if treatment started before the disease appeared, "after_onset" if after
  symptoms began, "not_applicable" for genetic studies
- "direction": one of {dirs}: "benefit" if the treatment or change improved the disease or repair on the main
  outcome, "no_benefit" if it did not, "mixed", "harm" if it made it worse, "not_applicable" for mechanism-only papers
- "conclusion": copy, word for word, the one sentence of the abstract that best states the main conclusion
- "summary": one plain-English sentence of at most 30 words on what was tested and found, naming the model (for
  example "in mice with EAE"), for a reader without medical training. No semicolons and no dashes.

Reply with the JSON only."""


def tag_one(p, groups_txt):
    prompt = PROMPT.format(title=p["title"], journal=p["journal"], year=p["pub_year"], abstract=p["abstract"][:6000],
                           study_types=STUDY_TYPES, itypes=INTERVENTION_TYPES, aims=list(AIMS), groups=groups_txt,
                           dosing=DOSING, dirs=DIRECTIONS)
    raw = lit.call(prompt, model=MODEL)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError(f"no JSON in reply: {raw[:160]!r}")
    j = json.loads(m.group(0))
    if "relevant" not in j or "study_type" not in j:
        raise RuntimeError(f"incomplete JSON: {raw[:160]!r}")
    return j


def validate(j, p):
    """Keep only values from the fixed lists, and only names, genes and a quote that appear in the paper."""
    pick = lambda v, allowed: [x for x in (v if isinstance(v, list) else []) if x in allowed]
    text = lit.norm(f"{p['title']} {p['abstract']}")
    ab = lit.norm(p["abstract"])
    names = [lit.clean(str(x))[:120] for x in (j.get("interventions") or []) if isinstance(x, str)]
    names = [n for n in names if len(n) >= 3 and n.lower() not in NAME_STOP
             and re.search(rf"(?<![a-z0-9]){re.escape(lit.norm(n))}(?![a-z0-9])", text)][:3]
    genes = []
    for g in (j.get("target_genes") or [])[:5]:
        g = re.sub(r"[^A-Za-z0-9-]", "", str(g)).upper()
        if 2 <= len(g) <= 12 and re.search(rf"\b{re.escape(g.lower())}\b", text):
            genes.append(g)
    quote = lit.clean(j.get("conclusion") or "")
    if not quote or lit.norm(quote) not in ab:
        quote = None
    clean_txt = lambda s, n: (re.sub(r"\s*[–—;]\s*", ", ", lit.clean(s or ""))[:n] or None)
    st = j.get("study_type") if j.get("study_type") in STUDY_TYPES else "other"
    return {"relevant": bool(j.get("relevant")) and st in ("intervention", "genetic"), "study_type": st,
            "interventions": names,
            "intervention_type": j.get("intervention_type") if j.get("intervention_type") in INTERVENTION_TYPES
            else "other",
            "target_genes": genes[:3], "mechanism": clean_txt(j.get("mechanism"), 80),
            "aims": pick(j.get("aims"), AIMS), "approach_groups_model": pick(j.get("approach_groups"), GROUP_LABELS),
            "dosing": j.get("dosing") if j.get("dosing") in DOSING else "not_stated",
            "direction": j.get("direction") if j.get("direction") in DIRECTIONS else "not_applicable",
            "conclusion_quote": quote, "summary": clean_txt(j.get("summary"), 300)}


def harvest():
    out, cursor = {}, "*"
    while True:
        for k in range(4):
            try:
                r = requests.get(lit.EPMC, timeout=120, params={"query": QUERY, "format": "json", "resultType": "core",
                                                                "pageSize": 1000, "cursorMark": cursor})
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:
                print(f"preclinical: Europe PMC attempt {k + 1} failed: {e}")
                time.sleep(20 * (k + 1))
        else:
            raise RuntimeError("Europe PMC unreachable")
        for x in d.get("resultList", {}).get("result", []):
            pmid = x.get("pmid")
            types = [t.lower() for t in (x.get("pubTypeList") or {}).get("pubType") or []]
            if not pmid or not x.get("abstractText") or any("review" in t for t in types):
                continue
            ji = x.get("journalInfo") or {}
            out[pmid] = {
                "pmid": pmid, "doi": x.get("doi"), "pmcid": x.get("pmcid"), "title": lit.clean(x.get("title")),
                "journal": (ji.get("journal") or {}).get("title") or (ji.get("journal") or {}).get("isoabbreviation"),
                "pub_year": int(x["pubYear"]) if str(x.get("pubYear", "")).isdigit() else None,
                "pub_date": x.get("firstPublicationDate"), "abstract": lit.clean(x.get("abstractText")),
                "cited_by": x.get("citedByCount"), "open_access": x.get("isOpenAccess") == "Y",
                "authors": (x.get("authorString") or "")[:300]}
        nxt = d.get("nextCursorMark")
        if not nxt or nxt == cursor or not d.get("resultList", {}).get("result"):
            break
        cursor = nxt
    print(f"preclinical: {len(out)} lab studies with abstracts from Europe PMC")
    return out


def chembl_get(path, params):
    for k in range(3):
        try:
            r = requests.get(f"{CHEMBL}/{path}.json", params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    return None


def chembl_lookup(name):
    """Exact ChEMBL name or synonym -> {chembl_id, pref_name, max_phase, mechanism text}, or None."""
    fields = "molecule_chembl_id,pref_name,max_phase,molecule_hierarchy"
    for key in ("pref_name__iexact", "molecule_synonyms__molecule_synonym__iexact"):
        d = chembl_get("molecule", {key: name, "only": fields})
        if d is None:
            raise RuntimeError("ChEMBL unreachable")
        mols = d.get("molecules") or []
        if mols:
            mols.sort(key=lambda m: -float(m.get("max_phase") or 0))
            m = mols[0]
            cid = (m.get("molecule_hierarchy") or {}).get("parent_chembl_id") or m["molecule_chembl_id"]
            mech = chembl_get("mechanism", {"molecule_chembl_id": cid, "only": "mechanism_of_action"}) or {}
            moa = "; ".join(sorted({x.get("mechanism_of_action") or "" for x in mech.get("mechanisms", [])}))
            return {"chembl_id": cid, "pref_name": (m.get("pref_name") or name).lower(),
                    "max_phase": m.get("max_phase"), "moa": moa}
    return None


# lab papers often name a treatment differently from trial registries
LAB_SYNONYMS = {"ivig": ["immunoglobulin", "ivig"], "msc": ["mesenchymal"], "mscs": ["mesenchymal"],
                "bm-mscs": ["mesenchymal"], "bm-msc": ["mesenchymal"], "vitd": ["vitamin d", "cholecalciferol"],
                "vitamin d": ["vitamin d", "cholecalciferol"], "vitamin d3": ["vitamin d", "cholecalciferol"],
                "calcitriol": ["calcitriol", "vitamin d"], "ursodiol": ["ursodeoxycholic", "ursodiol", "tudca"],
                "nadide": ["nicotinamide", "nad+"], "nad +": ["nicotinamide", "nad+"], "nad+": ["nicotinamide", "nad+"],
                "hscs": ["stem cell transplant", "hsct"], "tregs": ["regulatory t cell", "treg"]}
LAB_DISPLAY = {"ivig": "Intravenous immunoglobulin (IVIG)", "msc": "Mesenchymal stem cells",
               "mscs": "Mesenchymal stem cells", "bm-mscs": "Mesenchymal stem cells from bone marrow",
               "bm-msc": "Mesenchymal stem cells from bone marrow", "vitd": "Vitamin D", "nad +": "NAD+",
               "nad+": "NAD+", "nadide": "NAD+ (nadide)", "tregs": "Regulatory T cells"}


def display_name(n):
    """How an intervention from a lab paper is shown: codes in capitals (MCC950, PLX-5622), names with a capital."""
    n = str(n).strip()
    if n.lower() in LAB_DISPLAY:
        return LAB_DISPLAY[n.lower()]
    if re.fullmatch(r"[a-z]{1,6}[- ]?\d[\w-]*", n, flags=re.I):
        return n.upper()
    return n[:1].upper() + n[1:]


def base_name(n):
    """'cannabidiol (CBD)' -> 'cannabidiol', 'Ketogenic Diet (KD)' -> 'ketogenic diet'."""
    n = re.sub(r"\s+", " ", re.sub(r"\s*\([^)]*\)\s*", " ", str(n))).strip().lower()
    for g, w in (("β", "beta"), ("α", "alpha"), ("γ", "gamma"), ("κ", "kappa")):
        n = n.replace(g, w)
    return re.sub(r"^ifn[- ]?(beta|alpha|gamma)", r"interferon \1", n)


def resolve_names(names, deadline):
    cache = json.loads(CHEMBL_CACHE.read_text()) if CHEMBL_CACHE.exists() else {}
    todo = sorted(({n.lower() for n in names} | {base_name(n) for n in names}) - set(cache) - {""})
    print(f"preclinical: {len(todo)} new intervention names to look up in ChEMBL")

    def one(n):
        if time.time() > deadline:   # time budget: names not looked up now are tried next run
            return n, "error"
        try:
            return n, chembl_lookup(n)
        except Exception:
            return n, "error"

    with ThreadPoolExecutor(6) as ex:
        for n, m in ex.map(one, todo):
            if m != "error":
                cache[n] = m
    CHEMBL_CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    return cache


def main():
    t0 = time.time()
    hyp = pd.read_parquet(DATA / "hypotheses.parquet")
    groups_txt = "\n".join(f"  {g}: {l}" for g, l in GROUP_LABELS.items())

    meta = json.loads(META.read_text()) if META.exists() else {}
    harvested = True
    try:
        papers = harvest()
    except Exception as e:
        harvested = False
        print(f"preclinical: Europe PMC failed ({e}), using the saved list of {len(meta)} papers without new ones")
        papers = {k: {**v, "abstract": v.get("abstract_start", "")} for k, v in meta.items()}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [p for k, p in sorted(papers.items(), key=lambda kv: -(kv[1].get("pub_year") or 0))
            if (cache.get(k) or {}).get("version") != VERSION][:MAX_NEW] if harvested else []
    print(f"preclinical: {len(todo)} papers to tag with {MODEL}, newest first, for at most {MAX_MINUTES:.0f} minutes")
    deadline = t0 + MAX_MINUTES * 60
    done, failed, stopped = 0, 0, False
    CACHE.parent.mkdir(exist_ok=True)
    if todo and not os.environ.get("ANTHROPIC_API_KEY"):
        print("preclinical: no ANTHROPIC_API_KEY, nothing new is tagged this run")
        todo = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        it = iter(todo)
        futs = {}
        def submit_next():
            p = next(it, None)
            if p is not None:
                futs[ex.submit(tag_one, p, groups_txt)] = p
        for _ in range(WORKERS * 2):
            submit_next()
        while futs:
            f = next(as_completed(futs))
            p = futs.pop(f)
            try:
                cache[p["pmid"]] = {"version": VERSION, "model": MODEL, "tagged_on": date.today().isoformat(),
                                    **validate(f.result(), p)}
            except Exception as e:
                failed += 1
                if failed <= 10:
                    print(f"preclinical: {p['pmid']} not tagged: {e}")
            done += 1
            if done % 250 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False))
                print(f"preclinical: {done} tagged ({(time.time() - t0) / 60:.0f} min)")
            if time.time() < deadline:
                submit_next()
            elif not stopped:
                stopped = True
                print("preclinical: time budget reached, the rest are tagged next run")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))
    print(f"preclinical: {done - failed} tagged, {failed} failed, "
          f"{sum(1 for k in papers if (cache.get(k) or {}).get('version') != VERSION)} still to tag")
    too_many_failed = done > 20 and failed > 0.5 * done

    if harvested and papers:
        META.write_text(json.dumps({k: {**{x: v.get(x) for x in ("pmid", "doi", "pmcid", "title", "journal",
                                                                   "pub_year", "pub_date", "cited_by", "open_access",
                                                                   "authors")},
                                        "abstract_start": (v.get("abstract") or "")[:800]}
                                    for k, v in papers.items()}, ensure_ascii=False))

    kept = {k: c for k, c in cache.items() if k in papers and c.get("version") == VERSION and c.get("relevant")}
    names = {n for c in kept.values() if c["intervention_type"] not in ("genetic_change", "device_physical")
             for n in c["interventions"]}
    chembl = resolve_names(names, time.time() + 10 * 60)
    rx, bank_names = lit.drug_matcher()
    bank_chembl = set(pd.read_parquet(DATA / "drugs.parquet").chembl_id) if (DATA / "drugs.parquet").exists() else set()
    bank_by_chembl = {v[0]: v[1] for v in bank_names.values()}
    dt = pd.read_parquet(DATA / "drug_targets.parquet") if (DATA / "drug_targets.parquet").exists() \
        else pd.DataFrame(columns=["chembl_id", "symbol", "drug_name"])
    gl = pd.read_parquet(DATA / "genetic_leads.parquet") if (DATA / "genetic_leads.parquet").exists() \
        else pd.DataFrame(columns=["symbol", "genetic_strength"])
    gene_strength = dict(zip(gl.symbol, gl.genetic_strength))
    trial_drugs_by_gene = defaultdict(set)
    for r in dt.itertuples():
        if r.chembl_id in bank_chembl:
            trial_drugs_by_gene[r.symbol].add(r.drug_name)
    genes_by_chembl = defaultdict(set)
    for r in dt.itertuples():
        genes_by_chembl[r.chembl_id].add(r.symbol)

    rows, links = [], []
    for k, c in kept.items():
        p = papers[k]
        text = f"{p['title']} {p['abstract']}"
        systems = [s for s, r_ in SYSTEM_RX if r_.search(text)] or ["other_animal"]
        species = [s for s, r_ in SPECIES_RX if r_.search(text)]
        resolved = []
        for n in c["interventions"]:
            m = chembl.get(n.lower())
            if m:
                resolved.append(m)
        bank_drugs = {}
        if rx and c["study_type"] == "intervention":
            for m_ in rx.finditer(text):
                ch, base, nodes = bank_names[m_.group(1).lower()]
                bank_drugs[ch] = base
        for m in resolved:
            if m["chembl_id"] in bank_chembl:
                bank_drugs[m["chembl_id"]] = bank_by_chembl.get(m["chembl_id"], m["pref_name"])
        mech_text = " ".join([*c["interventions"], *(m["moa"] for m in resolved), *c["target_genes"],
                              c["mechanism"] or ""])
        rule_groups = {g for g, _ in mechanisms.assign(mech_text) if g in GROUP_LABELS}
        groups = sorted(set(c["approach_groups_model"]) | rule_groups)
        genes = sorted(set(c["target_genes"]) | {g for m in resolved for g in genes_by_chembl.get(m["chembl_id"], ())})
        frontiers = sorted({AIM_FRONTIER[a] for a in c["aims"]})
        in_trials = bool(bank_drugs)
        rows.append({**{x: p.get(x) for x in ("pmid", "doi", "pmcid", "title", "journal", "pub_year", "pub_date",
                                               "cited_by", "open_access", "authors")},
                     "study_type": c["study_type"], "model_systems": "|".join(systems),
                     "species": "|".join(species), "interventions": "|".join(c["interventions"]),
                     "intervention_type": c["intervention_type"],
                     "chembl_ids": "|".join(sorted({m["chembl_id"] for m in resolved})),
                     "target_genes": "|".join(genes), "mechanism": c["mechanism"], "aims": "|".join(c["aims"]),
                     "approach_groups": "|".join(groups), "frontiers": "|".join(frontiers), "dosing": c["dosing"],
                     "direction": c["direction"], "randomised_reported": bool(RANDOM_RX.search(p["abstract"])),
                     "blinded_reported": bool(BLIND_RX.search(p["abstract"])),
                     "in_human_trials": in_trials, "trial_drugs": "|".join(sorted(set(bank_drugs.values()))),
                     "conclusion_quote": c["conclusion_quote"], "summary": c["summary"],
                     "url": f"https://europepmc.org/article/MED/{k}", "tagged_by": c.get("model"),
                     "tags_version": VERSION})
        for g in groups:
            links.append((k, "approach_group", g, "model_or_mechanism_rule"))
        for f_ in frontiers:
            links.append((k, "frontier", f_, "aim"))
        for ch in bank_drugs:
            links.append((k, "treatment", ch, "name_in_text_or_chembl"))
        for g in genes:
            links.append((k, "gene", g, "named_in_abstract_or_chembl_target"))
        # hypotheses: same approach group and aim, any population (animals have no type of MS). A hypothesis about
        # one medicine (approach "group.medicine") needs that medicine.
        drug_slugs = {b.replace(" ", "-") for b in bank_drugs.values()}
        for h in ([] if c["study_type"] != "intervention" else hyp[hyp.approach_group.isin(groups) & hyp.aim.isin(c["aims"])].itertuples()):
            if "." in h.approach and h.approach.split(".", 1)[1] not in drug_slugs:
                continue
            links.append((k, "hypothesis", h.hypothesis_id, "approach_group_and_aim"))

    df = pd.DataFrame(rows)
    ln = pd.DataFrame(links, columns=["pmid", "target_type", "target_id", "rule"]).drop_duplicates()

    # interventions as registered in the trials (covers diets and medicines ChEMBL does not name the same way)
    registered_text = ""
    if (DATA / "trials.parquet").exists():
        tt = pd.read_parquet(DATA / "trials.parquet", columns=["interventions_raw"])
        registered_text = " | ".join(str(v).lower() for v in tt.interventions_raw.dropna())
    registered_rx = lambda nm: re.compile(rf"(?<![a-z0-9]){re.escape(nm)}(?![a-z0-9])")

    # one row per intervention (medicines, antibodies, cells, diets): the "ideas" tested in the lab
    ideas = defaultdict(lambda: {"pmids": set(), "benefit": 0, "no_benefit": 0, "mixed": 0, "harm": 0,
                                 "systems": set(), "groups": set(), "aims": set(), "genes": set(), "years": [],
                                 "after_onset": 0, "names": set(), "trial_drugs": set(), "chembl_id": None,
                                 "type": None, "mechanism": None})
    for r in df[df.study_type == "intervention"].itertuples() if len(df) else []:
        c = kept[r.pmid]
        for n in c["interventions"]:
            m = chembl.get(n.lower()) or chembl.get(base_name(n))
            key = m["chembl_id"] if m else base_name(n)
            x = ideas[key]
            x["pmids"].add(r.pmid)
            x["names"].add(m["pref_name"] if m else base_name(n))
            x["chembl_id"] = m["chembl_id"] if m else None
            x["type"] = x["type"] or r.intervention_type
            x["mechanism"] = x["mechanism"] or r.mechanism
            if r.direction in ("benefit", "no_benefit", "mixed", "harm"):
                x[r.direction] += 1
            x["after_onset"] += r.dosing in ("after_onset", "both")
            x["systems"] |= set(r.model_systems.split("|"))
            x["groups"] |= set(filter(None, r.approach_groups.split("|")))
            x["aims"] |= set(filter(None, r.aims.split("|")))
            x["genes"] |= set(filter(None, r.target_genes.split("|")))
            x["years"].append(r.pub_year)
            if m and m["chembl_id"] in bank_chembl:
                x["trial_drugs"].add(bank_by_chembl.get(m["chembl_id"], m["pref_name"]))
            elif base_name(n) in bank_names:
                x["trial_drugs"].add(bank_names[base_name(n)][1])
            elif len(base_name(n)) >= 6 and registered_rx(base_name(n)).search(registered_text):
                x["trial_drugs"].add(base_name(n))   # named as an intervention in a registered trial (diets, devices)
            else:
                for syn in LAB_SYNONYMS.get(base_name(n), []):
                    if registered_rx(syn).search(registered_text):
                        x["trial_drugs"].add(syn)   # a synonym is registered (IVIG as immunoglobulin, MSCs as mesenchymal)
                        break
    # what trials in people found for the same medicine: hypotheses whose approach group is one of the medicine's
    # own mechanism groups (so a background or comparator medicine in the same trials is never credited)
    drug_nodes = {}
    if (DATA / "drugs.parquet").exists():
        for r in pd.read_parquet(DATA / "drugs.parquet").itertuples():
            v = r.mechanism_nodes
            drug_nodes[str(r.drug_name).lower()] = set(v.split("|") if isinstance(v, str) else (list(v) if v is not None else []))
    outcome_by_drug = defaultdict(set)
    for h in hyp.itertuples():
        ds = h.drugs if h.drugs is not None and not isinstance(h.drugs, str) else str(h.drugs or "").split("|")
        for d_ in ds:
            d_ = str(d_).strip().lower()
            if "." in h.approach and h.approach.split(".", 1)[1] != d_.replace(" ", "-"):
                continue   # a hypothesis about one named medicine counts only for that medicine
            if d_ and h.approach_group in drug_nodes.get(d_, set()):
                outcome_by_drug[d_].add(f"{h.approach_label} in {h.population_label}: {h.outcome_label}")
    idea_rows = []
    for key, x in ideas.items():
        nm = sorted(x["names"], key=len)[0]
        trial = sorted(x["trial_drugs"])
        idea_rows.append({
            "idea_id": key, "name": display_name(nm), "chembl_id": x["chembl_id"], "intervention_type": x["type"],
            "mechanism": x["mechanism"], "n_papers": len(x["pmids"]), "n_benefit": x["benefit"],
            "n_no_benefit": x["no_benefit"], "n_mixed": x["mixed"], "n_harm": x["harm"],
            "n_after_onset": x["after_onset"], "model_systems": "|".join(sorted(x["systems"])),
            "approach_groups": "|".join(sorted(x["groups"])), "aims": "|".join(sorted(x["aims"])),
            "target_genes": "|".join(sorted(x["genes"])),
            "genetic_support": "|".join(sorted(g for g in x["genes"] if gene_strength.get(g) in ("strong", "moderate"))),
            "first_year": min(y for y in x["years"] if y) if any(x["years"]) else None,
            "latest_year": max(y for y in x["years"] if y) if any(x["years"]) else None,
            "in_human_trials": bool(trial), "trial_drugs": "|".join(trial),
            "human_outcomes": " · ".join(sorted({o for t in trial for o in outcome_by_drug.get(t, ())}))[:600],
            "pmids": "|".join(sorted(x["pmids"]))})
    ideas_df = pd.DataFrame(idea_rows)

    # one row per gene
    tg = defaultdict(lambda: {"pmids": set(), "benefit": 0, "genetic": 0})
    for r in df.itertuples() if len(df) else []:
        for g in filter(None, r.target_genes.split("|")):
            tg[g]["pmids"].add(r.pmid)
            tg[g]["benefit"] += r.direction == "benefit"
            tg[g]["genetic"] += r.study_type == "genetic"
    targets_df = pd.DataFrame([{
        "symbol": g, "n_papers": len(x["pmids"]), "n_benefit": x["benefit"], "n_genetic_studies": x["genetic"],
        "trial_drugs": "|".join(sorted(trial_drugs_by_gene.get(g, ()))),
        "in_human_trials": bool(trial_drugs_by_gene.get(g)),
        "human_genetics": gene_strength.get(g), "pmids": "|".join(sorted(x["pmids"]))} for g, x in tg.items()])

    for name, d_ in (("preclinical_studies", df), ("preclinical_links", ln), ("preclinical_ideas", ideas_df),
                     ("preclinical_targets", targets_df)):
        d_.to_parquet(DATA / f"{name}.parquet", index=False)
    print(f"preclinical: {len(df)} lab studies kept, {len(ln)} links "
          f"({ln.target_type.value_counts().to_dict() if len(ln) else {}})")
    if len(df):
        print("preclinical: study types", df.study_type.value_counts().to_dict(),
              "| directions", df.direction.value_counts().to_dict())
        print(f"preclinical: {len(ideas_df)} interventions, {int(ideas_df.in_human_trials.sum()) if len(ideas_df) else 0}"
              f" reached trials in people, {len(targets_df)} genes")
    if too_many_failed:
        raise SystemExit("preclinical: more than half the papers failed to tag, see the messages above")


if __name__ == "__main__":
    main()
