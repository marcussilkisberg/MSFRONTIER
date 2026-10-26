-- 003_trial_bank.sql — MSFrontier Trial Bank
-- Safe to re-run. Creates everything in a separate schema, "bank", so it never
-- touches the ledger tables from 001/002 (which already include a public.trials).
--
-- How the data is maintained:
--   * bank.trials and its child tables hold MACHINE values. The loader overwrites them on every run.
--   * bank.corrections holds HUMAN corrections. The loader never touches them.
--   * bank.trials_current = machine values with active corrections laid on top. Read from this.
--   * bank.change_log records every change the loader makes to tracked registry facts.
--   * bank.edges is the knowledge graph, rebuilt from the tables by bank.rebuild_edges().

create schema if not exists bank;

-- ------------------------------------------------------------------ runs
create table if not exists bank.load_runs (
  id            bigint generated always as identity primary key,
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  build_version text,
  build_stats   jsonb,
  n_trials      int,
  n_new         int,
  n_changed     int,
  n_dropped     int,
  error         text
);

-- ------------------------------------------------------------------ trials
create table if not exists bank.trials (
  msf_trial_id              text primary key,
  registry_ids              text[] not null,
  registries                text[] not null,
  url                       text,
  title                     text,
  official_title            text,
  acronym                   text,
  org_study_id              text,
  tier                      smallint,
  in_scope                  boolean not null default true,
  diseases                  text[],
  ms_focus                  text,
  population_group          text,
  phenotypes                text[],
  study_type                text,
  phase                     text[],
  status                    text,
  status_inferred           boolean,
  result_signal             text,
  start_year                smallint,
  start_date                date,
  primary_completion_date   date,
  completion_date           date,
  last_update               date,
  enrollment                int,
  enrollment_type           text,
  allocation                text,
  masking                   text,
  intervention_model        text,
  n_arms                    smallint,
  has_placebo_or_sham       boolean,
  primary_purpose           text,
  drugs                     text[],
  comparator_drugs          text[],
  chembl_ids                text[],
  mechanism_families        text[],
  mechanism_nodes           text[],
  nondrug_categories        text[],
  intervention_types        text[],
  primary_endpoint_class    text,
  primary_endpoint_tags     text[],
  lead_sponsor              text,
  sponsor_class             text,
  n_countries               smallint,
  countries                 text[],
  why_stopped               text,
  why_stopped_class         text,
  has_posted_results        boolean,
  results_first_posted      date,
  n_result_pmids            int,
  n_europepmc_mentions      int,
  n_europepmc_trial_reports int,
  n_unmatched_drug_names    int,
  min_age_years             numeric,
  max_age_years             numeric,
  conditions_raw            text,
  interventions_raw         text,
  mesh_interventions        text,
  tag_method                text,
  review_status             text not null default 'machine_tagged',
  curation_note             text,
  first_seen_run            bigint references bank.load_runs(id),
  last_seen_run             bigint references bank.load_runs(id),
  updated_at                timestamptz not null default now()
);
alter table bank.trials add column if not exists curation_note text;  -- for databases created by an earlier draft
create index if not exists trials_population_idx on bank.trials (population_group);
create index if not exists trials_status_idx     on bank.trials (status);
create index if not exists trials_signal_idx     on bank.trials (result_signal);
create index if not exists trials_drugs_idx      on bank.trials using gin (drugs);
create index if not exists trials_nodes_idx      on bank.trials using gin (mechanism_nodes);
create index if not exists trials_regids_idx     on bank.trials using gin (registry_ids);

-- ------------------------------------------------------------------ child tables (replaced per trial on each load)
create table if not exists bank.trial_registry_ids (
  msf_trial_id text not null references bank.trials(msf_trial_id) on delete cascade,
  registry     text not null,
  registry_id  text not null,
  id_type      text not null,
  other_id     text not null,
  primary key (msf_trial_id, registry_id, other_id)
);
create index if not exists trial_registry_ids_other_idx on bank.trial_registry_ids (other_id);

create table if not exists bank.trial_interventions (
  id                        bigint generated always as identity primary key,
  msf_trial_id              text not null references bank.trials(msf_trial_id) on delete cascade,
  registry                  text,
  registry_id               text,
  role                      text,          -- experimental | active_comparator | placebo_or_sham
  intervention_type         text,
  name_raw                  text,
  other_names               text,
  chembl_id                 text,
  drug_name                 text,
  molecule_type             text,
  max_phase_any_indication  text,
  mechanism_of_action       text,
  action_type               text,
  targets                   text[],
  atc_codes                 text[],
  atc_level3                text[],
  normalisation             text,
  mechanism_nodes           text[],
  mechanism_families        text[],
  nondrug_category          text
);
create index if not exists trial_interventions_trial_idx on bank.trial_interventions (msf_trial_id);
create index if not exists trial_interventions_chembl_idx on bank.trial_interventions (chembl_id);

create table if not exists bank.trial_outcomes (
  id            bigint generated always as identity primary key,
  msf_trial_id  text not null references bank.trials(msf_trial_id) on delete cascade,
  registry      text,
  registry_id   text,
  outcome_kind  text,   -- primary | secondary
  measure       text,
  time_frame    text,
  endpoint_tags text[]
);
create index if not exists trial_outcomes_trial_idx on bank.trial_outcomes (msf_trial_id);

create table if not exists bank.trial_primary_analyses (
  id                   bigint generated always as identity primary key,
  msf_trial_id         text not null references bank.trials(msf_trial_id) on delete cascade,
  registry_id          text,
  outcome_title        text,
  endpoint_tags        text[],
  p_value_raw          text,
  p_value              double precision,
  p_op                 text,
  method               text,
  param_type           text,
  param_value          text,
  ci_lower             text,
  ci_upper             text,
  non_inferiority_type text
);
create index if not exists trial_primary_analyses_trial_idx on bank.trial_primary_analyses (msf_trial_id);

create table if not exists bank.trial_publications (
  id                   bigint generated always as identity primary key,
  msf_trial_id         text not null references bank.trials(msf_trial_id) on delete cascade,
  source               text not null,  -- registry_link | europepmc_registry_id_mention
  matched_registry_id  text,
  pmid                 text,
  pmcid                text,
  doi                  text,
  title                text,
  journal              text,
  pub_year             smallint,
  pub_type             text,
  ref_type             text,
  is_trial_report_type boolean
);
create index if not exists trial_publications_trial_idx on bank.trial_publications (msf_trial_id);
create index if not exists trial_publications_pmid_idx  on bank.trial_publications (pmid);

-- ------------------------------------------------------------------ reference tables
create table if not exists bank.drugs (
  chembl_id                 text primary key,
  drug_name                 text,
  molecule_type             text,
  max_phase_any_indication  text,
  mechanism_of_action       text,
  targets                   text[],
  atc_level3                text[],
  mechanism_nodes           text[],
  mechanism_families        text[],
  n_trials                  int,
  n_trials_as_comparator    int,
  n_interventional          int,
  n_phase3                  int,
  n_progressive_population  int,
  n_terminated              int,
  n_primary_p_lt_005        int,
  n_primary_p_ge_005        int,
  first_trial_start         date,
  latest_trial_start        date,
  raw_names_seen            text[],
  updated_at                timestamptz not null default now()
);

create table if not exists bank.mechanism_nodes (
  node_id    text primary key,
  family     text not null,
  label      text not null,
  rule_regex text,
  n_trials   int,
  map_version text
);

-- ------------------------------------------------------------------ human corrections (never overwritten by bots)
create table if not exists bank.corrections (
  id           bigint generated always as identity primary key,
  table_name   text not null default 'trials' check (table_name in ('trials')),
  row_key      text not null,            -- msf_trial_id
  field        text not null,            -- column name in bank.trials
  value        jsonb not null,           -- e.g. "progressive" or ["metformin","thioctic acid"]
  source_url   text,
  note         text,
  created_by   text,                     -- editor email, or 'curation_file'
  created_at   timestamptz not null default now(),
  active       boolean not null default true
);
create unique index if not exists corrections_one_active
  on bank.corrections (table_name, row_key, field) where active;

-- refuse corrections to columns that don't exist
create or replace function bank.check_correction_field() returns trigger language plpgsql as $$
begin
  if not exists (select 1 from information_schema.columns
                 where table_schema = 'bank' and table_name = new.table_name and column_name = new.field) then
    raise exception 'bank.%: no column named %', new.table_name, new.field;
  end if;
  if new.field in ('msf_trial_id', 'first_seen_run', 'last_seen_run', 'updated_at') then
    raise exception 'field % cannot be corrected', new.field;
  end if;
  return new;
end $$;
drop trigger if exists corrections_field_check on bank.corrections;
create trigger corrections_field_check before insert or update on bank.corrections
  for each row execute function bank.check_correction_field();

-- trials with corrections applied: the table everything should read.
-- A materialized view (fast to join and filter), refreshed by the loader and
-- automatically whenever a correction is added, changed or removed.
do $$ begin
  if exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'bank' and c.relname = 'trials_current' and c.relkind = 'v') then
    drop view bank.trials_current;
  end if;
end $$;
drop materialized view if exists bank.trials_current;
create materialized view bank.trials_current as
with patches as (
  select row_key, jsonb_object_agg(field, value) as patch, array_agg(field order by field) as corrected_fields
  from bank.corrections where table_name = 'trials' and active
  group by row_key
)
select t.*, '{}'::text[] as corrected_fields
from bank.trials t
where not exists (select 1 from patches p where p.row_key = t.msf_trial_id)
union all
select (jsonb_populate_record(t, to_jsonb(t) || p.patch || jsonb_build_object('review_status', 'partly_curated'))).*,
       p.corrected_fields
from bank.trials t join patches p on p.row_key = t.msf_trial_id;
create unique index trials_current_pk on bank.trials_current (msf_trial_id);
create index trials_current_population_idx on bank.trials_current (population_group);
create index trials_current_drugs_idx on bank.trials_current using gin (drugs);
create index trials_current_nodes_idx on bank.trials_current using gin (mechanism_nodes);

create or replace function bank.refresh_trials_current() returns void
language plpgsql security definer set search_path = bank, public as $$
begin
  refresh materialized view bank.trials_current;
end $$;

create or replace function bank.on_corrections_change() returns trigger
language plpgsql security definer set search_path = bank, public as $$
begin
  perform bank.refresh_trials_current();
  return null;
end $$;
drop trigger if exists corrections_refresh on bank.corrections;
create trigger corrections_refresh after insert or update or delete on bank.corrections
  for each statement execute function bank.on_corrections_change();

-- ------------------------------------------------------------------ change log (registry facts only)
create table if not exists bank.change_log (
  id           bigint generated always as identity primary key,
  run_id       bigint references bank.load_runs(id),
  msf_trial_id text not null,
  field        text not null,
  old_value    jsonb,
  new_value    jsonb,
  changed_at   timestamptz not null default now()
);
create index if not exists change_log_trial_idx on bank.change_log (msf_trial_id);
create index if not exists change_log_run_idx on bank.change_log (run_id);

-- ------------------------------------------------------------------ knowledge graph
create table if not exists bank.edges (
  id            bigint generated always as identity primary key,
  src_type      text not null,   -- trial | drug | target | mechanism | population | endpoint | publication | disease | sponsor
  src_id        text not null,
  relation      text not null,   -- tests | compares_against | acts_on | assigned_to | studied_in | measures | reported_in | about | sponsored_by | part_of
  dst_type      text not null,
  dst_id        text not null,
  properties    jsonb not null default '{}'::jsonb,
  origin        text not null default 'machine',  -- machine | reviewed (reviewed edges survive rebuilds)
  review_status text not null default 'machine_tagged',
  source        text,
  created_at    timestamptz not null default now()
);
create index if not exists edges_src_idx on bank.edges (src_type, src_id);
create index if not exists edges_dst_idx on bank.edges (dst_type, dst_id);
create index if not exists edges_rel_idx on bank.edges (relation);

create or replace function bank.rebuild_edges() returns int language plpgsql as $$
declare n_edges int;
begin
  delete from bank.edges where origin = 'machine';

  -- trial -> drug (experimental) / comparator drug
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select distinct 'trial', i.msf_trial_id,
         case when i.role = 'experimental' then 'tests' else 'compares_against' end,
         'drug', i.chembl_id, jsonb_build_object('drug_name', i.drug_name), 'registry+chembl'
  from bank.trial_interventions i
  where i.chembl_id is not null and i.role in ('experimental', 'active_comparator');

  -- drug -> target (with action type)
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select distinct on (i.chembl_id, tg) 'drug', i.chembl_id, 'acts_on', 'target', tg,
         jsonb_build_object('action_type', i.action_type, 'mechanism_of_action', i.mechanism_of_action), 'chembl'
  from bank.trial_interventions i, unnest(i.targets) tg
  where i.chembl_id is not null;

  -- drug -> mechanism node
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, source)
  select distinct 'drug', d.chembl_id, 'assigned_to', 'mechanism', mn, 'mechanism_map'
  from bank.drugs d, unnest(d.mechanism_nodes) mn;

  -- mechanism node -> family
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, source)
  select 'mechanism', node_id, 'part_of', 'mechanism_family', family, 'mechanism_map' from bank.mechanism_nodes;

  -- trial -> disease, population, endpoint, sponsor
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, source)
  select 'trial', t.msf_trial_id, 'about', 'disease', d, 'registry' from bank.trials_current t, unnest(t.diseases) d where t.in_scope;
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, source)
  select 'trial', t.msf_trial_id, 'studied_in', 'population', t.population_group, 'rules'
  from bank.trials_current t where t.in_scope and t.population_group is not null;
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'trial', t.msf_trial_id, 'measures', 'endpoint', e, jsonb_build_object('primary', true), 'rules'
  from bank.trials_current t, unnest(t.primary_endpoint_tags) e where t.in_scope;
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'trial', t.msf_trial_id, 'sponsored_by', 'sponsor', t.lead_sponsor, jsonb_build_object('class', t.sponsor_class), 'registry'
  from bank.trials_current t where t.in_scope and t.lead_sponsor is not null;

  -- trial -> publication
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select distinct on (p.msf_trial_id, coalesce(p.pmid, p.doi, p.pmcid))
         'trial', p.msf_trial_id, 'reported_in', 'publication', coalesce('pmid:' || p.pmid, 'doi:' || p.doi, 'pmc:' || p.pmcid),
         jsonb_build_object('is_trial_report_type', p.is_trial_report_type, 'pub_year', p.pub_year), p.source
  from bank.trial_publications p
  where coalesce(p.pmid, p.doi, p.pmcid) is not null;

  select count(*) into n_edges from bank.edges;
  return n_edges;
end $$;

-- ------------------------------------------------------------------ access
-- The data is open: anyone may read. Only the loader (service role, which bypasses RLS)
-- writes machine tables. Editors may write corrections.
alter table bank.load_runs              enable row level security;
alter table bank.trials                 enable row level security;
alter table bank.trial_registry_ids     enable row level security;
alter table bank.trial_interventions    enable row level security;
alter table bank.trial_outcomes         enable row level security;
alter table bank.trial_primary_analyses enable row level security;
alter table bank.trial_publications     enable row level security;
alter table bank.drugs                  enable row level security;
alter table bank.mechanism_nodes        enable row level security;
alter table bank.corrections            enable row level security;
alter table bank.change_log             enable row level security;
alter table bank.edges                  enable row level security;

do $$
declare t text;
begin
  foreach t in array array['trials','trial_registry_ids','trial_interventions','trial_outcomes','trial_primary_analyses',
                           'trial_publications','drugs','mechanism_nodes','change_log','edges','load_runs','corrections']
  loop
    execute format('drop policy if exists public_read on bank.%I', t);
    execute format('create policy public_read on bank.%I for select using (true)', t);
  end loop;
end $$;

-- security definer, so the check works whatever RLS public.editors has
create or replace function bank.is_editor() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.editors e where e.user_id = auth.uid())
$$;
revoke all on function bank.is_editor() from public;
grant execute on function bank.is_editor() to authenticated;

drop policy if exists editors_write on bank.corrections;
create policy editors_write on bank.corrections for all to authenticated
  using (bank.is_editor()) with check (bank.is_editor());

grant usage on schema bank to anon, authenticated, service_role;
grant select on all tables in schema bank to anon, authenticated;
grant insert, update on bank.corrections to authenticated;
grant all on all tables in schema bank to service_role;
grant all on all sequences in schema bank to service_role;
grant usage on all sequences in schema bank to authenticated;
grant execute on function bank.rebuild_edges() to service_role;
grant execute on function bank.refresh_trials_current() to service_role;
revoke all on function bank.refresh_trials_current() from public, anon, authenticated;
