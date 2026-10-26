"""Harvest MS, NMOSD and MOGAD studies from ClinicalTrials.gov API v2.

Writes one JSONL file of full study records (protocol + results sections).
Usage: python harvest_ctgov.py OUT_DIR
"""
import json
import sys
import time
from pathlib import Path

import requests

API = "https://clinicaltrials.gov/api/v2/studies"
QUERIES = {
    "ms": "multiple sclerosis OR clinically isolated syndrome OR radiologically isolated syndrome OR demyelinating",
    "nmosd": "neuromyelitis optica",
    "mogad": "MOG antibody OR myelin oligodendrocyte glycoprotein antibody disease OR MOGAD",
    "optic_neuritis": "optic neuritis",
}


def harvest(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[str, dict] = {}
    for label, cond in QUERIES.items():
        token = None
        n = 0
        while True:
            params = {"query.cond": cond, "pageSize": 1000, "format": "json"}
            if token:
                params["pageToken"] = token
            for attempt in range(5):
                try:
                    r = requests.get(API, params=params, timeout=120)
                    r.raise_for_status()
                    break
                except requests.RequestException as e:  # retry with backoff
                    print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
                    time.sleep(2 ** attempt)
            else:
                raise SystemExit(f"failed on {label}")
            page = r.json()
            for s in page.get("studies", []):
                nct = s["protocolSection"]["identificationModule"]["nctId"]
                rec = seen.setdefault(nct, {"query_labels": [], "study": s})
                rec["query_labels"].append(label)
                n += 1
            token = page.get("nextPageToken")
            if not token:
                break
            time.sleep(0.3)
        print(f"{label}: {n} records")
    path = out_dir / "ctgov_studies.jsonl"
    with path.open("w") as f:
        for nct, rec in seen.items():
            f.write(json.dumps({"nct_id": nct, **rec}) + "\n")
    print(f"unique studies: {len(seen)} -> {path}")


if __name__ == "__main__":
    harvest(Path(sys.argv[1]))
