"""Spot-check the v0 bank against landmark trials, and draw a random audit sample.

Usage: python validate.py   (reads ../data, writes ../data/audit_sample.csv)
"""
from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parent.parent / "data"
t = pd.read_csv(D / "trials.csv", low_memory=False)

LANDMARKS = {
    "MS-STAT2 (simvastatin, SPMS, phase 3 null)": r"MS-STAT2|MS-STAT 2",
    "Octopus (MAMS platform, progressive MS)": r"\bOCTOPUS\b",
    "ORATORIO (ocrelizumab, PPMS)": r"ORATORIO",
    "OPERA I/II (ocrelizumab, RMS)": r"\bOPERA ?I",
    "EXPAND (siponimod, SPMS)": r"\bEXPAND\b",
    "ASCLEPIOS (ofatumumab, RMS)": r"ASCLEPIOS",
    "HERCULES (tolebrutinib, nrSPMS)": r"HERCULES",
    "PERSEUS (tolebrutinib, PPMS)": r"PERSEUS",
    "SYNERGY (opicinumab, remyelination)": r"\bSYNERGY\b",
    "ReBUILD (clemastine, remyelination)": r"ReBUILD",
    "SPRINT-MS (ibudilast, progressive)": r"SPRINT-MS|SPRINT MS",
    "MS-SPI (biotin, progressive)": r"MS-SPI",
    "CHAMPION-NMOSD (ravulizumab)": r"CHAMPION-NMO",
    "N-MOmentum (inebilizumab, NMOSD)": r"N-MOmentum|MOMENTUM",
    "MS-SMART (amiloride/fluoxetine/riluzole)": r"MS-SMART",
    "ASCEND (natalizumab, SPMS)": r"\bASCEND\b",
    "INFORMS (fingolimod, PPMS)": r"INFORMS",
    "COSMOS / MOGAD trials": r"cosMOG|METEOROID",
}
cols = ["msf_trial_id", "registries", "acronym", "tier", "population_group", "phase", "status", "result_signal",
        "drugs", "mechanism_nodes", "primary_endpoint_class", "enrollment"]
hay = (t.acronym.fillna("") + " " + t.title.fillna("") + " " + t.official_title.fillna(""))
found = []
for label, rx in LANDMARKS.items():
    m = t[hay.str.contains(rx, case=False, regex=True)]
    m = m[m.study_type == "interventional"]
    print(f"\n## {label}: {len(m)} match(es)")
    if len(m):
        print(m[cols].head(4).to_string(index=False, max_colwidth=40))
    found.append({"landmark": label, "n_matches": len(m)})
pd.DataFrame(found).to_csv(D / "landmark_check.csv", index=False)

# random audit sample of interventional tier-1 trials, for hand review
intr = t[(t.tier == 1) & (t.study_type == "interventional")]
sample = intr.sample(60, random_state=20261026)
sample[["msf_trial_id", "url", "title", "conditions_raw", "phenotypes", "population_group", "primary_endpoint_class",
        "primary_endpoint_tags", "interventions_raw", "drugs", "mechanism_nodes", "status", "result_signal"]] \
    .to_csv(D / "audit_sample.csv", index=False)
print(f"\naudit sample written: {len(sample)} trials")
