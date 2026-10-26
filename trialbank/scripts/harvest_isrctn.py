"""Harvest ISRCTN records for MS-related search terms (full XML).

Usage: python harvest_isrctn.py OUT_DIR
"""
import sys
import time
from pathlib import Path

import requests

API = "https://www.isrctn.com/api/query/format/default"
QUERIES = {"multiple20s": "multiple sclerosis", "neuromyeliti": "neuromyelitis optica",
           "optic20neur": "optic neuritis", "MOGAD": "MOGAD"}


def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, q in QUERIES.items():
        for attempt in range(5):
            try:
                r = requests.get(API, params={"q": q, "limit": 2000}, timeout=300)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                print(f"  retry {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(2 ** attempt)
        else:
            raise SystemExit(f"failed: {q}")
        (out_dir / f"isrctn_{key}.xml").write_bytes(r.content)
        print(f"{q}: {r.content.count(b'<fullTrial>')} records")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
