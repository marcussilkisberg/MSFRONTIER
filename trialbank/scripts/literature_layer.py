"""Reviews and guidelines: the literature layer.

Collects every systematic review, meta-analysis and clinical guideline on MS, NMOSD and MOGAD published since 2015
from Europe PMC, tags each one by machine, and links it to the bank's medicines, hypotheses, frontiers and trials.

Tagging, per paper:
  1. Rules: medicines named in the title or abstract are matched to the bank's medicine list, and their mechanism
     group becomes an approach. Registry numbers in the abstract link the paper to trials.
  2. A model reads the title and abstract and returns fixed-list tags (kind, populations, topics, aims, approach
     groups, frontiers), the direction of the main finding for treatment reviews, and the sentence of the abstract
     that states the main conclusion. The sentence is kept only if it appears word for word in the abstract, and the
     number of included studies only if that number appears in the abstract.
  Papers the model judges not to be mainly about MS, NMOSD or MOGAD, or not to be a review or guideline, are dropped.

Reviews are context. They never change a hypothesis's status, which stays set by trials (HYPOTHESES.md).

Outputs ../data/papers.parquet and ../data/paper_links.parquet.
Cache: ../readouts/literature_cache.json (committed to the repository: paid model calls are never repeated).

Environment: ANTHROPIC_API_KEY. Optional LIT_MODEL (default claude-haiku-5-5), LIT_MAX_NEW (default 3000 papers
tagged per run), LIT_WORKERS (default 6).
Usage: python literature_layer.py
"""
import html as htmllib
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "readouts" / "literature_cache.json"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("LIT_MODEL") or "claude-haiku-5-5"
MAX_NEW = int(os.environ.get("LIT_MAX_NEW") or 3000)
WORKERS = int(os.environ.get("LIT_WORKERS") or 6)
VERSION = "lit_v1"

DISEASE = ('(TITLE:"multiple sclerosis" OR TITLE:"neuromyelitis" OR TITLE:"NMOSD" OR TITLE:"MOGAD" OR '
           'TITLE:"MOG antibody" OR TITLE:"MOG-antibody" OR TITLE:"myelin oligodendrocyte glycoprotein antibody" OR '
           'TITLE:"demyelinating")')
TYPES = ('(PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Systematic Review" OR PUB_TYPE:"systematic-review" OR '
         'PUB_TYPE:"Practice Guideline" OR PUB_TYPE:"Guideline" OR TITLE:"systematic review" OR '
         'TITLE:"meta-analysis" OR TITLE:"meta-analyses" OR TITLE:"umbrella review" OR TITLE:"guideline" OR '
         'TITLE:"guidelines" OR TITLE:"consensus")')
QUERY = f"{DISEASE} AND {TYPES} AND PUB_YEAR:[2015 TO {date.today().year}] AND SRC:MED"

FRONTIERS = {
    "what-starts-ms": "What starts MS: causes, risk factors, EBV, genetics, prevention",
    "stopping-inflammation": "Stopping inflammation: relapses and new lesions, disease-modifying treatments",
    "why-ms-progresses": "Why MS progresses: progressive MS, PIRA, smouldering inflammation, neurodegeneration",
    "repair-and-protection": "Repair and protection: remyelination, neuroprotection, rehabilitation, restoring function",
    "resetting-the-immune-system": "Resetting the immune system: stem-cell transplant, cladribine, alemtuzumab, CAR-T, tolerance",
    "measuring-ms": "Measuring MS: diagnosis, MRI, biomarkers, outcome measures, prognosis",
    "nmosd-and-mogad": "NMOSD and MOGAD",
}
POPULATIONS = ["any_ms", "relapsing", "progressive", "spms", "ppms", "early_cis_ris", "paediatric", "optic_neuritis",
               "nmosd", "mogad"]
TOPICS = ["treatment_effect", "treatment_safety", "diagnosis", "prognosis", "biomarkers_imaging", "causes_risk",
          "epidemiology", "pathology_mechanism", "symptoms_rehabilitation", "pregnancy_family", "other"]
AIMS = {"prevent": "prevent or delay MS", "stop_inflammation": "reduce relapses and new lesions",
        "slow_progression": "slow disability progression", "protect_nerves": "protect nerve cells and axons",
        "repair": "repair myelin", "restore_function": "restore function or treat symptoms",
        "reset": "reset the immune system"}
KINDS = ["meta_analysis", "systematic_review", "umbrella_review", "guideline", "consensus", "other"]
DIRECTIONS = ["benefit", "no_benefit", "mixed", "harm", "uncertain", "not_applicable"]

PROMPT = """You tag scientific papers for MSFrontier, a database of multiple sclerosis research. Read the paper below
and return tags chosen ONLY from the lists given.

Title: {title}
Journal and year: {journal}, {year}
Publication types: {pubtypes}
Abstract: {abstract}

Return one line of JSON with these keys:
- "relevant": true if the paper is mainly about multiple sclerosis, NMOSD or MOGAD, otherwise false
- "kind": one of {kinds}. Use "other" if it is not a systematic review, meta-analysis, umbrella review, clinical
  guideline or consensus statement (for example a single study or a narrative review)
- "populations": list from {pops}. "any_ms" if it covers MS in general
- "topics": list from {topics}
- "aims": for papers about treatments only, list from {aims}, otherwise []
- "approach_groups": for papers about treatments only, list from this list of id: label pairs, otherwise []:
{groups}
- "frontiers": list of one to three ids from:
{frontiers}
- "direction": for papers that pool the effect of a treatment, one of {dirs}: "benefit" if the treatment helped on the
  main outcome, "no_benefit" if it did not, "mixed", "harm", or "uncertain" if the evidence was too weak to say.
  Otherwise "not_applicable"
- "conclusion": copy, word for word, the one sentence of the abstract that best states the main conclusion
- "n_studies": the number of included studies if the abstract states it, else null
- "summary": one plain-English sentence of at most 30 words on what the paper found, for a reader without medical
  training. No semicolons and no dashes.

Reply with the JSON only."""


TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")


def clean(text):
    return re.sub(r"\s+", " ", htmllib.unescape(TAG.sub(" ", text or ""))).strip()


def norm(s):
    s = unicodedata.normalize("NFKC", clean(s)).lower()
    s = re.sub(r"[‐-―−]", "-", s)
    return re.sub(r"\s+", " ", s).strip()


def harvest():
    out, cursor = {}, "*"
    while True:
        for k in range(4):
            try:
                r = requests.get(EPMC, timeout=120, params={"query": QUERY, "format": "json", "resultType": "core",
                                                            "pageSize": 1000, "cursorMark": cursor})
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:   # Europe PMC sometimes times out
                print(f"literature: Europe PMC attempt {k + 1} failed: {e}")
                time.sleep(20 * (k + 1))
        else:
            raise RuntimeError("Europe PMC unreachable")
        for x in d.get("resultList", {}).get("result", []):
            pmid = x.get("pmid")
            if not pmid or not x.get("abstractText"):
                continue
            ji = x.get("journalInfo") or {}
            out[pmid] = {
                "pmid": pmid, "doi": x.get("doi"), "pmcid": x.get("pmcid"), "title": clean(x.get("title")),
                "journal": (ji.get("journal") or {}).get("title") or (ji.get("journal") or {}).get("isoabbreviation"),
                "pub_year": int(x["pubYear"]) if str(x.get("pubYear", "")).isdigit() else None,
                "pub_date": x.get("firstPublicationDate"), "abstract": clean(x.get("abstractText")),
                "pub_types": (x.get("pubTypeList") or {}).get("pubType") or [],
                "cited_by": x.get("citedByCount"), "open_access": x.get("isOpenAccess") == "Y",
                "authors": (x.get("authorString") or "")[:300]}
        nxt = d.get("nextCursorMark")
        if not nxt or nxt == cursor or not d.get("resultList", {}).get("result"):
            break
        cursor = nxt
    print(f"literature: {len(out)} reviews and guidelines with abstracts from Europe PMC")
    return out


def call(prompt):
    key = os.environ["ANTHROPIC_API_KEY"]
    for k in range(6):
        r = requests.post(API, timeout=120, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                    "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 700,
                                "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            return "".join(b.get("text", "") for b in r.json()["content"])
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (k + 1))
            continue
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:300]}")
    raise RuntimeError("Anthropic API: too many retries")


def tag_one(p, groups_txt):
    prompt = PROMPT.format(title=p["title"], journal=p["journal"], year=p["pub_year"],
                           pubtypes=", ".join(p["pub_types"]), abstract=p["abstract"][:6000], kinds=KINDS,
                           pops=POPULATIONS, topics=TOPICS, aims=list(AIMS), groups=groups_txt,
                           frontiers="\n".join(f"  {k}: {v}" for k, v in FRONTIERS.items()), dirs=DIRECTIONS)
    raw = call(prompt)
    m = re.search(r"\{.*\}", raw, re.S)
    j = json.loads(m.group(0)) if m else {}
    return j


def validate(j, p, group_ids):
    """Keep only values from the fixed lists, and only a quote and a study count found in the abstract."""
    pick = lambda v, allowed: [x for x in (v if isinstance(v, list) else []) if x in allowed]
    ab = norm(p["abstract"])
    quote = clean(j.get("conclusion") or "")
    if not quote or norm(quote) not in ab:
        quote = None
    n = j.get("n_studies")
    try:
        n = int(n)
        if not re.search(rf"\b{n}\b", p["abstract"]):
            n = None
    except (TypeError, ValueError):
        n = None
    summary = clean(j.get("summary") or "").replace(";", ",")
    summary = re.sub(r"\s*[–—]\s*", ", ", summary)[:300] or None
    return {"relevant": bool(j.get("relevant")), "kind": j.get("kind") if j.get("kind") in KINDS else "other",
            "populations": pick(j.get("populations"), POPULATIONS), "topics": pick(j.get("topics"), TOPICS),
            "aims": pick(j.get("aims"), AIMS), "approach_groups_model": pick(j.get("approach_groups"), group_ids),
            "frontiers_model": pick(j.get("frontiers"), FRONTIERS),
            "direction": j.get("direction") if j.get("direction") in DIRECTIONS else "not_applicable",
            "conclusion_quote": quote, "n_studies": n, "summary": summary}


def drug_matcher():
    """Medicine names (and brand names) from the bank, longest first, as whole-word patterns."""
    names = {}
    stop = {"placebo", "vitamin", "oxygen", "saline", "glucose", "water", "calcium", "sodium", "magnesium",
            "potassium", "protein", "caffeine", "nicotine", "alcohol", "exercise"}
    if (DATA / "drugs.parquet").exists():
        for r in pd.read_parquet(DATA / "drugs.parquet").itertuples():
            nm = str(r.drug_name or "").lower().strip()
            if len(nm) >= 5 and nm not in stop:
                names[nm] = (r.chembl_id, nm, str(r.mechanism_nodes or ""))
    if (DATA / "treatments.parquet").exists():
        for r in pd.read_parquet(DATA / "treatments.parquet").itertuples():
            base = str(r.name or "").lower().strip()
            nodes = "|".join(r.mechanism_nodes) if hasattr(r.mechanism_nodes, "__iter__") and not isinstance(
                r.mechanism_nodes, str) else str(r.mechanism_nodes or "")
            alts = []
            for col in ("other_names", "eu_brands", "us_brands"):
                v = getattr(r, col, None)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                alts += list(v) if not isinstance(v, str) else v.split("|")
            for nm in [base] + [str(a).lower().strip() for a in alts]:
                if len(nm) >= 5 and nm not in stop:
                    names.setdefault(nm, (r.chembl_id, base, nodes))
    pats = sorted(names, key=len, reverse=True)
    rx = re.compile(r"\b(" + "|".join(re.escape(n) for n in pats) + r")\b", re.I) if pats else None
    return rx, names


def main():
    groups = pd.read_parquet(DATA / "hypotheses.parquet")[["approach_group", "approach_group_label"]] \
        .drop_duplicates().dropna()
    group_ids = set(groups.approach_group)
    groups_txt = "\n".join(f"  {g}: {l}" for g, l in sorted(zip(groups.approach_group, groups.approach_group_label)))

    papers = harvest()
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [p for k, p in papers.items() if (cache.get(k) or {}).get("version") != VERSION][:MAX_NEW]
    print(f"literature: {len(todo)} papers to tag with {MODEL}")
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(tag_one, p, groups_txt): p for p in todo}
        for f in as_completed(futs):
            p = futs[f]
            try:
                cache[p["pmid"]] = {"version": VERSION, "model": MODEL, "tagged_on": date.today().isoformat(),
                                    **validate(f.result(), p, group_ids)}
            except Exception as e:
                print(f"literature: {p['pmid']} not tagged: {e}")
            done += 1
            if done % 200 == 0:
                CACHE.write_text(json.dumps(cache, ensure_ascii=False))
                print(f"literature: {done} tagged")
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False))

    rx, names = drug_matcher()
    reg = pd.read_parquet(DATA / "trial_registry_ids.parquet") if (DATA / "trial_registry_ids.parquet").exists() \
        else pd.DataFrame(columns=["registry_id", "msf_trial_id"])
    reg_map = dict(zip(reg.registry_id.astype(str).str.upper(), reg.msf_trial_id))
    hyps = pd.read_parquet(DATA / "hypotheses.parquet")[["hypothesis_id", "aim", "approach", "approach_group",
                                                         "population"]]
    any_ms = {"relapsing", "spms", "ppms", "relapsing_and_progressive", "unspecified"}
    prog = {"spms", "ppms", "relapsing_and_progressive"}
    aim_frontier = {"prevent": "what-starts-ms", "stop_inflammation": "stopping-inflammation",
                    "slow_progression": "why-ms-progresses", "protect_nerves": "repair-and-protection",
                    "repair": "repair-and-protection", "restore_function": "repair-and-protection",
                    "reset": "resetting-the-immune-system"}
    topic_frontier = {"diagnosis": "measuring-ms", "prognosis": "measuring-ms", "biomarkers_imaging": "measuring-ms",
                      "causes_risk": "what-starts-ms", "epidemiology": "what-starts-ms"}

    rows, links = [], []
    for k, p in papers.items():
        c = cache.get(k)
        if not c or c.get("version") != VERSION or not c["relevant"] or c["kind"] == "other":
            continue
        text = f"{p['title']} {p['abstract']}"
        drugs = {}
        if rx:
            for m in rx.finditer(text):
                chembl, base, nodes = names[m.group(1).lower()]
                drugs[chembl] = (base, [n for n in nodes.split("|") if n])
        rule_groups = {n for _, ns in drugs.values() for n in ns if n in group_ids}
        groups_all = sorted(set(c["approach_groups_model"]) | rule_groups)
        pops = set(c["populations"])
        frontiers = set(c["frontiers_model"]) | {aim_frontier[a] for a in c["aims"]} | \
            {topic_frontier[t] for t in c["topics"] if t in topic_frontier}
        if pops & {"nmosd", "mogad"}:
            frontiers.add("nmosd-and-mogad")
        trial_ids = sorted({reg_map[x.upper()] for x in re.findall(
            r"\b(NCT\d{8}|ISRCTN\d{8}|\d{4}-\d{6}-\d{2})\b", p["abstract"]) if x.upper() in reg_map})
        rows.append({**{x: p[x] for x in ("pmid", "doi", "pmcid", "title", "journal", "pub_year", "pub_date",
                                          "cited_by", "open_access", "authors")},
                     "kind": c["kind"], "populations": "|".join(sorted(pops)), "topics": "|".join(c["topics"]),
                     "aims": "|".join(c["aims"]), "approach_groups": "|".join(groups_all),
                     "frontiers": "|".join(sorted(frontiers)), "drugs": "|".join(sorted(b for b, _ in drugs.values())),
                     "chembl_ids": "|".join(sorted(drugs)), "direction": c["direction"],
                     "conclusion_quote": c["conclusion_quote"], "n_studies": c["n_studies"], "summary": c["summary"],
                     "url": f"https://europepmc.org/article/MED/{p['pmid']}", "tagged_by": c.get("model"),
                     "tags_version": VERSION})
        for f_ in frontiers:
            links.append((k, "frontier", f_, "model_or_rule"))
        for ch in drugs:
            links.append((k, "treatment", ch, "name_in_title_or_abstract"))
        for t_ in trial_ids:
            links.append((k, "trial", t_, "registry_number_in_abstract"))
        # hypotheses: same approach group, same aim, matching population
        if "treatment_effect" in c["topics"] or "treatment_safety" in c["topics"]:
            drug_slugs = {b.replace(" ", "-") for b, _ in drugs.values()}
            for h in hyps.itertuples():
                if h.approach_group not in groups_all or h.aim not in c["aims"]:
                    continue
                if "." in h.approach and h.approach.split(".", 1)[1] not in drug_slugs:
                    continue
                if h.population in pops or ("any_ms" in pops and h.population in any_ms) or \
                        ("progressive" in pops and h.population in prog) or \
                        (h.population == "early_cis_ris" and "early_cis_ris" in pops):
                    links.append((k, "hypothesis", h.hypothesis_id, "approach_aim_population"))

    df = pd.DataFrame(rows)
    ln = pd.DataFrame(links, columns=["pmid", "target_type", "target_id", "rule"]).drop_duplicates()
    df.to_parquet(DATA / "papers.parquet", index=False)
    ln.to_parquet(DATA / "paper_links.parquet", index=False)
    print(f"literature: {len(df)} reviews and guidelines kept, {len(ln)} links "
          f"({ln.target_type.value_counts().to_dict() if len(ln) else {}})")
    if len(df):
        print("literature: kinds", df.kind.value_counts().to_dict())


if __name__ == "__main__":
    main()
