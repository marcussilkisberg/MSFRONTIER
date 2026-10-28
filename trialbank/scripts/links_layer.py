"""Trial-to-trial links found in the registries' own text: extensions, follow-ups and sub-studies that name their
parent trial's registry number (e.g. CONSONANCE EX -> CONSONANCE). Writes ../data/trial_links.parquet.

Drug development paths (phase 1 -> 2 -> 3 for the same drug and MS type) are not stored here: the view
bank.drug_programmes builds them from the trials table by rule.
Usage: python links_layer.py
"""
import re
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
RX = re.compile(r"\b(NCT\d{8}|\d{4}-\d{6}-\d{2}(?:-\d{2})?|ISRCTN\d{8})\b", re.I)
EXT = re.compile(r"extension|long[- ]term|follow[- ]?up|roll[- ]?over|open[- ]label (?:phase|study) .*after|continuation",
                 re.I)
SUB = re.compile(r"sub-?study|substudy|mechanistic|ancillary|biomarker study|imaging study", re.I)


def main():
    t = pd.read_parquet(DATA / "trials.parquet").set_index("msf_trial_id")
    x = pd.read_parquet(DATA / "trial_texts.parquet").set_index("msf_trial_id") \
        if (DATA / "trial_texts.parquet").exists() else pd.DataFrame()
    ids = pd.read_parquet(DATA / "trial_registry_ids.parquet")
    owner = {str(r.other_id).upper(): r.msf_trial_id for r in ids.itertuples()}
    rows = []
    for uid, r in t.iterrows():
        heading = f"{r.title or ''} {r.official_title or ''}"
        body = heading
        if len(x) and uid in x.index:
            body += f" {x.at[uid, 'brief_summary'] or ''} {x.at[uid, 'eligibility_text'] or ''}"
        for m in {a.upper() for a in RX.findall(body)}:
            other = owner.get(m) or owner.get(m[:14])
            if not other or other == uid:
                continue
            rel = "extension_of" if EXT.search(heading) else "substudy_of" if SUB.search(heading) else "refers_to"
            rows.append({"msf_trial_id": uid, "related_trial_id": other, "relation": rel, "matched_id": m,
                         "source": "registry text"})
    df = pd.DataFrame(rows, columns=["msf_trial_id", "related_trial_id", "relation", "matched_id", "source"])
    df = df.drop_duplicates(["msf_trial_id", "related_trial_id"])
    df.to_parquet(DATA / "trial_links.parquet", index=False)
    print(f"trial links: {len(df)} ({df.relation.value_counts().to_dict()})")


if __name__ == "__main__":
    main()
