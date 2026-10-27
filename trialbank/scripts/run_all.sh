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
python results_layer.py                  # posted registry results, per arm
python treatments_layer.py               # EMA + FDA approvals, safety letters, adverse-event reports
python measures_layer.py                 # measures dictionary with usage counts
python genetics_layer.py || echo "genetic leads skipped (Open Targets unreachable)"
python readouts_layer.py || echo "paper readouts skipped"   # reads papers only if ANTHROPIC_API_KEY is set
python hypotheses_layer.py               # hypothesis ledger, from everything above plus ../project/*.yml
python validate.py > ../data/validate.log

if [ -n "${SUPABASE_DB_URL:-}" ]; then
  python load_supabase.py ../data
else
  echo "SUPABASE_DB_URL not set: built ../data but did not load it."
fi
