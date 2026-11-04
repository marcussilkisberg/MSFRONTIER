-- 021_area_fixes.sql: fixes from the audit of 4 November 2026. Run after 020. Safe to re-run.
-- 1. area_hypotheses gets a display label that names the medicine when a hypothesis is about one medicine, so that
--    "Amiloride", "Fluoxetine" and "Riluzole" no longer all read "Axonal protection / ion channels / excitotoxicity".
-- 2. results_timeline places each trial in the area of the aim most of its hypotheses share, not the first in order,
--    so a metformin trial aimed at progression is no longer shown under Stopping relapses.
-- 3. research_area_summary prefers a phase 3 trial when two results are due in the same month.
-- 4. missing_results_summary and missing_results_largest for the Missing results page, from the results watch.

create or replace view bank.area_hypotheses as
select a.area_id, h.hypothesis_id, h.statement, h.approach_group, h.approach_group_label, h.aim, h.aim_label,
       h.population, bank.upper_first(h.population_label) as population_label, h.status, h.outcome, h.outcome_label,
       case when h.outcome = 'confirmed' then 'confirmed'
            when h.outcome = 'supported_one' then 'supported_one'
            when h.outcome in ('failed_early', 'disproven') then 'failed'
            when h.outcome in ('testing', 'pending') then 'testing'
            when h.outcome in ('promising', 'mixed') then 'signal'
            else 'unclear' end as outcome_group,
       h.n_trials, h.n_ongoing, h.highest_phase, h.drugs,
       m.medicines,
       h.approach_label,
       case when h.approach like '%.%' then h.approach_label else h.approach_group_label end as display_label
from bank.research_area_aims a
join bank.hypotheses h on h.aim = a.aim
left join bank.hypothesis_medicines m using (hypothesis_id)
where h.population not in ('nmosd', 'mogad');

create or replace view bank.results_timeline as
with main_area as (
  select distinct on (e.msf_trial_id) e.msf_trial_id, ra.area_id
  from bank.hypothesis_evidence e
  join bank.research_area_aims aa on aa.aim = e.aim
  join bank.research_areas ra on ra.area_id = aa.area_id
  group by e.msf_trial_id, ra.area_id, ra.ord
  order by e.msf_trial_id, count(*) desc, ra.ord)
select distinct on (r.msf_trial_id)
       r.msf_trial_id,
       a.area_id, a.title as area_title, a.ord as area_ord,
       bank.trial_display_name(r.acronym,
         coalesce(nullif(split_part(coalesce(x.tested, ''), ',', 1), ''), 'Trial'), r.phase) as name,
       x.tested,
       r.phase, bank.phase_label(r.phase) as phase_label,
       r.population_group, bank.population_label(r.population_group) as population_label,
       r.enrollment, r.primary_completion_date,
       to_char(r.primary_completion_date, 'Mon YYYY') as due_label,
       r.primary_completion_date <= current_date + interval '12 months' as within_12_months
from bank.map_stage_readouts r
join bank.trials t using (msf_trial_id)
left join bank.trial_tested_medicines m using (msf_trial_id)
cross join lateral (select case
    when m.medicines is null or m.n_medicines > 3
         or t.title ~* 'discontinu|\mstopping\M|withdraw|de-?escalat|stem cell transplant|\mahsct\M|\mhsct\M'
      then coalesce(bank.trial_approach_label(t.title, t.nondrug_categories, t.mechanism_nodes), m.medicines)
    else m.medicines end as tested) x
join main_area ma on ma.msf_trial_id = r.msf_trial_id
join bank.research_areas a on a.area_id = ma.area_id
where r.primary_completion_date >= current_date
order by r.msf_trial_id;

create or replace view bank.research_area_summary as
with h as (
  select area_id,
         count(*) as n_ideas,
         count(*) filter (where outcome_group = 'confirmed') as n_confirmed,
         count(*) filter (where outcome_group = 'supported_one') as n_supported_one,
         count(*) filter (where outcome_group = 'signal') as n_signal,
         count(*) filter (where outcome_group = 'testing') as n_testing,
         count(*) filter (where outcome_group = 'failed') as n_failed,
         count(distinct approach_group) filter (where outcome_group = 'confirmed') as n_approaches_confirmed
  from bank.area_hypotheses group by area_id),
tr as (
  select x.area_id,
         count(*) filter (where t.running) as n_running,
         count(*) filter (where t.running and t.top_phase in ('phase1', 'phase2')) as n_running_early,
         count(*) filter (where t.running and t.top_phase = 'phase3') as n_running_phase3
  from bank.trial_areas x join bank.v_ms_trials t using (msf_trial_id) group by x.area_id),
lab as (select area_id, count(*) as n_lab_studies from bank.area_lab_studies group by area_id),
pap as (select area_id, count(*) as n_reviews from bank.area_papers group by area_id),
q as (select area_id, count(*) as n_open_questions from bank.area_open_questions group by area_id),
nx as (select distinct on (area_id) area_id, name as next_result_name, msf_trial_id as next_result_trial_id,
              primary_completion_date as next_result_date, due_label as next_result_label
       from bank.results_timeline
       order by area_id, date_trunc('month', primary_completion_date), (phase = 'phase3') desc, primary_completion_date)
select a.area_id, a.ord, a.title, a.question, a.kind,
       coalesce(n_ideas, 0) as n_ideas, coalesce(n_confirmed, 0) as n_confirmed,
       coalesce(n_supported_one, 0) as n_supported_one, coalesce(n_signal, 0) as n_signal,
       coalesce(n_testing, 0) as n_testing, coalesce(n_failed, 0) as n_failed,
       coalesce(n_approaches_confirmed, 0) as n_approaches_confirmed,
       coalesce(n_running, 0) as n_running, coalesce(n_running_early, 0) as n_running_early,
       coalesce(n_running_phase3, 0) as n_running_phase3,
       coalesce(n_lab_studies, 0) as n_lab_studies, coalesce(n_reviews, 0) as n_reviews,
       coalesce(n_open_questions, 0) as n_open_questions,
       next_result_name, next_result_trial_id, next_result_date, next_result_label,
       case when coalesce(n_approaches_confirmed, 0) >= 8 then 'established'
            when coalesce(n_approaches_confirmed, 0) >= 1 then 'partial'
            when coalesce(n_running, 0) >= 10 then 'testing'
            else 'little' end as level,
       case when coalesce(n_approaches_confirmed, 0) >= 8 then 'Many confirmed'
            when coalesce(n_approaches_confirmed, 0) >= 1 then 'Few confirmed'
            when coalesce(n_running, 0) >= 10 then 'None confirmed yet'
            else 'None confirmed, few trials' end as level_label,
       a.slug, a.short_title
from bank.research_areas a
left join h using (area_id) left join tr using (area_id) left join lab using (area_id) left join pap using (area_id)
left join q using (area_id) left join nx using (area_id)
order by a.ord;

-- the Missing results page: every finished phase 2 to 4 trial that ended at least 12 months ago and has been checked
-- for results in registries, papers and news (the results watch), so that the page, its card and the sidebar use one
-- number
create or replace view bank.missing_results_summary as
with w as (
  select *, case when phase like '%phase3%' then 'Phase 3' when phase like '%phase2%' then 'Phase 2'
                 when phase like '%phase4%' then 'Phase 4' else 'Other' end as phase_label,
            case when months_since_end < 24 then '1 to 2 years ago' when months_since_end < 60 then '2 to 5 years ago'
                 else 'More than 5 years ago' end as ended_label,
            case when months_since_end < 24 then 1 when months_since_end < 60 then 2 else 3 end as ended_ord
  from bank.results_watch_public)
select 'all' as dimension, 'All checked trials' as value, 0 as ord, count(*) as n_checked,
       count(*) filter (where not results_found) as n_missing,
       round(100.0 * count(*) filter (where not results_found) / nullif(count(*), 0)) as pct_missing,
       coalesce(sum(enrollment) filter (where not results_found), 0) as participants_missing
from w
union all
select 'phase', phase_label,
       case phase_label when 'Phase 2' then 2 when 'Phase 3' then 3 when 'Phase 4' then 4 else 5 end,
       count(*), count(*) filter (where not results_found),
       round(100.0 * count(*) filter (where not results_found) / nullif(count(*), 0)),
       coalesce(sum(enrollment) filter (where not results_found), 0)
from w group by phase_label
union all
select 'ended', ended_label, ended_ord, count(*), count(*) filter (where not results_found),
       round(100.0 * count(*) filter (where not results_found) / nullif(count(*), 0)),
       coalesce(sum(enrollment) filter (where not results_found), 0)
from w group by ended_label, ended_ord;

create or replace view bank.missing_results_largest as
select w.msf_trial_id, coalesce(n.name, w.acronym, w.title) as name, w.title, w.phase, w.status, w.enrollment,
       w.end_date, w.months_since_end, w.registry_ids
from bank.results_watch_public w
left join bank.trial_names n using (msf_trial_id)
where not w.results_found
order by w.enrollment desc nulls last;

grant select on bank.area_hypotheses, bank.results_timeline, bank.research_area_summary,
  bank.missing_results_summary, bank.missing_results_largest to anon, authenticated;
