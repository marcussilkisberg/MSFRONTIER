"""Harvest full EU Clinical Trials Register (EudraCT) records, page by page.

The register's bulk "all" download is refused, so this walks the per-page full
text download until a page adds no new EudraCT numbers.
Usage: python harvest_euctr.py OUT_DIR
"""
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://www.clinicaltrialsregister.eu/ctr-search/rest/download/full"
QUERIES = ["multiple sclerosis", "neuromyelitis optica", "optic neuritis",
           "clinically isolated syndrome", "MOG antibody"]
EUDRACT = re.compile(r"^EudraCT Number: (\d{4}-\d{6}-\d{2})", re.M)


def harvest(out_dir: Path) -> None:
    out = out_dir / "euctr_full.txt"
    seen: set[str] = set()
    with out.open("w") as f:
        for q in QUERIES:
            page, added_q = 1, 0
            while True:
                for attempt in range(5):
                    try:
                        r = requests.get(BASE, params={"query": q, "page": page, "mode": "current_page"}, timeout=180)
                        r.raise_for_status()
                        break
                    except requests.RequestException as e:
                        print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
                        time.sleep(2 ** attempt)
                else:
                    raise SystemExit(f"failed: {q} page {page}")
                ids = set(EUDRACT.findall(r.text))
                new = ids - seen
                if not ids:
                    break
                # keep every page's text; duplicates across queries are dropped at parse time
                f.write(f"\n#### QUERY={q} PAGE={page}\n")
                f.write(r.text)
                seen |= ids
                added_q += len(new)
                if not new and page > 1:
                    break
                page += 1
                time.sleep(0.5)
                if page > 200:
                    break
            print(f"{q}: {page - 1} pages, {added_q} new trials (total {len(seen)})")
    print(f"unique EudraCT numbers: {len(seen)} -> {out}")


if __name__ == "__main__":
    harvest(Path(sys.argv[1]))
