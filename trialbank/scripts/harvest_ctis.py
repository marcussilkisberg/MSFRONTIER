"""Harvest the EU Clinical Trials Information System (CTIS, euclinicaltrials.eu): every trial registered under the
EU Clinical Trials Regulation since 2023, including those transitioned from the old EU register.

Writes ../raw/ctis_search.json (search hits) and ../raw/ctis/<ctNumber>.json (full public record).
Usage: python harvest_ctis.py ../raw
"""
import json
import sys
import time
from pathlib import Path

import requests

BASE = "https://euclinicaltrials.eu/ctis-public-api"
QUERIES = ["multiple sclerosis", "neuromyelitis optica", "NMOSD", "MOGAD", "MOG antibody", "optic neuritis",
           "demyelinating", "transverse myelitis", "clinically isolated syndrome"]
S = requests.Session()
S.headers.update({"content-type": "application/json", "accept": "application/json"})


def post(payload, tries=4):
    for k in range(tries):
        try:
            r = S.post(f"{BASE}/search", json=payload, timeout=90)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    raise RuntimeError("CTIS search failed")


def main(raw):
    raw = Path(raw)
    (raw / "ctis").mkdir(parents=True, exist_ok=True)
    hits = {}
    for q in QUERIES:
        page = 1
        while True:
            j = post({"pagination": {"page": page, "size": 100},
                      "sort": {"property": "decisionDate", "direction": "DESC"},
                      "searchCriteria": {"containAll": q}})
            for d in j.get("data", []):
                hits.setdefault(d["ctNumber"], d)
            if not j.get("pagination", {}).get("nextPage"):
                break
            page += 1
        print(f"CTIS '{q}': {j.get('pagination', {}).get('totalRecords')} hits")
    (raw / "ctis_search.json").write_text(json.dumps(hits))

    ok = 0
    for ct in hits:
        for k in range(3):
            try:
                r = S.get(f"{BASE}/retrieve/{ct}", timeout=90)
                if r.status_code == 200:
                    (raw / "ctis" / f"{ct}.json").write_text(r.text)
                    ok += 1
                    break
            except requests.RequestException:
                pass
            time.sleep(2 * (k + 1))
        time.sleep(0.2)
    print(f"CTIS: {len(hits)} trials found, {ok} full records saved")
    if hits and ok < 0.8 * len(hits):
        raise SystemExit("CTIS: too many records failed to download")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../raw")
