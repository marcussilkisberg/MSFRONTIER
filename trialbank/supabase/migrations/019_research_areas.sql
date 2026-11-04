-- 019_research_areas.sql: one spine for the Research section. The research areas become the unit the site is
-- organised by (the map, the timeline, the gap grid and the area pages all use them), and each stage of the disease
-- sits inside one area. Also: one definition of "confirmed" everywhere (two controlled phase 3 trials, or one plus
-- approval: outcome 'confirmed' only; "supported by one trial" is counted separately), display names for trials,
-- and the figures for the home page and the Research landing page. Run after 018. Safe to re-run.

-- ---------------------------------------------------------------- 0. one meaning of "confirmed"
-- "Supported by one trial" is no longer counted as confirmed anywhere (the map, the gap grid, the state of research).
create or replace view bank.v_hypothesis_stage as
select h.*, case when h.aim = 'prevent' then 'trigger' else n.stage_id end as stage_id,
       case when h.outcome in ('failed_early', 'disproven') then 'failed' else h.outcome end as outcome_group
from bank.hypotheses h
left join bank.map_stage_nodes n on n.node_id = h.approach_group
where h.population not in ('nmosd', 'mogad');

-- ---------------------------------------------------------------- 1. the research areas
create table if not exists bank.research_areas (
  area_id   text primary key,      -- the page address under /frontiers/
  ord       int not null,
  title     text not null,
  question  text not null,
  kind      text not null,         -- disease (a part of the disease course), goal (across the course), supporting
  data_key  text not null,         -- the id used in papers.frontiers and preclinical_studies.frontiers
  extra_aim text                   -- ideas with this aim also belong to the area
);

insert into bank.research_areas (area_id, ord, title, question, kind, data_key, extra_aim) values
  ('what-starts-ms',        1, 'What starts MS',                  'Why does MS begin, and can it be prevented?',                 'disease',    'what-starts-ms',              'prevent'),
  ('stopping-inflammation', 2, 'Stopping inflammation',           'How well can relapses and new lesions be stopped?',           'disease',    'stopping-inflammation',       null),
  ('why-ms-progresses',     3, 'Why MS progresses',               'What drives worsening without relapses, and what slows it?',  'disease',    'why-ms-progresses',           null),
  ('repair-and-protection', 4, 'Repair and protection',           'Can lost myelin be rebuilt and nerve fibres protected?',      'disease',    'repair-and-protection',       null),
  ('symptoms-and-function', 5, 'Symptoms and everyday function',  'Which treatments make daily life with MS better?',            'disease',    'symptoms-and-function',       null),
  ('towards-a-cure',        6, 'Towards a cure',                  'Can MS be stopped for good, rather than held back?',          'goal',       'resetting-the-immune-system', 'reset'),
  ('measuring-ms',          7, 'Measuring MS',                    'Which measures show what matters, early enough to test treatments?', 'supporting', 'measuring-ms',          null),
  ('nmosd-and-mogad',       8, 'Related diseases: NMOSD and MOGAD', 'What works in the related antibody diseases?',              'supporting', 'nmosd-and-mogad',             null)
on conflict (area_id) do update set ord = excluded.ord, title = excluded.title, question = excluded.question,
  kind = excluded.kind, data_key = excluded.data_key, extra_aim = excluded.extra_aim;

-- which stages of the map belong to which area (disease areas only)
create or replace view bank.research_area_stages as
select s.frontier as area_id, s.stage_id, s.ord, s.short_label, s.label, s.question
from bank.map_stages s
where s.frontier in (select area_id from bank.research_areas where kind = 'disease');

-- the approaches of each area: the nodes of its stages, and for Towards a cure the routes that aim to stop MS
create table if not exists bank.research_area_nodes (
  area_id text not null references bank.research_areas(area_id) on delete cascade,
  node_id text not null,
  primary key (area_id, node_id)
);
delete from bank.research_area_nodes;
insert into bank.research_area_nodes (area_id, node_id)
select s.frontier, n.node_id from bank.map_stage_nodes n join bank.map_stages s using (stage_id)
where s.frontier in (select area_id from bank.research_areas where kind = 'disease')
on conflict do nothing;
insert into bank.research_area_nodes (area_id, node_id) values
  ('towards-a-cure', 'immune_reconstitution'), ('towards-a-cure', 'cell_therapy_tolerance'),
  ('towards-a-cure', 'nd-cell_or_transplant'), ('towards-a-cure', 'antiviral_ebv')
on conflict do nothing;

-- ---------------------------------------------------------------- 2. helpers for display
create or replace function bank.upper_first(x text) returns text language sql immutable as
$$ select case when x is null or x = '' then x else upper(left(x, 1)) || substr(x, 2) end $$;

create or replace function bank.phase_label(p text) returns text language sql immutable as
$$ select case p when 'phase1' then 'phase 1' when 'phase2' then 'phase 2' when 'phase3' then 'phase 3'
                 when 'phase4' then 'phase 4' else 'trial' end $$;

create or replace function bank.population_label(p text) returns text language sql immutable as
$$ select case p when 'relapsing' then 'Relapsing MS' when 'progressive' then 'Progressive MS'
                 when 'relapsing_and_progressive' then 'Relapsing and progressive MS'
                 when 'early_cis_ris' then 'Early MS' when 'unspecified' then 'MS, type not stated'
                 when 'nmosd' then 'NMOSD' when 'mogad' then 'MOGAD' when 'optic_neuritis' then 'Optic neuritis'
                 else bank.upper_first(replace(coalesce(p, ''), '_', ' ')) end $$;

-- the medicines a trial tests: experimental arms only, capitalised, at most three
create or replace view bank.trial_tested_medicines as
select msf_trial_id,
       string_agg(name, ', ' order by name) filter (where rn <= 3)
         || case when max(rn) > 3 then ' and ' || (max(rn) - 3) || ' more' else '' end as medicines,
       max(rn) as n_medicines
from (select msf_trial_id, bank.upper_first(drug_name) as name,
             row_number() over (partition by msf_trial_id order by drug_name) as rn
      from (select distinct msf_trial_id, drug_name from bank.trial_interventions
            where role = 'experimental' and drug_name is not null and drug_name <> ''
              -- a medicine that is also the comparator (double-dummy designs) is not what is tested
              and not exists (select 1 from bank.trial_interventions c
                              where c.msf_trial_id = trial_interventions.msf_trial_id
                                and c.role = 'active_comparator' and c.drug_name = trial_interventions.drug_name)) d) x
group by msf_trial_id;

-- what a trial tests when it has no medicine: stem cell transplantation, a device, exercise and so on
create or replace function bank.trial_approach_label(title text, nondrug text[], nodes text[]) returns text
language sql stable as $$
  select case
    when title ~* 'discontinu|\mstopping\M|withdraw|de-?escalat' then 'Stopping or reducing treatment'
    when title ~* '(haemato|hemato)poietic stem cell|\mahsct\M|\mhsct\M|stem cell transplant' then 'Stem cell transplantation'
    when title ~* 'car[- ]?t\M' then 'CAR-T cell therapy'
    when nondrug is not null and array_length(nondrug, 1) > 0 then
      bank.upper_first(replace(replace(nondrug[1], '_or_', ' or '), '_', ' '))
    else (select m.label from bank.mechanism_nodes m where m.node_id = nodes[1])
  end $$;

-- the name a trial is shown by: its acronym when it reads as a name, otherwise "<medicine>, phase N"
create or replace function bank.trial_display_name(acronym text, medicine text, top_phase text) returns text
language sql immutable as $$
  select case
    when a is null or upper(a) = 'ND' or length(a) < 3 or length(a) > 20
         or length(regexp_replace(a, '\D', '', 'g')) >= 3 or a !~* '[aeiouy]'
      then coalesce(nullif(medicine, ''), 'Trial') || ', ' || bank.phase_label(top_phase)
    else a end
  from (select nullif(regexp_replace(regexp_replace(trim(coalesce(acronym, '')), '\s*\(.*?\)\s*$', ''),
                                     '[_ ]v\d+(\.\d+)*$', '', 'i'), '') as a) x $$;

-- ---------------------------------------------------------------- 3. ideas, trials, papers and lab studies by area
create or replace view bank.area_hypotheses as
select a.area_id, h.hypothesis_id, h.statement, h.approach_group, h.approach_group_label, h.aim, h.aim_label,
       h.population, h.population_label, h.status, h.outcome, h.outcome_label,
       case when h.outcome = 'confirmed' then 'confirmed'
            when h.outcome = 'supported_one' then 'supported_one'
            when h.outcome in ('failed_early', 'disproven') then 'failed'
            when h.outcome in ('testing', 'pending') then 'testing'
            when h.outcome in ('promising', 'mixed') then 'signal'
            else 'unclear' end as outcome_group,
       h.n_trials, h.n_ongoing, h.highest_phase, h.drugs
from bank.research_areas a
join bank.hypotheses h
  on h.approach_group in (select node_id from bank.research_area_nodes n where n.area_id = a.area_id)
  or h.aim = a.extra_aim
  or (a.area_id = 'nmosd-and-mogad' and h.population in ('nmosd', 'mogad'))
where (a.area_id = 'nmosd-and-mogad') = (h.population in ('nmosd', 'mogad'));

create or replace view bank.trial_areas as
select distinct a.area_id, t.msf_trial_id
from bank.research_areas a
join bank.v_ms_trials t
  on t.approach_tags && array(select node_id from bank.research_area_nodes n where n.area_id = a.area_id)
  or (a.extra_aim = 'prevent' and t.population_group = 'early_cis_ris');

create or replace view bank.area_papers as
select distinct a.area_id, p.pmid
from bank.research_areas a
join bank.papers p
  on a.data_key = any(p.frontiers)
  or p.approach_groups && array(select node_id from bank.research_area_nodes n where n.area_id = a.area_id)
  or (a.area_id = 'symptoms-and-function' and 'symptoms_rehabilitation' = any(p.topics));

create or replace view bank.area_lab_studies as
select distinct a.area_id, p.pmid
from bank.research_areas a
join bank.preclinical_studies p
  on a.data_key = any(p.frontiers)
  or p.approach_groups && array(select node_id from bank.research_area_nodes n where n.area_id = a.area_id)
  or (a.area_id = 'what-starts-ms' and p.intervention_type = 'diet_microbiome');

create or replace view bank.area_open_questions as
select distinct s.frontier as area_id, q.question_id
from bank.open_questions q join bank.map_stages s using (stage_id)
union
select 'towards-a-cure', q.question_id from bank.open_questions q
where q.question_id in ('ebv-treatment', 'ebv-cells', 'ahsct', 'car-t', 'tolerance')
union
select 'measuring-ms', q.question_id from bank.open_questions q where q.stage_id is null;

-- ---------------------------------------------------------------- 4. names for every trial, and results to come
create or replace view bank.trial_names as
select t.msf_trial_id,
       bank.trial_display_name(t.acronym, coalesce(nullif(split_part(coalesce(x.tested, ''), ',', 1), ''), 'Trial'),
         case when 'phase3' = any(t.phase) then 'phase3' when 'phase2' = any(t.phase) then 'phase2'
              when 'phase4' = any(t.phase) then 'phase4' when 'phase1' = any(t.phase) or 'early_phase1' = any(t.phase)
              then 'phase1' else 'none' end) as name,
       x.tested
from bank.trials t
left join bank.trial_tested_medicines m using (msf_trial_id)
cross join lateral (select case
    when m.medicines is null or m.n_medicines > 3
         or t.title ~* 'discontinu|\mstopping\M|withdraw|de-?escalat|stem cell transplant|\mahsct\M|\mhsct\M'
      then coalesce(bank.trial_approach_label(t.title, t.nondrug_categories, t.mechanism_nodes), m.medicines)
    else m.medicines end as tested) x;

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
join bank.research_area_stages s on s.stage_id = r.stage_id
join bank.research_areas a on a.area_id = s.area_id
where r.primary_completion_date >= current_date
order by r.msf_trial_id, a.ord;

-- ---------------------------------------------------------------- 5. one row per area, for the map and the area pages
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
       case when coalesce(n_confirmed, 0) >= 5 then 'established'
            when coalesce(n_confirmed, 0) >= 1 then 'partial'
            when coalesce(n_running, 0) >= 10 then 'testing'
            else 'little' end as level,
       case when coalesce(n_confirmed, 0) >= 5 then 'Several treatments work'
            when coalesce(n_confirmed, 0) >= 1 then 'Some treatments work'
            when coalesce(n_running, 0) >= 10 then 'Being tested, none confirmed'
            else 'Little tested so far' end as level_label
from bank.research_areas a
left join h using (area_id) left join tr using (area_id) left join lab using (area_id) left join pap using (area_id)
left join q using (area_id) left join nx using (area_id)
order by a.ord;

-- ---------------------------------------------------------------- 6. figures for the home page and Research
create or replace view bank.research_numbers as
select
  (select count(*) from bank.v_ms_trials) as n_trials,
  (select min(start_year) from bank.v_ms_trials where start_year >= 1980) as first_year,
  (select count(*) from bank.v_ms_trials where running) as n_trials_running,
  (select count(*) from bank.v_ms_trials where running and top_phase = 'phase3') as n_phase3_running,
  (select count(*) from bank.v_hypothesis_stage) as n_ideas,
  (select count(*) from bank.v_hypothesis_stage where outcome = 'confirmed') as n_ideas_confirmed,
  (select count(*) from bank.v_hypothesis_stage where outcome = 'supported_one') as n_ideas_supported_one,
  (select count(*) from bank.v_hypothesis_stage where outcome in ('failed_early', 'disproven')) as n_ideas_failed,
  (select count(*) from bank.v_hypothesis_stage where outcome in ('testing', 'pending')) as n_ideas_testing,
  (select count(distinct approach_group) from bank.v_hypothesis_stage where outcome = 'confirmed') as n_approaches_confirmed,
  (select count(*) from bank.preclinical_studies) as n_lab_studies,
  (select count(*) from bank.papers) as n_reviews,
  (select count(*) from bank.open_questions) as n_open_questions,
  (select count(*) from bank.results_timeline where within_12_months) as n_results_12m,
  (select count(*) from bank.results_timeline) as n_results_6y,
  (select count(*) from bank.trials) as n_trial_records;

-- where the running trials are, by area (disease areas only, so the shares add up to the whole)
create or replace view bank.research_effort as
select s.area_id, s.ord, s.title, s.n_running, s.n_lab_studies,
       round(100.0 * s.n_running / nullif(sum(s.n_running) over (), 0)) as pct_of_running,
       round(100.0 * s.n_lab_studies / nullif(sum(s.n_lab_studies) over (), 0)) as pct_of_lab
from bank.research_area_summary s where s.kind = 'disease';

-- the stage pipeline by area, for the map: one row per area and level
create or replace view bank.area_pipeline as
select area_id, ord, 'lab' as level, 1 as level_ord, 'Lab studies' as level_label, n_lab_studies as n from bank.research_area_summary where kind <> 'supporting'
union all select area_id, ord, 'early', 2, 'Early trials running', n_running_early from bank.research_area_summary where kind <> 'supporting'
union all select area_id, ord, 'phase3', 3, 'Phase 3 trials running', n_running_phase3 from bank.research_area_summary where kind <> 'supporting'
union all select area_id, ord, 'confirmed', 4, 'Confirmed', n_confirmed from bank.research_area_summary where kind <> 'supporting'
union all select area_id, ord, 'failed', 5, 'Failed', n_failed from bank.research_area_summary where kind <> 'supporting';

-- ---------------------------------------------------------------- 7. the gap grid, with what sits behind each cell
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
       case h.aim when 'reset' then 'Lasting remission' else h.aim_label end as aim_label,
       h.n_confirmed, h.n_supported_one, h.confirmed_approaches, h.tested_approaches,
       coalesce(e.n_running, 0) as n_running, coalesce(e.n_running_phase3, 0) as n_running_phase3,
       case when h.n_confirmed > 0 then 'confirmed' when coalesce(e.n_running, 0) > 0 then 'testing'
            else 'nothing' end as cell_state
from h left join e using (population, aim);

-- ---------------------------------------------------------------- 8. read access
alter table bank.research_areas enable row level security;
alter table bank.research_area_nodes enable row level security;
drop policy if exists public_read on bank.research_areas;
create policy public_read on bank.research_areas for select using (true);
drop policy if exists public_read on bank.research_area_nodes;
create policy public_read on bank.research_area_nodes for select using (true);

grant select on bank.v_hypothesis_stage, bank.trial_names, bank.research_areas, bank.research_area_nodes, bank.research_area_stages, bank.trial_tested_medicines,
  bank.area_hypotheses, bank.trial_areas, bank.area_papers, bank.area_lab_studies, bank.area_open_questions,
  bank.results_timeline, bank.research_area_summary, bank.research_numbers, bank.research_effort, bank.area_pipeline,
  bank.gap_cells to anon, authenticated;
grant all on bank.research_areas, bank.research_area_nodes to service_role;
grant execute on function bank.upper_first(text), bank.phase_label(text), bank.population_label(text),
  bank.trial_approach_label(text, text[], text[]), bank.trial_display_name(text, text, text) to anon, authenticated;
