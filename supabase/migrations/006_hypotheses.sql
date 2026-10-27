-- 006_hypotheses.sql — hypothesis ledger, paper readouts, genetic leads and the Project's studies
-- Run after 003 and 005. Safe to re-run.
-- Everything here is derived by the weekly pipeline from the trial bank and two files in the repository
-- (project/studies.yml, project/hypotheses.yml). Nothing is linked by hand in the database.

-- ------------------------------------------------------------------ paper readouts (machine-read, gated)
create table if not exists bank.trial_readouts (
  msf_trial_id      text primary key references bank.trials(msf_trial_id) on delete cascade,
  readout           text not null,          -- met | not_met | mixed | unclear
  pmid              text,
  quote             text,                   -- sentence copied word for word from the abstract
  pmids_considered  text[],
  reader_said       text,
  checker_said      text,
  reason            text,                   -- why a readout is 'unclear' (gate that failed)
  reader_model      text,
  checker_model     text,
  prompt_version    text,
  read_on           date
);

-- ------------------------------------------------------------------ hypotheses
create table if not exists bank.hypotheses (
  hypothesis_id          text primary key,  -- H:<aim>:<approach>:<population>, stable from week to week
  aim                    text not null,
  aim_label              text,
  approach               text not null,     -- mechanism node | <node>.<drug> for mixed groups | nd-<category> | new-<slug>
  approach_label         text,
  approach_group         text,              -- the mechanism node (the row on the map)
  approach_group_label   text,
  approach_family        text,
  population             text not null,
  population_label       text,
  statement              text not null,
  status                 text not null,     -- proposed | being_tested | tested
  verdict                text not null,     -- see verdict_label
  verdict_label          text,
  verdict_note           text,
  outcome                text,              -- what the website shows: roadmap | testing | pending | promising |
                                            -- confirmed | mixed | failed_early | disproven | unclear
  outcome_label          text,
  n_trials               int,
  n_ongoing              int,
  n_rct_phase2plus       int,
  n_participants_rct     int,
  n_met                  int,
  n_not_met              int,
  n_stopped_safety       int,
  n_unread               int,
  n_unread_phase3        int,
  highest_phase          text,
  first_trial_year       int,
  latest_trial_year      int,
  drugs                  text[],
  target_genes           text[],
  genetic_support_genes  text[],
  project_study_ids      text[],
  origin                 text,              -- trials | project
  rules_version          text,
  as_of                  date,
  updated_at             timestamptz not null default now()
);
alter table bank.hypotheses add column if not exists approach_group text;
alter table bank.hypotheses add column if not exists outcome text;
alter table bank.hypotheses add column if not exists outcome_label text;
alter table bank.hypotheses add column if not exists approach_group_label text;
create index if not exists hypotheses_aim_idx on bank.hypotheses (aim, approach_group);
create index if not exists hypotheses_pop_idx on bank.hypotheses (population);

create table if not exists bank.hypothesis_evidence (
  id                     bigint generated always as identity primary key,
  hypothesis_id          text not null references bank.hypotheses(hypothesis_id) on delete cascade,
  msf_trial_id           text not null references bank.trials(msf_trial_id) on delete cascade,
  aim                    text,
  approach               text,
  approach_group         text,
  population             text,
  phase                  text,
  status                 text,
  state                  text,              -- met | not_met | mixed | stopped_no_effect | stopped_safety | ongoing |
                                            -- stopped_other | result_in_paper_unread | no_result_found
  state_source           text,              -- registry_analysis | registry_stop_reason | registry_status | paper_machine_read
  is_rct                 boolean,
  has_placebo_or_sham    boolean,
  eligible_for_verdict   boolean,
  counts_toward_verdict  boolean,
  comparator_drugs       text[],
  enrollment             int,
  start_year             int,
  drugs                  text[],
  acronym                text,
  title                  text,
  primary_endpoint_tags  text[],
  readout_quote          text,
  readout_pmid           text
);
alter table bank.hypothesis_evidence add column if not exists approach_group text;
create index if not exists hyp_ev_h_idx on bank.hypothesis_evidence (hypothesis_id);
create index if not exists hyp_ev_t_idx on bank.hypothesis_evidence (msf_trial_id);

-- what changed, week by week (status, verdict, trial count) — kept forever, never replaced
create table if not exists bank.hypothesis_history (
  id             bigint generated always as identity primary key,
  hypothesis_id  text not null,
  changed_at     timestamptz not null default now(),
  field          text not null,          -- created | outcome | status | verdict | n_trials | removed
  old_value      text,
  new_value      text,
  run_id         bigint
);
create index if not exists hyp_hist_idx on bank.hypothesis_history (hypothesis_id, changed_at desc);

-- ------------------------------------------------------------------ genetics
create table if not exists bank.genetic_leads (
  ensembl_id                  text primary key,
  symbol                      text not null,
  name                        text,
  genetic_score               double precision,
  overall_score               double precision,
  genetic_strength            text,      -- strong | moderate | weak
  lead_status                 text,      -- tested_in_ms_trials | pathway_tested_via_partner |
                                         -- drugs_exist_not_tested_in_ms | no_drugs_yet
  n_existing_drugs            int,
  existing_drugs              text[],
  approved_drugs_any_disease  text[],
  max_stage_any_drug          text,
  bank_chembl_ids             text[],
  bank_drug_names             text[],
  n_ms_trials                 int,
  ms_trial_ids                text[],
  max_ms_phase                text,
  partner_genes               text[],
  partner_drug_names          text[],
  n_ms_trials_via_partner     int,
  partner_trial_ids           text[],
  source                      text,
  ot_url                      text,
  as_of                       date
);
create index if not exists genetic_leads_symbol_idx on bank.genetic_leads (symbol);

create table if not exists bank.drug_targets (
  id             bigint generated always as identity primary key,
  chembl_id      text not null,
  drug_name      text,
  ensembl_id     text,
  symbol         text,
  moa            text,
  action_type    text,
  target_source  text
);
create index if not exists drug_targets_idx on bank.drug_targets (chembl_id);

-- ------------------------------------------------------------------ the Project (from project/*.yml)
create table if not exists bank.project_studies (
  study_id   text primary key,
  number     int,
  title      text not null,
  question   text,
  status     text,
  target     text,
  uses       text[],
  outputs    text[]
);

create table if not exists bank.project_hypotheses (
  id                     text primary key,
  study                  text references bank.project_studies(study_id) on delete cascade,
  kind                   text,           -- therapeutic | method
  statement              text not null,
  aim                    text,
  approach               text,
  approach_label         text,
  population             text,
  drugs                  text[],
  status                 text,
  registered_on          date,
  ledger_hypothesis_ids  text[]          -- computed by rule (aim + approach + population family)
);

-- ------------------------------------------------------------------ gap map: aim x approach group, all populations
drop view if exists bank.gap_map;
create view bank.gap_map with (security_invoker = true) as
with ranked as (
  select h.*,
         case h.verdict when 'supported' then 1 when 'mixed' then 2 when 'not_supported' then 3
                        when 'incomplete_phase3' then 4 when 'early_signal' then 5 when 'mixed_early' then 6
                        when 'early_negative' then 7 when 'incomplete_phase2' then 8 when 'no_readout' then 9
                        else 10 end as verdict_rank
  from bank.hypotheses h
)
select aim, min(aim_label) as aim_label, approach_group, min(approach_group_label) as approach_group_label,
       min(approach_family) as approach_family,
       count(*)                                         as n_hypotheses,
       sum(n_trials)                                    as n_trials,
       sum(n_ongoing)                                   as n_ongoing,
       sum(n_rct_phase2plus)                            as n_rct_phase2plus,
       (array_agg(verdict order by verdict_rank))[1]    as best_verdict,
       bool_or(status = 'being_tested')                 as being_tested,
       bool_or(cardinality(project_study_ids) > 0)      as in_project,
       array_agg(hypothesis_id order by verdict_rank)   as hypothesis_ids
from ranked
group by aim, approach_group;

-- ------------------------------------------------------------------ graph edges for hypotheses and genetics
create or replace function bank.rebuild_hypothesis_edges() returns int language plpgsql as $$
declare n_new int;
begin
  delete from bank.edges where origin = 'machine'
    and relation in ('tested_by', 'about_mechanism', 'registers', 'genetically_linked', 'acts_on_gene');

  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'hypothesis', e.hypothesis_id, 'tested_by', 'trial', e.msf_trial_id,
         jsonb_build_object('state', e.state, 'counts_toward_verdict', e.counts_toward_verdict), 'hypothesis ledger'
  from bank.hypothesis_evidence e;

  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'hypothesis', h.hypothesis_id, 'about_mechanism', 'mechanism', h.approach,
         jsonb_build_object('aim', h.aim, 'population', h.population, 'verdict', h.verdict), 'hypothesis ledger'
  from bank.hypotheses h;

  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'project_study', p.study, 'registers', 'hypothesis', x, jsonb_build_object('project_hypothesis', p.id),
         'project/hypotheses.yml'
  from bank.project_hypotheses p, unnest(p.ledger_hypothesis_ids) x;

  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select 'gene', g.symbol, 'genetically_linked', 'disease', 'ms',
         jsonb_build_object('genetic_score', g.genetic_score, 'lead_status', g.lead_status), 'Open Targets'
  from bank.genetic_leads g;

  insert into bank.edges (src_type, src_id, relation, dst_type, dst_id, properties, source)
  select distinct 'drug', d.chembl_id, 'acts_on_gene', 'gene', d.symbol,
         jsonb_build_object('action_type', d.action_type), d.target_source
  from bank.drug_targets d where d.symbol is not null;

  get diagnostics n_new = row_count;
  return n_new;
end $$;

-- ------------------------------------------------------------------ access: open read, loader writes
do $$
declare t text;
begin
  foreach t in array array['trial_readouts','hypotheses','hypothesis_evidence','hypothesis_history','genetic_leads',
                           'drug_targets','project_studies','project_hypotheses']
  loop
    execute format('alter table bank.%I enable row level security', t);
    execute format('drop policy if exists public_read on bank.%I', t);
    execute format('create policy public_read on bank.%I for select using (true)', t);
    execute format('grant select on bank.%I to anon, authenticated', t);
    execute format('grant all on bank.%I to service_role', t);
  end loop;
end $$;
grant select on bank.gap_map to anon, authenticated;
grant usage on all sequences in schema bank to service_role;
grant execute on function bank.rebuild_hypothesis_edges() to service_role;
