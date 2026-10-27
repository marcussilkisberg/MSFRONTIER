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

            # ---- knowledge layers (005), loaded when their files exist and the tables are there
            load_layers(cur, set(ids))
            # ---- hypothesis ledger, genetics and the Project (006)
            load_hypotheses(cur, set(ids), run_id)

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
            if has_table(cur, "treatments"):
                cur.execute("select bank.rebuild_layer_edges()")
            if has_table(cur, "hypotheses"):
                cur.execute("select bank.rebuild_hypothesis_edges()")
                cur.execute("select count(*) from bank.edges")
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


def has_table(cur, name):
    cur.execute("select to_regclass(%s) is not null", (f"bank.{name}",))
    return cur.fetchone()[0]


def load_layers(cur, keep_ids):
    """Results, treatments and measures layers: full machine replace on every run."""
    f = lambda n: DATA / f"{n}.parquet"
    if not has_table(cur, "trial_results"):
        print("migration 005 not applied: skipping knowledge layers")
        return
    num = lambda v: None if missing(v) else float(v)
    if f("trial_results").exists():
        cur.execute("delete from bank.trial_results where msf_trial_id = any(%s)", (list(keep_ids),))
        load_child(cur, f("trial_results"), "trial_results", keep_ids=keep_ids, spec={
            "msf_trial_id": t, "registry_id": t, "outcome_type": t, "outcome_title": t, "endpoint_tags": arr,
            "time_frame": t, "class_title": t, "category_title": t, "arm_title": t, "arm_is_placebo": b,
            "arm_drugs": arr, "n_analysed": i, "param_type": t, "value": num, "value_raw": t, "unit": t,
            "dispersion_type": t, "spread": num, "lower_limit": num, "upper_limit": num,
            "analysis_p_value_raw": t, "analysis_p_value": num, "analysis_estimate_type": t,
            "analysis_estimate": t, "analysis_ci_lower": t, "analysis_ci_upper": t, "source": t,
            "extraction_method": t})
    if f("trial_arm_safety").exists():
        cur.execute("delete from bank.trial_arm_safety where msf_trial_id = any(%s)", (list(keep_ids),))
        load_child(cur, f("trial_arm_safety"), "trial_arm_safety", keep_ids=keep_ids, spec={
            "msf_trial_id": t, "registry_id": t, "arm_title": t, "arm_is_placebo": b, "arm_drugs": arr,
            "at_risk": i, "serious_affected": i, "deaths": i, "other_affected": i, "source": t})
    if f("treatments").exists():
        cur.execute("delete from bank.treatments")   # cascades to products, signals, AE reports, events
        load_child(cur, f("treatments"), "treatments", dedupe=["treatment_id"], spec={
            "treatment_id": t, "name": t, "other_names": arr, "chembl_id": t, "molecule_type": t, "category": t,
            "diseases": arr, "mechanism_of_action": t, "targets": arr, "mechanism_nodes": arr,
            "mechanism_families": arr, "eu_status": t, "eu_first_authorisation": d, "eu_brands": arr,
            "eu_generics_or_biosimilars": i, "eu_additional_monitoring": b, "us_first_approval_ms_product": d,
            "us_first_approval_any_indication": d, "us_brands": arr, "us_generic_applications": i,
            "n_ema_safety_letters": i, "faers_reports": i, "faers_serious_reports": i, "n_trials": i,
            "n_trials_as_comparator": i, "n_phase3_trials": i, "availability_note": t, "assembled_by": t,
            "sources": t})
        for name, spec in (
                ("treatment_products", {"treatment_id": t, "region": t, "product_name": t, "status": t, "generic": b,
                                        "biosimilar": b, "conditional_approval": b, "additional_monitoring": b,
                                        "holder": t, "authorisation_date": d, "refusal_date": d,
                                        "withdrawal_date": d, "indication": t, "url": t, "source": t}),
                ("treatment_safety_signals", {"treatment_id": t, "substance": t, "type": t, "title": t, "date": d,
                                              "url": t, "source": t}),
                ("treatment_adverse_event_reports", {"treatment_id": t, "substance": t, "reaction": t, "reports": i}),
                ("regulatory_events", {"treatment_id": t, "substance": t, "region": t, "event": t,
                                       "product_name": t, "date": d, "url": t, "source": t})):
            if f(name).exists():
                load_child(cur, f(name), name, spec=spec)
    if f("measures").exists():
        cur.execute("delete from bank.measures")
        load_child(cur, f("measures"), "measures", dedupe=["measure_id"], spec={
            "measure_id": t, "name": t, "short_name": t, "kind": t, "endpoint_tag": t, "what_it_is": t,
            "how_trials_use_it": t, "n_trials_measuring": i, "n_trials_primary_endpoint": i,
            "further_reading": t, "written_by": t, "as_of": d})


def load_hypotheses(cur, keep_ids, run_id):
    """Hypotheses, evidence, readouts, genetic leads and Project files: full machine replace, with a permanent
    week-by-week history of each hypothesis's status, verdict and trial count."""
    f = lambda n: DATA / f"{n}.parquet"
    if not has_table(cur, "hypotheses"):
        print("migration 006 not applied: skipping hypothesis ledger")
        return
    if not f("hypotheses").exists():
        print("no hypotheses.parquet: skipping hypothesis ledger")
        return
    def lst(v):
        if v is None:
            return None
        if isinstance(v, str):
            return arr(v)
        if hasattr(v, "__iter__"):
            return [str(x) for x in v]
        return None if missing(v) else [str(v)]

    new = pd.read_parquet(f("hypotheses"))
    cur.execute("select hypothesis_id, status, verdict, n_trials, outcome from bank.hypotheses")
    old = {r[0]: r[1:] for r in cur.fetchall()}
    hist = []
    for r in new.itertuples():
        o = old.pop(r.hypothesis_id, None)
        if o is None:
            hist.append((r.hypothesis_id, "created", None, r.outcome))
            continue
        for field, ov, nv in (("status", o[0], r.status), ("verdict", o[1], r.verdict),
                              ("n_trials", o[2], int(r.n_trials)), ("outcome", o[3], r.outcome)):
            if str(ov) != str(nv):
                hist.append((r.hypothesis_id, field, None if ov is None else str(ov), str(nv)))
    hist += [(h, "removed", o[1], None) for h, o in old.items()]
    if old or len(new):   # first load records every hypothesis as created; later loads only changes
        cur.executemany("insert into bank.hypothesis_history (hypothesis_id, field, old_value, new_value, run_id) "
                        "values (%s, %s, %s, %s, %s)", [(*h, run_id) for h in hist])

    # each table is replaced only when its file was built this run, so a failed optional step (e.g. Open Targets
    # down) keeps last week's rows instead of emptying the table
    for tbl in ("hypothesis_evidence", "hypotheses"):
        cur.execute(f"delete from bank.{tbl}")
    for tbl, fn in (("trial_readouts", "trial_readouts"), ("genetic_leads", "genetic_leads"),
                    ("drug_targets", "drug_targets"), ("project_hypotheses", "project_hypotheses"),
                    ("project_studies", "project_studies")):
        if f(fn).exists():
            cur.execute(f"delete from bank.{tbl}")
    load_child(cur, new, "hypotheses", dedupe=["hypothesis_id"], spec={
        "hypothesis_id": t, "aim": t, "aim_label": t, "approach": t, "approach_label": t, "approach_group": t,
        "approach_group_label": t, "approach_family": t,
        "population": t, "population_label": t, "statement": t, "status": t, "verdict": t, "verdict_label": t,
        "outcome": t, "outcome_label": t,
        "verdict_note": t, "n_trials": i, "n_ongoing": i, "n_rct_phase2plus": i, "n_participants_rct": i,
        "n_met": i, "n_not_met": i, "n_stopped_safety": i, "n_unread": i, "n_unread_phase3": i,
        "highest_phase": t, "first_trial_year": i, "latest_trial_year": i, "drugs": lst, "target_genes": lst,
        "genetic_support_genes": lst, "project_study_ids": lst, "origin": t, "rules_version": t, "as_of": d})
    load_child(cur, f("hypothesis_evidence"), "hypothesis_evidence", keep_ids=keep_ids, spec={
        "hypothesis_id": t, "msf_trial_id": t, "aim": t, "approach": t, "approach_group": t, "population": t,
        "phase": t, "status": t,
        "state": t, "state_source": t, "is_rct": b, "has_placebo_or_sham": b, "eligible_for_verdict": b,
        "counts_toward_verdict": b, "comparator_drugs": lst, "enrollment": i, "start_year": i, "drugs": lst,
        "acronym": t, "title": t, "primary_endpoint_tags": lst, "readout_quote": t, "readout_pmid": t})
    if f("trial_readouts").exists():
        load_child(cur, f("trial_readouts"), "trial_readouts", keep_ids=keep_ids, dedupe=["msf_trial_id"], spec={
            "msf_trial_id": t, "readout": t, "pmid": t, "quote": t, "pmids_considered": lst, "reader_said": t,
            "checker_said": t, "reason": t, "reader_model": t, "checker_model": t, "prompt_version": t, "read_on": d})
    if f("genetic_leads").exists():
        load_child(cur, f("genetic_leads"), "genetic_leads", dedupe=["ensembl_id"], spec={
            "ensembl_id": t, "symbol": t, "name": t, "genetic_score": lambda v: None if missing(v) else float(v),
            "overall_score": lambda v: None if missing(v) else float(v), "genetic_strength": t, "lead_status": t,
            "n_existing_drugs": i, "existing_drugs": lst, "approved_drugs_any_disease": lst,
            "max_stage_any_drug": t, "bank_chembl_ids": lst, "bank_drug_names": lst, "n_ms_trials": i,
            "ms_trial_ids": lst, "max_ms_phase": t, "partner_genes": lst, "partner_drug_names": lst,
            "n_ms_trials_via_partner": i, "partner_trial_ids": lst, "source": t, "ot_url": t, "as_of": d})
    if f("drug_targets").exists():
        load_child(cur, f("drug_targets"), "drug_targets", spec={
            "chembl_id": t, "drug_name": t, "ensembl_id": t, "symbol": t, "moa": t, "action_type": t,
            "target_source": t})
    if f("project_studies").exists():
        load_child(cur, f("project_studies"), "project_studies", dedupe=["study_id"], spec={
            "study_id": t, "number": i, "title": t, "question": t, "status": t, "target": t, "uses": lst,
            "outputs": lst})
    if f("project_hypotheses").exists():
        load_child(cur, f("project_hypotheses"), "project_hypotheses", dedupe=["id"], spec={
            "id": t, "study": t, "kind": t, "statement": t, "aim": t, "approach": t, "approach_label": t,
            "population": t, "drugs": lst, "status": t, "registered_on": d, "ledger_hypothesis_ids": lst})
    print(f"hypotheses: {len(new)} loaded, {len(hist)} history entries")


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
