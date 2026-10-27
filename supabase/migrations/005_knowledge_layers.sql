-- 005_knowledge_layers.sql — results, treatments, safety signals, measures and failures
-- Run after 003. Safe to re-run. Every table here is machine-assembled and fully replaced by the weekly
-- loader; nothing in it is human-reviewed.

-- ------------------------------------------------------------------ results (posted registry results)
create table if not exists bank.trial_results (
  id                       bigint generated always as identity primary key,
  msf_trial_id             text not null references bank.trials(msf_trial_id) on delete cascade,
  registry_id              text,
  outcome_type             text,       -- primary | secondary | other_pre_specified | post_hoc
  outcome_title            text,
  endpoint_tags            text[],
  time_frame               text,
  class_title              text,
  category_title           text,
  arm_title                text,
  arm_is_placebo           boolean,
  arm_drugs                text[],
  n_analysed               int,
  param_type               text,
  value                    double precision,
  value_raw                text,
  unit                     text,
  dispersion_type          text,
  spread                   double precision,
  lower_limit              double precision,
  upper_limit              double precision,
  analysis_p_value_raw     text,
  analysis_p_value         double precision,
  analysis_estimate_type   text,
  analysis_estimate        text,
  analysis_ci_lower        text,
  analysis_ci_upper        text,
  source                   text,
  extraction_method        text
);
create index if not exists trial_results_trial_idx on bank.trial_results (msf_trial_id);
create index if not exists trial_results_tags_idx on bank.trial_results using gin (endpoint_tags);
create index if not exists trial_results_drugs_idx on bank.trial_results using gin (arm_drugs);

create table if not exists bank.trial_arm_safety (
  id               bigint generated always as identity primary key,
  msf_trial_id     text not null references bank.trials(msf_trial_id) on delete cascade,
  registry_id      text,
  arm_title        text,
  arm_is_placebo   boolean,
  arm_drugs        text[],
  at_risk          int,
  serious_affected int,
  deaths           int,
  other_affected   int,
  source           text
);
create index if not exists trial_arm_safety_trial_idx on bank.trial_arm_safety (msf_trial_id);

-- ------------------------------------------------------------------ treatments
create table if not exists bank.treatments (
  treatment_id                      text primary key,      -- ChEMBL id, or name:<inn> when ChEMBL has none
  name                              text not null,
  other_names                       text[],
  chembl_id                         text,
  molecule_type                     text,
  category                          text,                  -- disease_modifying | nmosd_mogad_treatment | symptom_treatment | relapse_treatment
  diseases                          text[],
  mechanism_of_action               text,
  targets                           text[],
  mechanism_nodes                   text[],
  mechanism_families                text[],
  eu_status                         text,
  eu_first_authorisation            date,
  eu_brands                         text[],
  eu_generics_or_biosimilars        int,
  eu_additional_monitoring          boolean,
  us_first_approval_ms_product      date,
  us_first_approval_any_indication  date,
  us_brands                         text[],
  us_generic_applications           int,
  n_ema_safety_letters              int,
  faers_reports                     int,
  faers_serious_reports             int,
  n_trials                          int,
  n_trials_as_comparator            int,
  n_phase3_trials                   int,
  availability_note                 text,
  assembled_by                      text,
  sources                           text,
  updated_at                        timestamptz not null default now()
);

create table if not exists bank.treatment_products (
  id                     bigint generated always as identity primary key,
  treatment_id           text not null references bank.treatments(treatment_id) on delete cascade,
  region                 text,      -- EU/EEA | US
  product_name           text,
  status                 text,
  generic                boolean,
  biosimilar             boolean,
  conditional_approval   boolean,
  additional_monitoring  boolean,
  holder                 text,
  authorisation_date     date,
  refusal_date           date,
  withdrawal_date        date,
  indication             text,
  url                    text,
  source                 text
);
create index if not exists treatment_products_t_idx on bank.treatment_products (treatment_id);

create table if not exists bank.treatment_safety_signals (
  id            bigint generated always as identity primary key,
  treatment_id  text not null references bank.treatments(treatment_id) on delete cascade,
  substance     text,
  type          text,      -- EMA safety letter (DHPC) | EMA referral
  title         text,
  date          date,
  url           text,
  source        text
);

create table if not exists bank.treatment_adverse_event_reports (
  id            bigint generated always as identity primary key,
  treatment_id  text not null references bank.treatments(treatment_id) on delete cascade,
  substance     text,
  reaction      text,
  reports       int
);

create table if not exists bank.regulatory_events (
  id            bigint generated always as identity primary key,
  treatment_id  text references bank.treatments(treatment_id) on delete cascade,
  substance     text,
  region        text,
  event         text,      -- refused | withdrawn | revoked | application withdrawn | suspended
  product_name  text,
  date          date,
  url           text,
  source        text
);

-- ------------------------------------------------------------------ measures dictionary
create table if not exists bank.measures (
  measure_id                 text primary key,
  name                       text not null,
  short_name                 text,
  kind                       text,
  endpoint_tag               text,
  what_it_is                 text,
  how_trials_use_it          text,
  n_trials_measuring         int,
  n_trials_primary_endpoint  int,
  further_reading            text,
  written_by                 text,
  as_of                      date
);

-- ------------------------------------------------------------------ failures (registry-evidenced only)
create or replace view bank.failures with (security_invoker = true) as
select t.msf_trial_id, t.acronym, t.title, t.url, t.phase, t.population_group, t.diseases, t.drugs, t.comparator_drugs,
       t.mechanism_families, t.mechanism_nodes, t.primary_endpoint_class, t.enrollment, t.start_year,
       t.completion_date, t.status, t.why_stopped, t.result_signal,
       case
         when t.result_signal = 'primary_p_ge_0.05'             then 'primary_endpoint_not_met'
         when t.result_signal like 'terminated:futility%'      then 'stopped_for_lack_of_efficacy'
         when t.result_signal like 'withdrawn:futility%'       then 'stopped_for_lack_of_efficacy'
         when t.result_signal like 'terminated:safety%'        then 'stopped_for_safety'
       end as failure_type,
       'registry' as evidence_source
from bank.trials_current t
where t.in_scope and t.study_type = 'interventional'
  and (t.result_signal = 'primary_p_ge_0.05'
       or t.result_signal like 'terminated:futility%' or t.result_signal like 'withdrawn:futility%'
       or t.result_signal like 'terminated:safety%');

-- ------------------------------------------------------------------ graph edges for the new layers
create or replace function bank.rebuild_layer_edges() returns int language plpgsql as $$
declare n_new int;
begin
  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'drug', coalesce(tr.chembl_id, tr.treatment_id), 'approved_for', 'disease', d,
         jsonb_build_object('eu_first_authorisation', tr.eu_first_authorisation,
                            'us_first_approval', tr.us_first_approval_ms_product, 'category', tr.category),
         'EMA / Drugs@FDA'
  from bank.treatments tr, unnest(tr.diseases) d
  where tr.eu_status = 'authorised' or tr.us_first_approval_ms_product is not null;

  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'trial', f.msf_trial_id, 'failed', 'outcome', f.failure_type,
         jsonb_build_object('result_signal', f.result_signal), 'registry'
  from bank.failures f;

  get diagnostics n_new = row_count;
  return n_new;
end $$;

-- ------------------------------------------------------------------ access: open read, loader writes
do $$
declare t text;
begin
  foreach t in array array['trial_results','trial_arm_safety','treatments','treatment_products','treatment_safety_signals',
                           'treatment_adverse_event_reports','regulatory_events','measures']
  loop
    execute format('alter table bank.%I enable row level security', t);
    execute format('drop policy if exists public_read on bank.%I', t);
    execute format('create policy public_read on bank.%I for select using (true)', t);
    execute format('grant select on bank.%I to anon, authenticated', t);
    execute format('grant all on bank.%I to service_role', t);
  end loop;
end $$;
grant select on bank.failures to anon, authenticated;
grant usage on all sequences in schema bank to service_role;
grant execute on function bank.rebuild_layer_edges() to service_role;
