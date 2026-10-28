-- 007_trial_page.sql — what the trial detail page needs: the trial's own summary and eligibility text, and one
-- "what it found" row per trial. Run after 003, 005 and 006. Safe to re-run.

create table if not exists bank.trial_texts (
  msf_trial_id      text primary key references bank.trials(msf_trial_id) on delete cascade,
  brief_summary     text,     -- the registry's own description of the trial (sponsor's words)
  eligibility_text  text      -- inclusion and exclusion criteria as registered
);

alter table bank.trial_texts enable row level security;
drop policy if exists public_read on bank.trial_texts;
create policy public_read on bank.trial_texts for select using (true);
grant select on bank.trial_texts to anon, authenticated;
grant all on bank.trial_texts to service_role;

-- main numbers read from the results paper's abstract (every number verified word for word against the abstract)
alter table bank.trial_readouts add column if not exists result_json jsonb;

-- One row per trial: the best available statement of what it found, and where that comes from.
-- finding: met | not_met | mixed | equivalent | not_efficacy | stopped_no_effect | stopped_safety | stopped_other |
--          ongoing | results_posted_no_test | result_in_paper_unread | no_result_found
drop view if exists bank.drug_programmes;
drop view if exists bank.trial_findings;
create view bank.trial_findings with (security_invoker = true) as
select t.msf_trial_id,
       t.status,
       t.result_signal,
       t.completion_date,
       t.primary_completion_date,
       t.has_posted_results,
       t.results_first_posted,
       case
         when t.result_signal = 'primary_p_lt_0.05' then 'met'
         when t.result_signal = 'primary_p_ge_0.05' then 'not_met'
         when t.result_signal like '%futility%' then 'stopped_no_effect'
         when t.result_signal like 'terminated:safety%' then 'stopped_safety'
         when t.status in ('recruiting','active_not_recruiting','not_yet_recruiting','enrolling_by_invitation',
                           'ongoing','ongoing_inferred','suspended','transitioned_to_ctis') then 'ongoing'
         when t.result_signal like 'terminated:%' or t.result_signal like 'withdrawn:%' then 'stopped_other'
         when r.readout in ('met','not_met','mixed','equivalent','not_efficacy') then r.readout
         when t.result_signal = 'results_posted_no_primary_test' then 'results_posted_no_test'
         when t.result_signal in ('publication_linked','publication_found_europepmc') then 'result_in_paper_unread'
         else 'no_result_found'
       end as finding,
       case
         when t.result_signal in ('primary_p_lt_0.05','primary_p_ge_0.05') then 'registry_analysis'
         when t.result_signal like 'terminated:%' or t.result_signal like 'withdrawn:%' then 'registry_stop_reason'
         when r.readout in ('met','not_met','mixed','equivalent','not_efficacy') then 'paper_machine_read'
       end as finding_source,
       r.quote  as paper_quote,
       r.pmid   as paper_pmid,
       r.result_json as paper_result,
       pa.primary_analyses,
       -- months since the trial finished with nothing published anywhere we can see
       case when t.status in ('completed','terminated','completed_inferred')
                 and coalesce(t.has_posted_results, false) = false
                 and coalesce(t.n_result_pmids, 0) = 0
                 and not exists (select 1 from bank.trial_publications p where p.msf_trial_id = t.msf_trial_id
                                 and p.is_trial_report_type)
                 and coalesce(t.primary_completion_date, t.completion_date) is not null
            then (extract(year from age(current_date, coalesce(t.primary_completion_date, t.completion_date))) * 12
                  + extract(month from age(current_date, coalesce(t.primary_completion_date, t.completion_date))))::int
       end as months_since_end_without_results
from bank.trials_current t
left join bank.trial_readouts r on r.msf_trial_id = t.msf_trial_id
left join lateral (
  select jsonb_agg(jsonb_build_object('outcome', a.outcome_title, 'p', a.p_value_raw, 'method', a.method,
                                      'estimate_type', a.param_type, 'estimate', a.param_value,
                                      'ci_lower', a.ci_lower, 'ci_upper', a.ci_upper,
                                      'non_inferiority', a.non_inferiority_type)
                   order by a.p_value nulls last) as primary_analyses
  from bank.trial_primary_analyses a where a.msf_trial_id = t.msf_trial_id
) pa on true
where t.in_scope;

grant select on bank.trial_findings to anon, authenticated;

-- ------------------------------------------------------------------ connecting trials
-- 1. Direct links stated in the registries: an extension, follow-up or sub-study naming its parent trial.
create table if not exists bank.trial_links (
  id                bigint generated always as identity primary key,
  msf_trial_id      text not null references bank.trials(msf_trial_id) on delete cascade,
  related_trial_id  text not null references bank.trials(msf_trial_id) on delete cascade,
  relation          text not null,   -- extension_of | substudy_of | refers_to
  matched_id        text,
  source            text
);
create index if not exists trial_links_a on bank.trial_links (msf_trial_id);
create index if not exists trial_links_b on bank.trial_links (related_trial_id);
alter table bank.trial_links enable row level security;
drop policy if exists public_read on bank.trial_links;
create policy public_read on bank.trial_links for select using (true);
grant select on bank.trial_links to anon, authenticated;
grant all on bank.trial_links to service_role;

-- 2. Development paths: every trial of the same medicine (ChEMBL ID) in the same patient group, ordered by phase and
-- start year, so a phase 2 trial sits next to the phase 3 trials that followed it. Built by rule, nothing by hand.
drop view if exists bank.drug_programmes;
create view bank.drug_programmes with (security_invoker = true) as
with x as (
  select c as chembl_id, t.population_group, t.msf_trial_id, t.acronym, t.title, t.phase, t.start_year, t.status,
         t.enrollment, t.has_placebo_or_sham, t.comparator_drugs,
         case when t.phase && array['phase3'] then 3 when t.phase && array['phase2'] then 2
              when t.phase && array['phase1'] then 1 when t.phase && array['phase4'] then 4 else 0 end as phase_rank,
         f.finding
  from bank.trials_current t
  cross join lateral unnest(t.chembl_ids) c
  left join bank.trial_findings f on f.msf_trial_id = t.msf_trial_id
  where t.in_scope and t.study_type = 'interventional'
)
select x.chembl_id, d.drug_name, x.population_group,
       count(*)                                         as n_trials,
       max(phase_rank)                                  as highest_phase,
       bool_or(phase_rank = 2) and bool_or(phase_rank = 3) as has_phase2_and_phase3,
       min(start_year)                                  as first_year,
       max(start_year)                                  as last_year,
       jsonb_agg(jsonb_build_object('msf_trial_id', x.msf_trial_id, 'acronym', x.acronym, 'title', x.title,
                                    'phase', x.phase, 'phase_rank', phase_rank, 'start_year', x.start_year,
                                    'status', x.status, 'enrollment', x.enrollment, 'finding', x.finding,
                                    'placebo', x.has_placebo_or_sham, 'comparator', x.comparator_drugs)
                 order by phase_rank, x.start_year nulls last) as trials
from x left join bank.drugs d on d.chembl_id = x.chembl_id
group by x.chembl_id, d.drug_name, x.population_group;

grant select on bank.drug_programmes to anon, authenticated;
