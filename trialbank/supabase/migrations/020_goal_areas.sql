-- 020_goal_areas.sql: the research areas become goals of treatment, and each hypothesis, trial, review and lab study
-- belongs to an area through its aim (prevent, stop relapses, slow progression, protect and repair, ease symptoms,
-- lasting remission). This replaces the placement by approach in 019, which put prevention trials under relapses and
-- left Protecting and repairing with thirteen hypotheses. Measuring MS and Related diseases leave Research.
-- Also: clean medicine lists for hypotheses, the views for "From the lab to people" and "Not yet tested in people".
-- Run after 019. Safe to re-run. Keeps every view's existing columns and adds new ones at the end.

-- ---------------------------------------------------------------- 1. the areas as goals
alter table bank.research_areas add column if not exists slug text;
alter table bank.research_areas add column if not exists short_title text;

delete from bank.research_areas where area_id in ('measuring-ms', 'nmosd-and-mogad');

insert into bank.research_areas (area_id, ord, title, question, kind, data_key, extra_aim, slug, short_title) values
  ('what-starts-ms',        1, 'Preventing MS',            'What starts MS, and can it be prevented or delayed?',          'disease', 'what-starts-ms',              'prevent',          'preventing-ms',            'Prevention'),
  ('stopping-inflammation', 2, 'Stopping relapses',        'How well can relapses and new lesions be stopped?',            'disease', 'stopping-inflammation',       'stop_inflammation','stopping-relapses',        'Relapses'),
  ('why-ms-progresses',     3, 'Slowing progression',      'What drives worsening without relapses, and what slows it?',   'disease', 'why-ms-progresses',           'slow_progression', 'slowing-progression',      'Progression'),
  ('repair-and-protection', 4, 'Protecting and repairing', 'Can nerve fibres be protected and lost myelin rebuilt?',       'disease', 'repair-and-protection',       'protect_nerves',   'protecting-and-repairing', 'Repair'),
  ('symptoms-and-function', 5, 'Easing symptoms',          'Which treatments make daily life with MS better?',             'disease', 'symptoms-and-function',       'restore_function', 'easing-symptoms',          'Symptoms'),
  ('towards-a-cure',        6, 'Towards a cure',           'Can MS be stopped for good, rather than held back?',           'goal',    'resetting-the-immune-system', 'reset',            'towards-a-cure',           'Cure')
on conflict (area_id) do update set ord = excluded.ord, title = excluded.title, question = excluded.question,
  kind = excluded.kind, data_key = excluded.data_key, extra_aim = excluded.extra_aim, slug = excluded.slug,
  short_title = excluded.short_title;

-- the aims of each area (Protecting and repairing has two)
create table if not exists bank.research_area_aims (
  area_id text not null references bank.research_areas(area_id) on delete cascade,
  aim     text not null,
  primary key (area_id, aim)
);
delete from bank.research_area_aims;
insert into bank.research_area_aims (area_id, aim) values
  ('what-starts-ms', 'prevent'), ('stopping-inflammation', 'stop_inflammation'),
  ('why-ms-progresses', 'slow_progression'), ('repair-and-protection', 'protect_nerves'),
  ('repair-and-protection', 'repair'), ('symptoms-and-function', 'restore_function'), ('towards-a-cure', 'reset');

-- ---------------------------------------------------------------- 2. medicines of a hypothesis
-- only medicines given in the experimental arms of its trials that act through the hypothesis's own approach, so a
-- premedication (paracetamol, cetirizine) or a comparator never appears
create or replace view bank.hypothesis_medicines as
select hypothesis_id,
       string_agg(name, ', ' order by name) filter (where rn <= 4)
         || case when max(rn) > 4 then ' and ' || (max(rn) - 4) || ' more' else '' end as medicines
from (select hypothesis_id, bank.upper_first(drug_name) as name,
             row_number() over (partition by hypothesis_id order by drug_name) as rn
      from (select distinct e.hypothesis_id, i.drug_name
            from bank.hypothesis_evidence e
            join bank.trial_interventions i on i.msf_trial_id = e.msf_trial_id
            where i.role = 'experimental' and i.drug_name is not null and i.drug_name <> ''
              and e.approach_group = any(i.mechanism_nodes)) d) x
group by hypothesis_id;

-- ---------------------------------------------------------------- 3. hypotheses, trials, reviews and lab studies by aim
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
       m.medicines
from bank.research_area_aims a
join bank.hypotheses h on h.aim = a.aim
left join bank.hypothesis_medicines m using (hypothesis_id)
where h.population not in ('nmosd', 'mogad');

create or replace view bank.trial_areas as
select distinct a.area_id, e.msf_trial_id
from bank.research_area_aims a
join bank.hypothesis_evidence e on e.aim = a.aim
where e.population not in ('nmosd', 'mogad');

create or replace view bank.area_papers as
select distinct a.area_id, p.pmid
from bank.research_area_aims a
join bank.papers p
  on a.aim = any(p.aims)
  or (a.area_id = 'what-starts-ms' and p.topics && array['causes_risk', 'epidemiology'])
  or (a.area_id = 'symptoms-and-function' and 'symptoms_rehabilitation' = any(p.topics))
  or (a.area_id = 'towards-a-cure' and 'resetting-the-immune-system' = any(p.frontiers));

create or replace view bank.area_lab_studies as
select distinct a.area_id, p.pmid
from bank.research_area_aims a
join bank.preclinical_studies p
  on a.aim = any(p.aims)
  or (a.area_id = 'what-starts-ms'
      and (p.intervention_type = 'diet_microbiome' or p.approach_groups && array['antiviral_ebv', 'nutritional_supplement']));

create or replace view bank.area_open_questions as
select distinct s.frontier as area_id, q.question_id
from bank.open_questions q join bank.map_stages s using (stage_id)
where s.frontier in (select area_id from bank.research_areas)
union
select 'towards-a-cure', q.question_id from bank.open_questions q
where q.question_id in ('ebv-treatment', 'ebv-cells', 'ahsct', 'car-t', 'tolerance')
union
select 'stopping-inflammation', q.question_id from bank.open_questions q where q.stage_id is null;

-- ---------------------------------------------------------------- 4. results to come, placed by aim
create or replace view bank.results_timeline as
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
join bank.trial_areas ta on ta.msf_trial_id = r.msf_trial_id
join bank.research_areas a on a.area_id = ta.area_id
where r.primary_completion_date >= current_date
order by r.msf_trial_id, a.ord;

-- ---------------------------------------------------------------- 5. one row per area, with honest status words
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
       from bank.results_timeline order by area_id, primary_completion_date)
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
       -- short enough for one line; "Few" and "None" make clear that an area is not solved
       case when coalesce(n_approaches_confirmed, 0) >= 8 then 'Many confirmed'
            when coalesce(n_approaches_confirmed, 0) >= 1 then 'Few confirmed'
            when coalesce(n_running, 0) >= 10 then 'None confirmed yet'
            else 'None confirmed, few trials' end as level_label,
       a.slug, a.short_title
from bank.research_areas a
left join h using (area_id) left join tr using (area_id) left join lab using (area_id) left join pap using (area_id)
left join q using (area_id) left join nx using (area_id)
order by a.ord;

-- ---------------------------------------------------------------- 6. the gap grid, columns named as the areas
create or replace view bank.gap_cells as
with h as (
  select population, population_label, aim, aim_label,
         count(*) filter (where outcome = 'confirmed') as n_confirmed,
         count(*) filter (where outcome = 'supported_one') as n_supported_one,
         string_agg(approach_group_label, '; ' order by approach_group_label) filter (where outcome = 'confirmed') as confirmed_approaches,
         string_agg(approach_group_label, '; ' order by approach_group_label) filter (where outcome in ('testing', 'pending', 'supported_one', 'promising', 'mixed')) as tested_approaches
  from bank.v_hypothesis_stage
  where population in ('early_cis_ris', 'relapsing', 'relapsing_and_progressive', 'spms', 'ppms')
  group by 1, 2, 3, 4),
e as (
  select population, aim,
         count(distinct msf_trial_id) filter (where state = 'ongoing') as n_running,
         count(distinct msf_trial_id) filter (where state = 'ongoing' and phase in ('phase3', 'phase2|phase3')) as n_running_phase3
  from bank.hypothesis_evidence group by 1, 2)
select h.population, bank.upper_first(h.population_label) as population_label, h.aim,
       case h.aim when 'prevent' then 'Prevent or delay MS' when 'stop_inflammation' then 'Stop relapses'
                  when 'slow_progression' then 'Slow progression' when 'protect_nerves' then 'Protect nerves'
                  when 'repair' then 'Repair myelin' when 'restore_function' then 'Ease symptoms'
                  when 'reset' then 'Lasting remission' else h.aim_label end as aim_label,
       h.n_confirmed, h.n_supported_one, h.confirmed_approaches, h.tested_approaches,
       coalesce(e.n_running, 0) as n_running, coalesce(e.n_running_phase3, 0) as n_running_phase3,
       case when h.n_confirmed > 0 then 'confirmed' when coalesce(e.n_running, 0) > 0 then 'testing'
            else 'nothing' end as cell_state,
       ra.area_id, ra.title as area_title, ra.ord as area_ord,
       case h.population when 'early_cis_ris' then 1 when 'relapsing' then 2 when 'relapsing_and_progressive' then 3
                         when 'spms' then 4 when 'ppms' then 5 end as population_ord
from h
left join e using (population, aim)
left join bank.research_area_aims aa on aa.aim = h.aim
left join bank.research_areas ra on ra.area_id = aa.area_id;

-- ---------------------------------------------------------------- 7. from the lab to people
-- per approach with at least five lab studies: how it did in the lab, and what happened in people
create or replace view bank.lab_then_people as
select l.approach_group, l.approach_group_label, l.n_lab_studies, l.n_lab_helped, l.pct_lab_helped,
       l.n_confirmed, l.n_failed, l.n_testing,
       case when l.n_confirmed > 0 then 'worked'
            when l.n_failed > 0 then 'failed'
            when l.n_testing > 0 then 'testing'
            else 'unclear' end as in_people,
       case when l.n_confirmed > 0 then 'Confirmed in people'
            when l.n_failed > 0 then 'Failed in people'
            when l.n_testing > 0 then 'Being tested in people'
            else 'No clear answer in people' end as in_people_label,
       (select string_agg(distinct bank.upper_first(h.population_label) || ': ' || h.outcome_label, ' · ')
          from bank.v_hypothesis_stage h
         where h.approach_group = l.approach_group and h.outcome_group in ('confirmed', 'failed')) as human_detail
from bank.lab_to_people l;

-- approaches that helped in most lab studies but failed in people, one row per approach
create or replace view bank.lab_failures_in_people as
select l.approach_group, l.approach_group_label, l.n_lab_studies, l.pct_lab_helped,
       count(*) as n_failed_hypotheses,
       string_agg(bank.upper_first(h.population_label) || ': ' || lower(h.outcome_label), ' · '
                  order by h.population_label) as failed_in,
       max(h.highest_phase) as highest_phase,
       bool_or(h.outcome = 'disproven') as failed_in_phase3,
       exists (select 1 from bank.v_hypothesis_stage c
               where c.approach_group = l.approach_group and c.outcome = 'confirmed') as confirmed_elsewhere
from bank.lab_to_people l
join bank.v_hypothesis_stage h using (approach_group)
where h.outcome_group = 'failed' and l.pct_lab_helped >= 60
group by l.approach_group, l.approach_group_label, l.n_lab_studies, l.pct_lab_helped
order by bool_or(h.outcome = 'disproven') desc, l.n_lab_studies desc;

-- treatments tested only in the lab, with the area of their main aim
create or replace view bank.lab_only_ideas as
select i.idea_id, i.name, i.mechanism, i.intervention_type, i.n_papers, i.n_benefit, i.n_no_benefit,
       round(100.0 * i.n_benefit / nullif(i.n_papers, 0)) as pct_benefit,
       i.model_systems, i.aims, i.target_genes, i.genetic_support, i.latest_year,
       a.area_id, a.title as area_title, a.ord as area_ord
from bank.preclinical_ideas i
left join lateral (select ra.area_id, ra.title, ra.ord
                   from bank.research_area_aims aa join bank.research_areas ra using (area_id)
                   where aa.aim = any(i.aims) order by ra.ord limit 1) a on true
where not coalesce(i.in_human_trials, false) and i.n_papers >= 2;

-- ---------------------------------------------------------------- 8. read access
alter table bank.research_area_aims enable row level security;
drop policy if exists public_read on bank.research_area_aims;
create policy public_read on bank.research_area_aims for select using (true);
grant select on bank.research_area_aims, bank.hypothesis_medicines, bank.lab_then_people,
  bank.lab_failures_in_people, bank.lab_only_ideas, bank.area_hypotheses, bank.trial_areas, bank.area_papers,
  bank.area_lab_studies, bank.area_open_questions, bank.results_timeline, bank.research_area_summary,
  bank.gap_cells to anon, authenticated;
grant all on bank.research_area_aims to service_role;
