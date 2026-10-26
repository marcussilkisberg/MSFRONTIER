#!/usr/bin/env bash
# Full refresh: harvest every registry, normalise, tag, build, and (if SUPABASE_DB_URL is set) load.
# Run from the repository root:  bash trialbank/scripts/run_all.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p ../raw ../data

python harvest_ctgov.py ../raw
python harvest_isrctn.py ../raw
python harvest_euctr.py ../raw           # slowest step (~25 min): the EU register serves 20 trials per page
python warm_chembl_all.py                # cached in raw/chembl_cache.json; only new names are looked up
python build.py                          # first pass: writes trial_registry_ids for the Europe PMC search
python europepmc.py                      # cached in raw/europepmc_cache.json
python build.py                          # final pass with publications
python validate.py > ../data/validate.log

if [ -n "${SUPABASE_DB_URL:-}" ]; then
  python load_supabase.py ../data
else
  echo "SUPABASE_DB_URL not set: built ../data but did not load it."
fi
