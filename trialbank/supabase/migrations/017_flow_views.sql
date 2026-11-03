-- 017_flow_views.sql: views behind the redesigned flow (state of research, results timeline, links from records back
-- to the map). Run after 016. Safe to re-run. Everything is computed from the weekly tables.

-- one sentence per stage, set by fixed rules, and a level for its colour
create or replace view bank.map_stage_verdict as
select s.stage_id, s.ord,
       case
         when s.n_confirmed >= 5 then 'established'
         when s.n_confirmed >= 1 then 'partial'
         when s.n_running >= 10 then 'testing'
         else 'little'
       end as level,
       case
         when s.n_confirmed >= 5 then 'Several treatments confirmed. ' || s.n_running || ' trials running.'
         when s.n_confirmed >= 1 then s.n_confirmed || case when s.n_confirmed = 1 then ' treatment' else ' treatments' end
              || ' confirmed. ' || s.n_running || ' trials running.'
         when s.n_running >= 10 then 'No treatment confirmed yet. ' || s.n_running || ' trials running.'
         else 'No treatment confirmed yet, and few trials running (' || s.n_running || ').'
       end as verdict
from bank.map_stage_summary s;

-- the research pipeline: one row per stage and level, for the matrix on the map
create or replace view bank.map_pipeline as
select stage_id, ord, 'lab' as level, 1 as level_ord, 'Lab studies since 2015' as level_label, n_lab_studies as n from bank.map_stage_summary
union all select stage_id, ord, 'early', 2, 'Early trials running (phase 1 and 2)', n_running_phase1 + n_running_phase2 from bank.map_stage_summary
union all select stage_id, ord, 'phase3', 3, 'Phase 3 trials running', n_running_phase3 from bank.map_stage_summary
union all select stage_id, ord, 'confirmed', 4, 'Approaches confirmed', n_confirmed from bank.map_stage_summary
union all select stage_id, ord, 'failed', 5, 'Approaches that failed', n_failed from bank.map_stage_summary;

-- results to come: running controlled phase 2 and 3 trials with a main results date in the next six years, per stage
create or replace view bank.map_stage_readouts as
select distinct n.stage_id, t.msf_trial_id, t.acronym, t.title, t.drugs, t.top_phase as phase, t.population_group,
       t.enrollment, t.primary_completion_date
from bank.map_stage_nodes n
join bank.v_ms_trials t on n.node_id = any(t.approach_tags)
where t.running and t.top_phase in ('phase2', 'phase3')
  and t.primary_completion_date between current_date and current_date + interval '6 years'
  and exists (select 1 from bank.hypothesis_evidence e where e.msf_trial_id = t.msf_trial_id and e.eligible_for_verdict);

-- the state of research in five figures, for the home page
create or replace view bank.research_state as
select
  (select count(*) from bank.v_hypothesis_stage where outcome_group = 'confirmed') as n_confirmed,
  (select count(*) from bank.v_hypothesis_stage where outcome_group = 'failed') as n_failed,
  (select count(*) from bank.v_hypothesis_stage where outcome = 'testing') as n_being_tested,
  (select count(*) from bank.v_ms_trials where running) as n_trials_running,
  (select count(distinct msf_trial_id) from bank.map_stage_readouts
    where primary_completion_date <= current_date + interval '12 months') as n_results_12m,
  (select count(*) from bank.map_stage_summary where n_confirmed = 0) as n_stages_without_confirmed,
  (select string_agg(short_label, ' and ' order by ord) from bank.map_stage_summary where n_confirmed = 0) as stages_without_confirmed;

-- from a record back to the map: the stages of each trial and each hypothesis
create or replace view bank.trial_stages as
select distinct t.msf_trial_id, n.stage_id, s.short_label, s.label
from bank.v_ms_trials t
join bank.map_stage_nodes n on n.node_id = any(t.approach_tags)
join bank.map_stages s using (stage_id);

create or replace view bank.hypothesis_stages as
select h.hypothesis_id, h.stage_id, s.short_label, s.label
from bank.v_hypothesis_stage h join bank.map_stages s using (stage_id);

grant select on bank.map_stage_verdict, bank.map_pipeline, bank.map_stage_readouts, bank.research_state,
  bank.trial_stages, bank.hypothesis_stages to anon, authenticated;
