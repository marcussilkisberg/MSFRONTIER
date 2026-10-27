"""Measures dictionary: what the scales, MRI measures and biomarkers used in MS trials mean.

Definitions are machine-written (by Claude, Oct 2026) from widely used standard definitions and are not
human-reviewed. Usage counts are computed from the trial bank on every build.
Writes data/measures.parquet (+ CSV).
"""
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data"

# id, name, short, kind, endpoint_tag (links to trial tags), plain description, how trials use it, regex to count usage
MEASURES = [
    ("edss", "Expanded Disability Status Scale", "EDSS", "clinical scale", "disability_progression",
     "A neurologist's 0–10 rating of disability in half-point steps, based on an examination of body systems and walking range. 0 is a normal exam; around 4 to 5.5 walking range shrinks; 6 means needing a walking aid; 10 is death due to MS.",
     "The main disability measure in almost every MS trial, mostly to define confirmed disability progression.",
     r"\bedss\b|expanded disability"),
    ("cdp", "Confirmed disability progression", "CDP", "composite outcome", "disability_progression",
     "A lasting increase in EDSS: usually at least 1.0 point (or 1.5 from a baseline of 0, and 0.5 from 5.5 or higher), still present when re-checked 12 or 24 weeks later (CDP12, CDP24).",
     "The standard primary endpoint of progressive MS trials and a key secondary endpoint in relapsing MS.",
     r"confirmed disability (progression|worsening)|\bcdp\b|\bcdw\b"),
    ("ccdp", "Composite confirmed disability progression", "cCDP", "composite outcome", "disability_progression",
     "Progression counted if any of three measures worsens and stays worse: EDSS, the timed 25-foot walk (by 20% or more) or the 9-hole peg test (by 20% or more).",
     "Used in newer progressive MS trials because it catches arm and walking decline the EDSS misses.",
     r"composite.{0,40}(progression|disability)|\bccdp"),
    ("pira", "Progression independent of relapse activity", "PIRA", "concept / outcome", "disability_progression",
     "Disability that worsens without a relapse causing it, the silent progression that can start early in MS.",
     "Increasingly analysed in trials and registries; some new trials enrol people with PIRA specifically.",
     r"\bpira\b|independent of relapse"),
    ("raw", "Relapse-associated worsening", "RAW", "concept / outcome", "disability_progression",
     "Disability that stays after a relapse has not fully recovered.",
     "Analysed alongside PIRA to separate the two routes to disability.",
     r"relapse.associated worsening"),
    ("t25fw", "Timed 25-foot walk", "T25FW", "clinical test", "walking_mobility",
     "How many seconds it takes to walk 25 feet (7.6 m) as quickly and safely as possible. A 20% slowing is usually treated as meaningful.",
     "Part of composite progression endpoints and walking trials.",
     r"t25fw|timed 25|25.foot walk"),
    ("9hpt", "Nine-hole peg test", "9HPT", "clinical test", "upper_limb",
     "Time to place and remove nine pegs in a board, for each hand. A 20% slowing is usually treated as meaningful.",
     "Measures hand and arm function; part of composite endpoints and the main endpoint in some advanced MS trials.",
     r"9.?hole peg|nine.hole|\b9hpt\b"),
    ("arr", "Annualised relapse rate", "ARR", "clinical outcome", "relapse",
     "The average number of relapses per person per year in a treatment group.",
     "The standard primary endpoint of relapsing MS trials.",
     r"annuali[sz]ed relapse|\barr\b"),
    ("neda3", "No evidence of disease activity", "NEDA-3", "composite outcome", "relapse",
     "No relapses, no new or active MRI lesions and no confirmed disability progression over a period, usually two years.",
     "A demanding treatment goal used in high-efficacy and stem cell transplant trials.",
     r"\bneda\b|no evidence of disease activity"),
    ("gd_lesions", "Gadolinium-enhancing lesions", "Gd+ lesions", "MRI", "mri_lesions",
     "Lesions that light up after a contrast injection, a sign of active inflammation in the last few weeks.",
     "A sensitive early efficacy measure in phase 2 relapsing MS trials.",
     r"gadolinium|\bgd\+|enhancing lesion"),
    ("t2_lesions", "New or enlarging T2 lesions", "T2 lesions", "MRI", "mri_lesions",
     "New lesions, or lesions that grew, on standard MRI since an earlier scan; together with Gd+ lesions they show inflammatory activity.",
     "Common primary endpoint in phase 2 and head-to-head trials.",
     r"new or enlarging|t2 lesion|t2.hyperintense"),
    ("brain_atrophy", "Brain volume loss (atrophy)", "PBVC", "MRI", "brain_atrophy",
     "The yearly percentage loss of brain volume. Everyone loses a little with age; MS speeds it up.",
     "A primary endpoint in some phase 2 progressive trials; a warning: drugs that shrink atrophy have not always slowed disability.",
     r"atrophy|brain volume|\bpbvc\b"),
    ("sel", "Slowly expanding lesions", "SEL", "MRI", "smouldering_inflammation",
     "Existing lesions that keep growing slowly over months to years, a marker of smouldering inflammation behind progression.",
     "A newer exploratory endpoint, used for example in the fenebrutinib and BTK inhibitor trials.",
     r"slowly expanding|\bsel\b"),
    ("prl", "Paramagnetic rim lesions", "PRL", "MRI", "smouldering_inflammation",
     "Lesions with a dark iron rim on special MRI, showing chronic active inflammation at their edge; they are linked to worse disability.",
     "An emerging endpoint and prognostic marker in progression trials.",
     r"paramagnetic rim|rim lesion|\bprl\b"),
    ("cvs", "Central vein sign", "CVS", "MRI", "mri_lesions",
     "A small vein visible in the centre of a lesion, typical of MS lesions; it helps tell MS apart from look-alike conditions.",
     "Used in diagnosis research rather than as a treatment endpoint.",
     r"central vein"),
    ("nfl", "Neurofilament light chain", "NfL", "blood biomarker", "fluid_biomarker",
     "A protein released when nerve fibres are damaged, measurable in blood. Higher levels mean more ongoing nerve injury.",
     "A widely used secondary endpoint and early signal of treatment effect; levels rise with age, so age-adjusted values are used.",
     r"neurofilament|\bnf-?l\b"),
    ("gfap", "Glial fibrillary acidic protein", "GFAP", "blood biomarker", "fluid_biomarker",
     "A protein from astrocytes, support cells in the brain; raised levels are linked to progression more than to relapses.",
     "Increasingly measured alongside NfL in progressive MS trials.",
     r"\bgfap\b|glial fibrillary"),
    ("kflc", "Kappa free light chains", "κFLC", "spinal fluid biomarker", "fluid_biomarker",
     "Antibody fragments in the spinal fluid that signal antibody production in the central nervous system; an alternative to oligoclonal bands.",
     "Used in diagnosis and to track immune activity in the spinal fluid, for example in CAR-T studies.",
     r"kappa free light|\bkflc\b"),
    ("sdmt", "Symbol Digit Modalities Test", "SDMT", "cognitive test", "cognition",
     "A 90-second test of processing speed: matching symbols to numbers. A drop of about 4 points is often treated as meaningful.",
     "The most common cognition outcome in MS trials.",
     r"\bsdmt\b|symbol digit"),
    ("msfc", "Multiple Sclerosis Functional Composite", "MSFC", "composite outcome", "disability_progression",
     "A combined score of walking speed, hand function and a cognitive test.",
     "Used as a secondary disability endpoint, especially in older trials.",
     r"\bmsfc\b|functional composite"),
    ("msws12", "MS Walking Scale (12 items)", "MSWS-12", "patient-reported", "walking_mobility",
     "A questionnaire in which people rate how MS limits their walking.",
     "Common in walking and rehabilitation trials.",
     r"msws|walking scale"),
    ("mfis", "Modified Fatigue Impact Scale", "MFIS", "patient-reported", "fatigue",
     "A questionnaire on how fatigue affects physical, thinking and social life.",
     "The usual primary outcome of fatigue trials.",
     r"\bmfis\b|modified fatigue"),
    ("msis29", "MS Impact Scale (29 items)", "MSIS-29", "patient-reported", "quality_of_life_pro",
     "A questionnaire on the physical and psychological impact of MS.",
     "Widely used quality-of-life outcome.",
     r"msis|ms impact scale"),
    ("vep", "Visual evoked potential latency", "VEP", "neurophysiology", "remyelination",
     "How long a signal takes to travel from the eye to the brain. Faster signals after treatment suggest repair of myelin in the optic nerve.",
     "The main endpoint of many myelin repair trials, such as clemastine and metformin studies.",
     r"evoked potential|\bm?vep\b"),
    ("oct", "Optical coherence tomography", "OCT", "imaging", "retina_oct",
     "A quick eye scan measuring the thickness of nerve layers at the back of the eye (RNFL, GCIPL), which thin as nerve fibres are lost.",
     "Used to measure nerve protection, especially in optic neuritis trials.",
     r"optical coherence|\boct\b|\brnfl\b|gcipl"),
    ("myelin_mri", "Myelin-sensitive MRI (MTR, myelin water fraction)", "MTR / MWF", "MRI", "remyelination",
     "Special MRI methods that estimate how much myelin is present in brain tissue.",
     "Used to detect repair in remyelination trials.",
     r"magneti[sz]ation transfer|\bmtr\b|myelin water"),
    ("tspo_pet", "TSPO PET imaging", "TSPO-PET", "imaging", "smouldering_inflammation",
     "A brain scan with a tracer that sticks to activated microglia, the brain's immune cells.",
     "Used as a primary endpoint in some trials of drugs aimed at microglia (for example nasal foralumab).",
     r"\btspo\b|pbr06|pk11195|dpa-714|microglia.{0,20}pet"),
]


def main():
    trials = pd.read_parquet(OUT / "trials.parquet")
    outcomes = pd.read_parquet(OUT / "trial_outcomes.parquet")
    outcomes = outcomes[outcomes.msf_trial_id.isin(set(trials[trials.study_type == "interventional"].msf_trial_id))]
    prim = outcomes[outcomes.outcome_kind == "primary"]
    rows = []
    for mid, name, short, kind, tag, plain, use, rx in MEASURES:
        any_hit = outcomes.measure.fillna("").str.contains(rx, case=False, regex=True)
        prim_hit = prim.measure.fillna("").str.contains(rx, case=False, regex=True)
        rows.append({
            "measure_id": mid, "name": name, "short_name": short, "kind": kind, "endpoint_tag": tag,
            "what_it_is": plain, "how_trials_use_it": use,
            "n_trials_measuring": int(outcomes[any_hit].msf_trial_id.nunique()),
            "n_trials_primary_endpoint": int(prim[prim_hit].msf_trial_id.nunique()),
            "further_reading": "https://europepmc.org/search?query=" + quote_plus(f'"{name}" AND "multiple sclerosis"'),
            "written_by": "machine (Claude), not human-reviewed", "as_of": "2026-10-27",
        })
    df = pd.DataFrame(rows).sort_values("n_trials_measuring", ascending=False)
    df.to_parquet(OUT / "measures.parquet", index=False)
    df.to_csv(OUT / "measures.csv", index=False)
    print(df[["short_name", "kind", "n_trials_measuring", "n_trials_primary_endpoint"]].to_string(index=False))


if __name__ == "__main__":
    main()
