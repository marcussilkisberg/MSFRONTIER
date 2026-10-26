"""Load a built trial bank into Supabase Postgres (schema "bank", migration 003).

Machine tables are upserted; child rows are replaced per trial; trials no longer
in the build are kept but marked in_scope = false. Changes to tracked registry
facts are written to bank.change_log. Human corrections (bank.corrections) are
never touched, except that rows from curation/overrides.csv are synced in as
corrections authored by 'curation_file'. Finally the knowledge-graph edges are rebuilt.

Usage:
  SUPABASE_DB_URL=postgresql://... python load_supabase.py [DATA_DIR]
Use the "Session pooler" connection string from Supabase (Connect → Session pooler).
"""
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"

TRACKED = ["status", "phase", "enrollment", "primary_completion_date", "completion_date", "result_signal",
           "why_stopped", "has_posted_results", "tier"]

TRIAL_ARRAYS = {"registry_ids", "registries", "diseases", "phenotypes", "phase", "drugs", "comparator_drugs", "chembl_ids",
                "mechanism_families", "mechanism_nodes", "nondrug_categories", "intervention_types",
                "primary_endpoint_tags", "countries"}
TRIAL_DATES = {"start_date", "primary_completion_date", "completion_date", "last_update", "results_first_posted"}
TRIAL_INTS = {"tier", "start_year", "enrollment", "n_arms", "n_countries", "n_result_pmids", "n_europepmc_mentions",
              "n_europepmc_trial_reports", "n_unmatched_drug_names"}
TRIAL_BOOLS = {"status_inferred", "has_placebo_or_sham", "has_posted_results"}


# ------------------------------------------------------------------ value cleaning
def missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NA or v is pd.NaT or v == ""


def arr(v):
    return None if missing(v) else [x for x in str(v).split("|") if x]


def d(v):
    if missing(v):
        return None
    s = str(v)[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}", s[:7]):
        return date.fromisoformat(s[:7] + "-01")
    return None


def i(v):
    if missing(v):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def b(v):
    if missing(v):
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def t(v):
    return None if missing(v) else str(v)


def clean_trial(r):
    out = {}
    for k, v in r.items():
        if k in TRIAL_ARRAYS:
            out[k] = arr(v)
        elif k in TRIAL_DATES:
            out[k] = d(v)
        elif k in TRIAL_INTS:
            out[k] = i(v)
        elif k in TRIAL_BOOLS:
            out[k] = b(v)
        elif k in ("min_age_years", "max_age_years"):
            out[k] = None if missing(v) else float(v)
        else:
            out[k] = t(v)
    return out


# ------------------------------------------------------------------ main
def main():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("Set SUPABASE_DB_URL (Supabase → Connect → Session pooler connection string).")
    stats = json.loads((DATA / "build_stats.json").read_text()) if (DATA / "build_stats.json").exists() else {}
    trials = pd.read_parquet(DATA / "trials.parquet")
    db_cols_needed = None

    with psycopg.connect(url, autocommit=False) as conn:
        cur = conn.cursor()
        cur.execute("insert into bank.load_runs (build_version, build_stats) values (%s, %s) returning id",
                    (stats.get("version"), Jsonb(stats)))
        run_id = cur.fetchone()[0]
        conn.commit()
        try:
            cur.execute("""select column_name from information_schema.columns
                           where table_schema='bank' and table_name='trials'""")
            db_cols = {r[0] for r in cur.fetchall()}
            cols = [c for c in trials.columns if c in db_cols]
            skipped = [c for c in trials.columns if c not in db_cols]
            if skipped:
                print("columns not in bank.trials (ignored):", skipped)

            # ---- stage trials
            cur.execute("create temp table stage_trials (like bank.trials including defaults) on commit drop")
            rows = [clean_trial(r) for r in trials[cols].to_dict("records")]
            with cur.copy(f"copy stage_trials ({', '.join(cols)}) from stdin") as cp:
                for r in rows:
                    cp.write_row([r[c] for c in cols])

            # ---- change log for tracked registry facts (only trials we already had)
            for f in TRACKED:
                cur.execute(f"""
                    insert into bank.change_log (run_id, msf_trial_id, field, old_value, new_value)
                    select %s, s.msf_trial_id, %s, to_jsonb(b.{f}), to_jsonb(s.{f})
                    from stage_trials s join bank.trials b using (msf_trial_id)
                    where b.{f} is distinct from s.{f}""", (run_id, f))
            cur.execute("""
                insert into bank.change_log (run_id, msf_trial_id, field, old_value, new_value)
                select %s, s.msf_trial_id, 'in_scope', 'false'::jsonb, 'true'::jsonb
                from stage_trials s join bank.trials b using (msf_trial_id) where not b.in_scope""", (run_id,))
            cur.execute("select count(distinct msf_trial_id) from bank.change_log where run_id = %s", (run_id,))
            n_changed = cur.fetchone()[0]
            cur.execute("select count(*) from stage_trials s where not exists (select 1 from bank.trials b where b.msf_trial_id = s.msf_trial_id)")
            n_new = cur.fetchone()[0]

            # ---- upsert trials
            set_cols = [c for c in cols if c != "msf_trial_id"]
            cur.execute(f"""
                insert into bank.trials ({', '.join(cols)}, in_scope, first_seen_run, last_seen_run, updated_at)
                select {', '.join(cols)}, true, %s, %s, now() from stage_trials
                on conflict (msf_trial_id) do update set
                  {', '.join(f'{c} = excluded.{c}' for c in set_cols)},
                  in_scope = true, last_seen_run = excluded.last_seen_run, updated_at = now()""", (run_id, run_id))
            # trials that dropped out of the build: keep, flag, log
            cur.execute("""
                with gone as (
                  update bank.trials set in_scope = false, updated_at = now()
                  where in_scope and msf_trial_id not in (select msf_trial_id from stage_trials)
                  returning msf_trial_id)
                insert into bank.change_log (run_id, msf_trial_id, field, old_value, new_value)
                select %s, msf_trial_id, 'in_scope', 'true'::jsonb, 'false'::jsonb from gone""", (run_id,))
            n_dropped = cur.rowcount

            # ---- child tables: replace rows for every trial in this build
            ids = list(trials.msf_trial_id)
            for tbl in ("trial_registry_ids", "trial_interventions", "trial_outcomes", "trial_primary_analyses", "trial_publications"):
                cur.execute(f"delete from bank.{tbl} where msf_trial_id = any(%s)", (ids,))

            load_child(cur, DATA / "trial_registry_ids.parquet", "trial_registry_ids", keep_ids=set(ids), spec=
                       {"msf_trial_id": t, "registry": t, "registry_id": t, "id_type": t, "other_id": t},
                       dedupe=["msf_trial_id", "registry_id", "other_id"])
            load_child(cur, DATA / "trial_interventions.parquet", "trial_interventions", keep_ids=set(ids), spec=
                       {"msf_trial_id": t, "registry": t, "registry_id": t, "role": t, "intervention_type": t, "name_raw": t,
                        "other_names": t, "chembl_id": t, "drug_name": t, "molecule_type": t, "max_phase_any_indication": t,
                        "mechanism_of_action": t, "action_type": t, "targets": arr, "atc_codes": arr, "atc_level3": arr,
                        "normalisation": t, "mechanism_nodes": arr, "mechanism_families": arr, "nondrug_category": t})
            load_child(cur, DATA / "trial_outcomes.parquet", "trial_outcomes", keep_ids=set(ids), spec=
                       {"msf_trial_id": t, "registry": t, "registry_id": t, "outcome_kind": t, "measure": t,
                        "time_frame": t, "endpoint_tags": arr})
            load_child(cur, DATA / "trial_primary_analyses_ctgov.parquet", "trial_primary_analyses", keep_ids=set(ids), spec=
                       {"msf_trial_id": t, "registry_id": t, "outcome_title": t, "endpoint_tags": arr, "p_value_raw": t,
                        "p_value": lambda v: None if missing(v) else float(v), "p_op": t, "method": t, "param_type": t,
                        "param_value": t, "ci_lower": t, "ci_upper": t, "non_inferiority_type": t})
            pubs = pd.read_parquet(DATA / "trial_publications.parquet").assign(source="registry_link")
            pubs = pubs.rename(columns={"registry_id": "matched_registry_id", "citation": "title"})
            epmc_path = DATA / "trial_publications_europepmc.parquet"
            if epmc_path.exists():
                pubs = pd.concat([pubs, pd.read_parquet(epmc_path)], ignore_index=True)
            load_child(cur, pubs, "trial_publications", keep_ids=set(ids), spec=
                       {"msf_trial_id": t, "source": t, "matched_registry_id": t, "pmid": t, "pmcid": t, "doi": t,
                        "title": t, "journal": t, "pub_year": i, "pub_type": t, "ref_type": t,
                        "is_trial_report_type": b})

            # ---- reference tables (full replace)
            cur.execute("delete from bank.drugs")
            load_child(cur, DATA / "drugs.parquet", "drugs",
                       {"chembl_id": t, "drug_name": t, "molecule_type": t, "max_phase_any_indication": t,
                        "mechanism_of_action": t, "targets": arr, "atc_level3": arr, "mechanism_nodes": arr,
                        "mechanism_families": arr, "n_trials": i, "n_trials_as_comparator": i, "n_interventional": i,
                        "n_phase3": i, "n_progressive_population": i, "n_terminated": i, "n_primary_p_lt_005": i,
                        "n_primary_p_ge_005": i, "first_trial_start": d, "latest_trial_start": d, "raw_names_seen": arr},
                       dedupe=["chembl_id"])
            cur.execute("delete from bank.mechanism_nodes")
            nodes = pd.read_parquet(DATA / "mechanism_nodes.parquet").assign(map_version=stats.get("mechanism_map"))
            load_child(cur, nodes, "mechanism_nodes",
                       {"node_id": t, "family": t, "label": t, "rule_regex": t, "n_trials": i, "map_version": t})

            # ---- sync curation file into corrections (authored as 'curation_file')
            ov_path = ROOT / "curation" / "overrides.csv"
            if ov_path.exists():
                ov = pd.read_csv(ov_path)
                cur.execute("delete from bank.corrections where created_by = 'curation_file'")
                for _, o in ov.iterrows():
                    val = arr(o.value) if o.field in TRIAL_ARRAYS else t(o.value)
                    cur.execute("""
                        insert into bank.corrections (table_name, row_key, field, value, source_url, note, created_by)
                        select 'trials', %s, %s, %s, %s, %s, 'curation_file'
                        where exists (select 1 from bank.trials where msf_trial_id = %s)
                          and not exists (select 1 from bank.corrections c where c.row_key = %s and c.field = %s
                                          and c.active and c.created_by <> 'curation_file')""",
                                (o.msf_trial_id, o.field, Jsonb(val), t(o.source_url), t(o.note), o.msf_trial_id,
                                 o.msf_trial_id, o.field))

            cur.execute("select bank.refresh_trials_current()")
            cur.execute("select bank.rebuild_edges()")
            n_edges = cur.fetchone()[0]
            cur.execute("""update bank.load_runs set finished_at = now(), n_trials = %s, n_new = %s, n_changed = %s,
                           n_dropped = %s where id = %s""", (len(trials), n_new, n_changed, n_dropped, run_id))
            conn.commit()
            print(f"run {run_id}: {len(trials)} trials ({n_new} new, {n_changed} changed, {n_dropped} dropped), {n_edges} edges")
        except Exception as e:
            conn.rollback()
            cur.execute("update bank.load_runs set finished_at = now(), error = %s where id = %s", (str(e)[:2000], run_id))
            conn.commit()
            raise


def load_child(cur, src, table, spec, dedupe=None, keep_ids=None):
    df = src if isinstance(src, pd.DataFrame) else pd.read_parquet(src)
    if keep_ids is not None and "msf_trial_id" in df.columns:
        df = df[df.msf_trial_id.isin(keep_ids)]
    if dedupe:
        df = df.drop_duplicates(dedupe)
    cols = list(spec)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    with cur.copy(f"copy bank.{table} ({', '.join(cols)}) from stdin") as cp:
        for r in df[cols].itertuples(index=False):
            cp.write_row([spec[c](v) for c, v in zip(cols, r)])


if __name__ == "__main__":
    main()
