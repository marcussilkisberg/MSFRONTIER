"""Find publications that cite each trial's registry IDs, via Europe PMC.

Registries under-link papers, so this catches results that were published but
never linked back. Cached in raw/europepmc_cache.json.
Usage: python europepmc.py   (reads ../data/trial_registry_ids.csv)
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "raw" / "europepmc_cache.json"
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_lock = threading.Lock()
_s = requests.Session()


def search(reg_id):
    q = f'"{reg_id}"'
    for attempt in range(4):
        try:
            r = _s.get(API, params={"query": q, "format": "json", "resultType": "lite", "pageSize": 50}, timeout=60)
            if r.status_code == 200:
                out = []
                for h in r.json().get("resultList", {}).get("result", []):
                    out.append({k: h.get(k) for k in ("id", "source", "pmid", "pmcid", "doi", "title", "journalTitle",
                                                      "pubYear", "pubType", "firstPublicationDate")})
                return out
        except requests.RequestException:
            pass
        time.sleep(1 + attempt)
    return None


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    ids = pd.read_csv(ROOT / "data" / "trial_registry_ids.csv")
    todo = sorted(set(ids.other_id) - set(cache))
    print(f"europepmc: {len(todo)} registry IDs to search")

    def one(x):
        res = search(x)
        with _lock:
            if res is not None:
                cache[x] = res

    with ThreadPoolExecutor(6) as ex:
        for i, _ in enumerate(ex.map(one, todo)):
            if i and i % 500 == 0:
                print(f"  {i}/{len(todo)}")
                with _lock:
                    CACHE.write_text(json.dumps(cache))
    CACHE.write_text(json.dumps(cache))
    print("hits:", sum(1 for v in cache.values() if v))


if __name__ == "__main__":
    main()
