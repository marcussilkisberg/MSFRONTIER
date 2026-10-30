"""Open data exports: one CSV per table, a data dictionary and one zip, written to ../exports/.

The weekly workflow publishes them as a GitHub release, so the latest files always sit at
  https://github.com/<owner>/<repo>/releases/latest/download/<file>
with stable file names (msfrontier-data.zip, trials.csv, findings.csv ...). The release notes and README carry the
date the data were built.

Usage: python export_layer.py
"""
import json
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "exports"

KNOWN = ("met", "not_met", "mixed", "equivalent", "not_efficacy")


def flat(v):
    """Lists and arrays become 'a|b|c', so every cell is plain text in a spreadsheet."""
    if isinstance(v, (list, tuple)) or (hasattr(v, "tolist") and not isinstance(v, str)):
        try:
            return "|".join(str(x) for x in list(v))
        except TypeError:
            return v
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return v


def tidy(df):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(flat)
    return df


def finding(t, r):
    """Same rules as the bank's trial_findings view (supabase/migrations/007_trial_page.sql)."""
    sig, st = str(t.get("result_signal") or ""), str(t.get("status") or "")
    if sig == "primary_p_lt_0.05":
        return "met", "registry_analysis"
    if sig == "primary_p_ge_0.05":
        return "not_met", "registry_analysis"
    if "futility" in sig:
        return "stopped_no_effect", "registry_stop_reason"
    if sig.startswith("terminated:safety"):
        return "stopped_safety", "registry_stop_reason"
    if st in ("recruiting", "active_not_recruiting", "not_yet_recruiting", "enrolling_by_invitation", "ongoing",
              "ongoing_inferred", "suspended", "transitioned_to_ctis"):
        return "ongoing", None
    if sig.startswith(("terminated:", "withdrawn:")):
        return "stopped_other", "registry_stop_reason"
    if r is not None and r.get("readout") in KNOWN:
        return r.get("readout"), "paper_machine_read"
    if sig == "results_posted_no_primary_test":
        return "results_posted_no_test", None
    if sig in ("publication_linked", "publication_found_europepmc"):
        return "result_in_paper_unread", None
    return "no_result_found", None


DICTIONARY = {
    "trials.csv": ("One row per trial after duplicates across registries are merged.", {
        "msf_trial_id": "MSFrontier's stable ID, built from the trial's main registry number",
        "registry_ids": "every registry number of this trial, separated by |",
        "title / official_title / acronym": "as registered",
        "population_group": "type of MS or related disease the trial enrolled (relapsing, progressive, early, nmosd, ...)",
        "phase / status / start_date / primary_completion_date / completion_date": "as registered, statuses normalised",
        "enrollment / enrollment_type": "participants, actual or anticipated",
        "allocation / masking / has_placebo_or_sham": "design, as registered",
        "drugs / comparator_drugs / chembl_ids": "medicines matched to ChEMBL, separated by |",
        "mechanism_nodes": "MSFrontier's mechanism groups for the tested medicines",
        "primary_endpoint_tags": "what the primary outcome measures (relapse, disability_progression, mri, ...)",
        "lead_sponsor / sponsor_class / countries": "as registered",
        "url": "link to the main registry record",
    }),
    "registry_ids.csv": ("Every registry number known for each trial, and which registry said so.", {}),
    "findings.csv": ("What each trial found, by the same rules as the trial pages.", {
        "finding": "met, not_met, mixed, equivalent, not_efficacy, stopped_no_effect, stopped_safety, stopped_other, "
                   "ongoing, results_posted_no_test, result_in_paper_unread or no_result_found",
        "finding_source": "registry_analysis (posted p-value), registry_stop_reason, or paper_machine_read",
        "paper_pmid / paper_quote": "for paper_machine_read: the PubMed ID and the sentence the reading rests on, "
                                    "copied word for word from the abstract",
    }),
    "primary_analyses.csv": ("Statistical analyses of primary outcomes posted on ClinicalTrials.gov.", {}),
    "hypotheses.csv": ("Every hypothesis (approach x aim x type of MS) with its status.", {
        "outcome": "roadmap, testing, pending, promising, confirmed, mixed, failed_early, disproven or unclear",
        "rules_version": "version of the rules that set the status (see HYPOTHESES.md in the repository)",
    }),
    "hypothesis_evidence.csv": ("Which trials bear on which hypothesis, and whether each counts toward its status.", {}),
    "medicines.csv": ("Medicines approved for MS, NMOSD and MOGAD, with approvals and trial counts.", {}),
    "results_watch.csv": ("Finished phase 2 to 4 trials and whether their results could be found.", {}),
    "trial_links.csv": ("Links between trials stated in the registries (extensions, sub-studies).", {}),
    "papers.csv": ("Systematic reviews, meta-analyses and guidelines on MS, NMOSD and MOGAD since 2015, tagged by "
                   "software.", {
        "kind / populations / topics / aims / approach_groups / frontiers": "tags from fixed lists, separated by |",
        "direction": "for treatment reviews: benefit, no_benefit, mixed, harm, uncertain or not_applicable",
        "conclusion_quote": "the abstract's main conclusion, copied word for word",
        "summary": "one plain-English sentence written by software",
    }),
    "paper_links.csv": ("Which hypotheses, medicines, trials and frontiers each review is linked to, and by which rule. "
                        "Reviews never change a hypothesis's status.", {}),
}

LICENCE = """## Licence and attribution

MSFrontier's own work in these files (merged records, tags, mechanism groups, findings, hypotheses and their
statuses, the results watch) is released under the Creative Commons Attribution 4.0 licence (CC BY 4.0). Please
cite "MSFrontier Trial Bank, <build date>".

Registry content (titles, dates, statuses, sponsors and other registered fields) comes from ClinicalTrials.gov, the
EU Clinical Trials Register, the EU Clinical Trials Information System (CTIS) and ISRCTN, and remains subject to each
registry's terms. Medicine identifiers come from ChEMBL (CC BY-SA 3.0). Quoted sentences come from published
abstracts and are reproduced as short quotations with their PubMed ID. Paper titles and bibliographic details come
from Europe PMC.

The data are assembled by software and are not reviewed by people. They are not medical advice.
"""


def main():
    OUT.mkdir(exist_ok=True)
    built = date.today().isoformat()
    t = pd.read_parquet(DATA / "trials.parquet")
    keep = ["msf_trial_id", "registry_ids", "registries", "url", "title", "official_title", "acronym", "diseases",
            "population_group", "phenotypes", "study_type", "phase", "status", "start_date", "primary_completion_date",
            "completion_date", "enrollment", "enrollment_type", "allocation", "masking", "has_placebo_or_sham",
            "primary_purpose", "drugs", "comparator_drugs", "chembl_ids", "mechanism_families", "mechanism_nodes",
            "nondrug_categories", "primary_endpoint_class", "primary_endpoint_tags", "lead_sponsor", "sponsor_class",
            "n_countries", "countries", "why_stopped", "has_posted_results", "results_first_posted", "last_update"]
    files = {"trials.csv": t[[c for c in keep if c in t.columns]]}

    files["registry_ids.csv"] = pd.read_parquet(DATA / "trial_registry_ids.parquet")

    rd = {}
    if (DATA / "trial_readouts.parquet").exists():
        for r in pd.read_parquet(DATA / "trial_readouts.parquet").to_dict("records"):
            rd[r["msf_trial_id"]] = r
    rows = []
    for r in t.to_dict("records"):
        x = rd.get(r["msf_trial_id"])
        f, src = finding(r, x)
        paper = src == "paper_machine_read"
        rows.append({"msf_trial_id": r["msf_trial_id"], "acronym": r.get("acronym"), "title": r.get("title"),
                     "phase": r.get("phase"), "status": r.get("status"), "finding": f, "finding_source": src,
                     "paper_pmid": x.get("pmid") if paper else None, "paper_quote": x.get("quote") if paper else None,
                     "has_posted_results": r.get("has_posted_results")})
    files["findings.csv"] = pd.DataFrame(rows)

    for name, src in (("primary_analyses.csv", "trial_primary_analyses_ctgov"), ("hypotheses.csv", "hypotheses"),
                      ("hypothesis_evidence.csv", "hypothesis_evidence"), ("medicines.csv", "treatments"),
                      ("results_watch.csv", "results_watch"), ("trial_links.csv", "trial_links"),
                      ("papers.csv", "papers"), ("paper_links.csv", "paper_links")):
        p = DATA / f"{src}.parquet"
        if p.exists():
            files[name] = pd.read_parquet(p)

    readme = [f"# MSFrontier open data\n\nBuilt {built}. Updated every week from public trial registries.\n",
              "Lists inside a cell are separated by `|`. Dates are ISO (YYYY-MM-DD).\n", "## Files\n"]
    for name, df in files.items():
        df = tidy(df)
        df.to_csv(OUT / name, index=False, encoding="utf-8")
        what, cols = DICTIONARY.get(name, ("", {}))
        readme.append(f"### {name}\n\n{what} {len(df):,} rows.\n")
        for c, d in cols.items():
            readme.append(f"- `{c}`: {d}")
        readme.append(f"\nColumns: {', '.join(f'`{c}`' for c in df.columns)}\n")
    readme.append(LICENCE)
    (OUT / "README.md").write_text("\n".join(readme), encoding="utf-8")

    with zipfile.ZipFile(OUT / "msfrontier-data.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name in list(files) + ["README.md"]:
            z.write(OUT / name, name)
    print(f"exports: {len(files)} tables, built {built}; " +
          ", ".join(f"{n} {len(d):,}" for n, d in files.items()))


if __name__ == "__main__":
    main()
