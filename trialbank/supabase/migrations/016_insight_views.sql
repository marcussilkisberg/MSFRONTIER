-- 016_insight_views.sql: the map of MS research, the gap index, open questions and evidence patterns.
-- Run after 015. Safe to re-run. Everything here is computed from the weekly tables, so it updates itself after each
-- load. The only hand-written parts are the stage list, the rules that place approaches on a stage, and the open
-- questions with their matching rules. Lab evidence and reviews never change a status.

-- ---------------------------------------------------------------- 1. stages of the disease and their rules
create table if not exists bank.map_stages (
  stage_id      text primary key,
  ord           int not null,
  label         text not null,
  short_label   text not null,
  question      text not null,
  frontier      text,              -- research question page it belongs to
  cross_cutting boolean default false
);

create table if not exists bank.map_stage_nodes (
  stage_id  text not null references bank.map_stages(stage_id) on delete cascade,
  node_id   text not null,        -- mechanism node, or 'nd-' + non-drug category
  primary key (stage_id, node_id)
);

insert into bank.map_stages (stage_id, ord, label, short_label, question, frontier, cross_cutting) values
  ('trigger',    1, 'Triggers and risk factors', 'Triggers', 'What sets MS off, and can it be prevented or delayed?', 'what-starts-ms', false),
  ('immune',     2, 'Immune attack outside the brain', 'Immune attack', 'Which immune cells drive relapses, and how well can they be stopped?', 'stopping-inflammation', false),
  ('entry',      3, 'Entry into the brain and spinal cord', 'Entry', 'Can immune cells be kept out of the brain?', 'stopping-inflammation', false),
  ('smouldering',4, 'Smouldering inflammation inside the brain', 'Smouldering', 'What keeps inflammation going behind the blood-brain barrier?', 'why-ms-progresses', false),
  ('damage',     5, 'Damage to nerve fibres', 'Nerve damage', 'Why do nerve fibres die, and can they be protected?', 'why-ms-progresses', false),
  ('repair',     6, 'Repair of myelin', 'Repair', 'Can lost myelin be rebuilt?', 'repair-and-protection', false),
  ('living',     7, 'Living with MS', 'Daily life', 'Which treatments improve symptoms and everyday function?', 'symptoms-and-function', false),
  ('reset',      8, 'Resetting the immune system', 'Reset', 'Can the immune system be rebuilt so the disease stops?', 'resetting-the-immune-system', true)
on conflict (stage_id) do update set ord = excluded.ord, label = excluded.label, short_label = excluded.short_label,
  question = excluded.question, frontier = excluded.frontier, cross_cutting = excluded.cross_cutting;

delete from bank.map_stage_nodes;
insert into bank.map_stage_nodes (stage_id, node_id) values
  ('trigger', 'antiviral_ebv'), ('trigger', 'nutritional_supplement'), ('trigger', 'nd-diet_nutrition'),
  ('immune', 'anti_cd20_b_cell'), ('immune', 'other_b_cell_plasma_cell'), ('immune', 't_cell_costimulation'),
  ('immune', 'interferon_beta'), ('immune', 'glatiramer'), ('immune', 'dhodh_pyrimidine'), ('immune', 'nrf2_fumarate'),
  ('immune', 'broad_immunosuppression'), ('immune', 'il6_pathway'), ('immune', 'complement'), ('immune', 'fcrn_igg'),
  ('immune', 'corticosteroid'),
  ('entry', 'integrin_trafficking'), ('entry', 's1p_receptor_modulation'),
  ('smouldering', 'btk_inhibition'), ('smouldering', 'microglia_innate'),
  ('damage', 'mitochondrial_oxidative'), ('damage', 'axonal_neuroprotection'), ('damage', 'vascular_lipid'),
  ('damage', 'blood_pressure'), ('damage', 'hormonal'),
  ('repair', 'remyelination'),
  ('living', 'walking_k_channel'), ('living', 'spasticity'), ('living', 'fatigue_wakefulness'), ('living', 'bladder'),
  ('living', 'pain_mood_cognition'), ('living', 'nd-exercise_rehabilitation'), ('living', 'nd-cognitive_psychological'),
  ('living', 'nd-neuromodulation_device'), ('living', 'nd-device_other'), ('living', 'nd-digital_health'),
  ('reset', 'immune_reconstitution'), ('reset', 'cell_therapy_tolerance'), ('reset', 'nd-cell_or_transplant');

-- helper: MS trials with their approach tags, running flag and phase
create or replace view bank.v_ms_trials as
select t.*,
       coalesce(t.mechanism_nodes, '{}') || coalesce(array(select 'nd-' || x from unnest(t.nondrug_categories) x), '{}') as approach_tags,
       t.status in ('recruiting', 'not_yet_recruiting', 'active_not_recruiting', 'enrolling_by_invitation', 'ongoing',
                    'ongoing_inferred') as running,
       case when 'phase3' = any(t.phase) then 'phase3' when 'phase2' = any(t.phase) then 'phase2'
            when 'phase4' = any(t.phase) then 'phase4' when 'phase1' = any(t.phase) or 'early_phase1' = any(t.phase)
            then 'phase1' else 'none' end as top_phase
from bank.trials t
where t.study_type = 'interventional' and 'ms' = any(t.diseases);

-- helper: MS hypotheses with their stage (prevention aims sit on Triggers)
create or replace view bank.v_hypothesis_stage as
select h.*, case when h.aim = 'prevent' then 'trigger' else n.stage_id end as stage_id,
       case when h.outcome in ('confirmed', 'supported_one') then 'confirmed'
            when h.outcome in ('failed_early', 'disproven') then 'failed' else h.outcome end as outcome_group
from bank.hypotheses h
left join bank.map_stage_nodes n on n.node_id = h.approach_group
where h.population not in ('nmosd', 'mogad');

-- ---------------------------------------------------------------- 2. the map: one row per stage
create or replace view bank.map_stage_summary as
with hyp as (
  select stage_id,
         count(*) as n_ideas,
         count(*) filter (where outcome_group = 'confirmed') as n_confirmed,
         count(*) filter (where outcome = 'promising') as n_promising,
         count(*) filter (where outcome = 'mixed') as n_mixed,
         count(*) filter (where outcome_group = 'failed') as n_failed,
         count(*) filter (where outcome = 'testing') as n_testing,
         count(*) filter (where outcome = 'pending') as n_pending,
         count(*) filter (where outcome = 'unclear') as n_unclear,
         count(*) filter (where outcome = 'roadmap') as n_not_yet_tested
  from bank.v_hypothesis_stage where stage_id is not null group by stage_id),
tr as (
  select n.stage_id,
         count(distinct t.msf_trial_id) filter (where t.running) as n_running,
         count(distinct t.msf_trial_id) filter (where t.running and t.top_phase = 'phase1') as n_running_phase1,
         count(distinct t.msf_trial_id) filter (where t.running and t.top_phase = 'phase2') as n_running_phase2,
         count(distinct t.msf_trial_id) filter (where t.running and t.top_phase = 'phase3') as n_running_phase3,
         count(distinct t.msf_trial_id) filter (where t.running and t.top_phase = 'phase4') as n_running_phase4,
         count(distinct t.msf_trial_id) filter (where t.running and t.top_phase = 'phase3' and t.controlled
           and t.primary_completion_date between current_date and current_date + interval '24 months') as n_phase3_due_24m,
         min(t.primary_completion_date) filter (where t.running and t.top_phase = 'phase3' and t.controlled
           and t.primary_completion_date >= current_date) as next_phase3_due
  from bank.map_stage_nodes n
  join (select t.*, exists (select 1 from bank.hypothesis_evidence e
                            where e.msf_trial_id = t.msf_trial_id and e.eligible_for_verdict) as controlled
        from bank.v_ms_trials t) t on n.node_id = any(t.approach_tags)
  group by n.stage_id),
lab as (
  select n.stage_id, count(distinct p.pmid) as n_lab_studies,
         count(distinct p.pmid) filter (where p.direction = 'benefit') as n_lab_helped
  from bank.map_stage_nodes n join bank.preclinical_studies p on n.node_id = any(p.approach_groups)
  group by n.stage_id),
idea as (
  select n.stage_id, count(distinct i.idea_id) as n_lab_ideas_not_in_people
  from bank.map_stage_nodes n join bank.preclinical_ideas i on n.node_id = any(i.approach_groups)
  where not coalesce(i.in_human_trials, false) and i.n_papers >= 2
  group by n.stage_id)
select s.stage_id, s.ord, s.label, s.short_label, s.question, s.frontier, s.cross_cutting,
       coalesce(hyp.n_ideas, 0) as n_ideas, coalesce(n_confirmed, 0) as n_confirmed,
       coalesce(n_promising, 0) as n_promising, coalesce(n_mixed, 0) as n_mixed, coalesce(n_failed, 0) as n_failed,
       coalesce(n_testing, 0) as n_testing, coalesce(n_pending, 0) as n_pending, coalesce(n_unclear, 0) as n_unclear,
       coalesce(n_not_yet_tested, 0) as n_not_yet_tested,
       coalesce(n_running, 0) as n_running, coalesce(n_running_phase1, 0) as n_running_phase1,
       coalesce(n_running_phase2, 0) as n_running_phase2, coalesce(n_running_phase3, 0) as n_running_phase3,
       coalesce(n_running_phase4, 0) as n_running_phase4, coalesce(n_phase3_due_24m, 0) as n_phase3_due_24m,
       next_phase3_due,
       coalesce(n_lab_studies, 0) as n_lab_studies, coalesce(n_lab_helped, 0) as n_lab_helped,
       coalesce(n_lab_ideas_not_in_people, 0) as n_lab_ideas_not_in_people
from bank.map_stages s
left join hyp using (stage_id) left join tr using (stage_id) left join lab using (stage_id) left join idea using (stage_id)
order by s.ord;

-- the next phase 3 results per stage (up to 3 each)
create or replace view bank.map_stage_next_results as
select * from (
  select y.*, row_number() over (partition by y.stage_id order by y.primary_completion_date, y.msf_trial_id) as rn
  from (
    select distinct n.stage_id, t.msf_trial_id, t.acronym, t.title, t.drugs, t.population_group, t.enrollment,
           t.primary_completion_date
    from bank.map_stage_nodes n join bank.v_ms_trials t on n.node_id = any(t.approach_tags)
    where t.running and t.top_phase = 'phase3' and t.primary_completion_date >= current_date
      and exists (select 1 from bank.hypothesis_evidence e
                  where e.msf_trial_id = t.msf_trial_id and e.eligible_for_verdict)) y) x
where rn <= 3;

-- ---------------------------------------------------------------- 3. gap index: type of MS x aim
create or replace view bank.gap_index as
with h as (
  select population, population_label, aim, aim_label,
         count(*) as n_ideas,
         count(*) filter (where outcome_group = 'confirmed') as n_confirmed,
         count(*) filter (where outcome_group = 'failed') as n_failed,
         count(*) filter (where outcome = 'testing') as n_testing
  from bank.v_hypothesis_stage
  where population in ('early_cis_ris', 'relapsing', 'relapsing_and_progressive', 'spms', 'ppms')
  group by 1, 2, 3, 4),
e as (
  select e.population, e.aim,
         count(distinct e.msf_trial_id) filter (where e.state = 'ongoing') as n_running,
         count(distinct e.msf_trial_id) filter (where e.state = 'ongoing' and e.phase in ('phase3', 'phase2|phase3')) as n_running_phase3
  from bank.hypothesis_evidence e group by 1, 2)
select h.*, coalesce(e.n_running, 0) as n_running, coalesce(e.n_running_phase3, 0) as n_running_phase3,
       (h.n_confirmed = 0) as no_confirmed_treatment
from h left join e using (population, aim);

-- ---------------------------------------------------------------- 4. open questions
create table if not exists bank.open_questions (
  question_id     text primary key,
  ord             int not null,
  stage_id        text references bank.map_stages(stage_id),
  question        text not null,
  why_it_matters  text not null,
  what_would_answer text not null,
  aims            text[] default '{}',
  approach_groups text[] default '{}',
  populations     text[] default '{}',
  title_pattern   text                 -- case-insensitive regular expression on the trial's title and acronym
);

insert into bank.open_questions (question_id, ord, stage_id, question, why_it_matters, what_would_answer, aims, approach_groups, populations, title_pattern) values
 ('ebv-treatment', 1, 'trigger', 'Does treating Epstein-Barr virus change the course of MS?',
  'Almost everyone with MS has had the virus, so a treatment aimed at it would target a cause rather than the immune response that follows.',
  'Controlled trials of antiviral medicines or EBV-directed cell therapies that reduce disease activity or slow worsening.',
  '{}', '{antiviral_ebv}', '{}', null),
 ('ebv-cells', 2, 'trigger', 'Can T cells trained against EBV-infected cells help people with MS?',
  'If infected B cells keep the disease going, removing them could act more precisely than removing all B cells.',
  'Randomised trials of EBV-specific T-cell therapy with clinical or MRI endpoints.',
  '{}', '{cell_therapy_tolerance}', '{}', 'ebv|epstein|tabelecleucel|ata188'),
 ('prevent-early', 3, 'trigger', 'Can treating a first episode, or MRI changes alone, delay or prevent MS?',
  'People with a first episode or with typical MRI lesions but no symptoms are at high risk of developing MS.',
  'Placebo-controlled trials in clinically isolated or radiologically isolated syndrome that delay a first or second attack.',
  '{prevent}', '{}', '{early_cis_ris}', null),
 ('vitamin-d', 4, 'trigger', 'Does vitamin D, or another supplement, reduce disease activity?',
  'Low vitamin D is linked to the risk of MS, but a link is not proof that taking more helps.',
  'Large randomised trials with relapses, new lesions or disability as the main outcome.',
  '{}', '{nutritional_supplement}', '{}', null),
 ('diet', 5, 'trigger', 'Does a particular diet change the course of MS?',
  'Diet is one of the questions people with MS ask most, and the evidence so far comes mostly from small studies.',
  'Randomised trials long enough to measure relapses, MRI activity or disability, not only fatigue or wellbeing.',
  '{}', '{nd-diet_nutrition}', '{}', null),
 ('early-high-efficacy', 6, 'immune', 'Does starting with a highly effective medicine give a better long-term course than escalating?',
  'Most people still start with a milder medicine and switch if the disease stays active.',
  'Large randomised strategy trials comparing early high-efficacy treatment with escalation over several years.',
  '{}', '{}', '{}', 'early (aggressive|intensive|high[- ]?efficacy)|escalation (therapy|strategy|approach)|deliver-ms|treat-ms|high[- ]?efficacy (therapy|treatment) (vs|versus|compared)'),
 ('stopping-treatment', 7, 'immune', 'Can treatment be stopped safely in older people whose MS has been stable for years?',
  'Relapses become rarer with age while the risks of immune treatment, such as infections, rise.',
  'Randomised trials of stopping against continuing, with relapses, MRI activity and disability as outcomes.',
  '{}', '{}', '{}', 'discontinu|stopping|cessation|de-?escalat|withdraw(al)? of'),
 ('dosing', 8, 'immune', 'Do longer intervals between doses work as well as standard dosing?',
  'Less frequent dosing could lower costs and some risks, such as infections and progressive multifocal leukoencephalopathy.',
  'Randomised non-inferiority trials of extended or personalised dosing against standard dosing.',
  '{}', '{}', '{}', 'extended interval|dosing interval|personali[sz]ed dos|reduced dos|dose interval'),
 ('bcell-pira', 9, 'immune', 'Do B-cell therapies slow disability worsening that happens without relapses?',
  'Most disability builds up without relapses, and it is unclear how much current medicines prevent it.',
  'Trials and long follow-up analyses that measure worsening independent of relapses as a main outcome.',
  '{slow_progression}', '{anti_cd20_b_cell,other_b_cell_plasma_cell}', '{}', null),
 ('ahsct', 10, 'reset', 'Is stem cell transplantation better than the most effective medicines?',
  'Transplantation can stop inflammatory MS for years after one treatment, but it carries serious risks.',
  'Randomised trials comparing transplantation with high-efficacy medicines, with disability over several years.',
  '{}', '{immune_reconstitution,nd-cell_or_transplant}', '{}', 'stem cell|hsct|transplant'),
 ('car-t', 11, 'reset', 'Can CAR-T cell therapy stop MS without continuous treatment?',
  'CAR-T cells can remove B cells deep in tissues, and in other autoimmune diseases have led to long remissions.',
  'Trials showing lasting absence of disease activity after one treatment, with an acceptable safety record.',
  '{}', '{cell_therapy_tolerance}', '{}', 'car[- ]?t|chimeric antigen|autoleucel|zapreleucel'),
 ('tolerance', 12, 'reset', 'Can the immune system be retrained to tolerate myelin?',
  'A treatment that switches off only the attack on myelin would leave the rest of the immune system working.',
  'Controlled trials of antigen-specific treatments that reduce new lesions or relapses.',
  '{}', '{cell_therapy_tolerance}', '{}', 'toleri|tolerogenic|peptide|antigen-specific|dendritic|plovamer|myelin'),
 ('btk-progression', 13, 'smouldering', 'Do BTK inhibitors slow progression without relapses?',
  'BTK inhibitors reach immune cells inside the brain, where the inflammation behind progression is thought to sit.',
  'Phase 3 trials in progressive MS with confirmed disability worsening as the main outcome.',
  '{slow_progression}', '{btk_inhibition}', '{}', null),
 ('rim-lesions', 14, 'smouldering', 'Can treatment quieten chronic active lesions?',
  'Lesions with an iron rim keep expanding slowly and are linked to faster worsening.',
  'Trials that measure paramagnetic rim lesions or slowly expanding lesions on MRI as an outcome.',
  '{}', '{}', '{}', 'rim lesion|paramagnetic|slowly expanding|chronic active|smoulder|smolder'),
 ('microglia', 15, 'smouldering', 'Do medicines aimed at microglia slow progression?',
  'Microglia, the brain''s own immune cells, are active at the edge of chronic lesions.',
  'Controlled trials of microglia-directed medicines with disability or brain shrinkage as the main outcome.',
  '{}', '{microglia_innate}', '{}', null),
 ('energy', 16, 'damage', 'Can protecting the energy supply of nerve fibres slow progression?',
  'Nerve fibres that have lost myelin need more energy, and their mitochondria are damaged in progressive MS.',
  'Phase 3 trials of mitochondrial or antioxidant treatments with disability as the main outcome.',
  '{}', '{mitochondrial_oxidative}', '{}', null),
 ('neuroprotection-on', 17, 'damage', 'Can nerve fibres be protected after optic neuritis?',
  'Optic neuritis allows damage and protection to be measured precisely in the eye within months.',
  'Controlled trials with retinal thickness on OCT or vision as the main outcome.',
  '{}', '{}', '{optic_neuritis}', null),
 ('vascular', 18, 'damage', 'Does treating vascular risk factors slow progression?',
  'High blood pressure, raised cholesterol and smoking are linked to faster worsening, and they can be treated.',
  'Randomised trials of statins or blood pressure medicines with disability as the main outcome.',
  '{}', '{vascular_lipid,blood_pressure}', '{}', null),
 ('hormones', 19, 'damage', 'Do sex hormones influence progression?',
  'Some studies suggest disability builds up faster after the menopause, and hormones act on both immune cells and myelin repair.',
  'Controlled trials of hormone treatments with disability, cognition or MRI outcomes.',
  '{}', '{hormonal}', '{}', null),
 ('remyelination', 20, 'repair', 'Can a medicine increase remyelination in people, and does it improve function?',
  'No treatment that repairs myelin is approved, although several have shown signals in small trials.',
  'Trials showing repair on a myelin measure, followed by trials showing better function in daily life.',
  '{}', '{remyelination}', '{}', null),
 ('cell-repair', 21, 'repair', 'Can transplanted cells repair the brain or spinal cord?',
  'Stem and precursor cells could in principle replace the cells that make myelin or calm inflammation locally.',
  'Controlled trials of cell transplants with disability or MRI measures of repair.',
  '{}', '{nd-cell_or_transplant,cell_therapy_tolerance}', '{}', 'mesenchymal|neural|precursor|stromal|stem cell'),
 ('ppms', 22, 'damage', 'What slows primary progressive MS?',
  'Only one medicine has slowed disability worsening in a phase 3 trial of primary progressive MS.',
  'Phase 3 trials in primary progressive MS with confirmed disability worsening as the main outcome.',
  '{slow_progression}', '{}', '{ppms}', null),
 ('spms', 23, 'damage', 'What slows secondary progressive MS without relapses?',
  'The medicines approved for secondary progressive MS work mainly in people who still have inflammatory activity.',
  'Phase 3 trials in non-active secondary progressive MS with disability as the main outcome.',
  '{slow_progression}', '{}', '{spms}', null),
 ('fatigue', 24, 'living', 'Which treatments reduce MS fatigue?',
  'Fatigue is among the most common and most limiting symptoms, and medicines tested so far have shown small effects.',
  'Randomised trials with a validated fatigue scale as the main outcome, long enough to show lasting benefit.',
  '{}', '{}', '{}', 'fatigue'),
 ('cognition', 25, 'living', 'Which treatments help thinking and memory?',
  'Changes in thinking affect work and daily life, often more than physical symptoms.',
  'Randomised trials with a cognitive test such as the Symbol Digit Modalities Test as the main outcome.',
  '{}', '{}', '{}', 'cogniti|memory|processing speed'),
 ('exercise', 26, 'living', 'Can exercise and rehabilitation slow disability, not only improve fitness?',
  'Exercise helps fatigue and fitness, and some studies suggest it may also protect the brain.',
  'Long randomised trials with disability or brain shrinkage as outcomes.',
  '{}', '{nd-exercise_rehabilitation}', '{}', null),
 ('bladder', 27, 'living', 'Which treatments work best for bladder problems?',
  'Bladder symptoms are common and often under-treated.',
  'Randomised trials comparing medicines, injections and nerve stimulation on symptoms and quality of life.',
  '{}', '{bladder}', '{}', null),
 ('spasticity', 28, 'living', 'Which treatments ease stiffness and spasms?',
  'Spasticity limits walking and sleep, and current medicines can cause drowsiness and weakness.',
  'Randomised trials with spasticity and walking as outcomes.',
  '{}', '{spasticity}', '{}', null),
 ('stimulation', 29, 'living', 'Do brain or nerve stimulation devices help symptoms?',
  'Devices could ease symptoms without the side effects of medicines.',
  'Sham-controlled randomised trials with symptom or function outcomes.',
  '{}', '{nd-neuromodulation_device}', '{}', null),
 ('blood-markers', 30, null, 'Can a blood test guide treatment decisions?',
  'Neurofilament light in blood rises with nerve damage and could show disease activity before symptoms do.',
  'Trials in which treatment decisions are based on blood markers, compared with usual care.',
  '{}', '{}', '{}', 'neurofilament|\mnfl\M|gfap')
on conflict (question_id) do update set ord = excluded.ord, stage_id = excluded.stage_id, question = excluded.question,
  why_it_matters = excluded.why_it_matters, what_would_answer = excluded.what_would_answer, aims = excluded.aims,
  approach_groups = excluded.approach_groups, populations = excluded.populations, title_pattern = excluded.title_pattern;

-- trials that address each question: through the hypothesis evidence (approach, aim, type of MS), or for
-- questions defined only by words, through the trial titles
create or replace view bank.open_question_trials as
with ev as (
  select distinct q.question_id, e.msf_trial_id
  from bank.open_questions q join bank.hypothesis_evidence e
    on (cardinality(q.approach_groups) = 0 or e.approach_group = any(q.approach_groups))
   and (cardinality(q.aims) = 0 or e.aim = any(q.aims))
   and (cardinality(q.populations) = 0 or e.population = any(q.populations))
  where cardinality(q.approach_groups) + cardinality(q.aims) + cardinality(q.populations) > 0),
tt as (
  select q.question_id, t.msf_trial_id
  from bank.open_questions q join bank.v_ms_trials t
    on q.title_pattern is not null
   and (coalesce(t.title, '') || ' ' || coalesce(t.official_title, '') || ' ' || coalesce(t.acronym, '')) ~* q.title_pattern)
select x.question_id, t.msf_trial_id, t.acronym, t.title, t.drugs, t.top_phase, t.status, t.running,
       t.population_group, t.enrollment, t.primary_completion_date, t.result_signal
from (
  -- a question with both rules (for example CAR-T within cell therapies) needs both to match
  select ev.question_id, ev.msf_trial_id from ev
  join bank.open_questions q using (question_id)
  where q.title_pattern is null
     or exists (select 1 from tt where tt.question_id = ev.question_id and tt.msf_trial_id = ev.msf_trial_id)
  union
  select tt.question_id, tt.msf_trial_id from tt
  join bank.open_questions q using (question_id)
  where cardinality(q.approach_groups) + cardinality(q.aims) + cardinality(q.populations) = 0) x
join bank.v_ms_trials t using (msf_trial_id);

create or replace view bank.open_questions_status as
select q.question_id, q.ord, q.stage_id, s.label as stage_label, q.question, q.why_it_matters, q.what_would_answer,
       count(t.msf_trial_id) filter (where t.running) as n_running,
       count(t.msf_trial_id) filter (where t.running and t.top_phase = 'phase3') as n_running_phase3,
       count(t.msf_trial_id) filter (where not t.running and t.status in ('completed', 'completed_inferred', 'terminated')) as n_finished,
       min(t.primary_completion_date) filter (where t.running and t.primary_completion_date >= current_date) as next_result_due,
       (array_agg(coalesce(t.acronym, left(t.title, 80)) order by t.primary_completion_date)
          filter (where t.running and t.primary_completion_date >= current_date))[1] as next_result_trial,
       (array_agg(t.msf_trial_id order by t.primary_completion_date)
          filter (where t.running and t.primary_completion_date >= current_date))[1] as next_result_trial_id
from bank.open_questions q
left join bank.map_stages s on s.stage_id = q.stage_id
left join bank.open_question_trials t using (question_id)
group by q.question_id, q.ord, q.stage_id, s.label, q.question, q.why_it_matters, q.what_would_answer
order by q.ord;

-- ---------------------------------------------------------------- 5. evidence patterns
-- did a positive phase 2 predict a positive phase 3? One row per hypothesis with controlled readouts at both phases.
create or replace view bank.phase2_to_phase3 as
with r as (
  select e.hypothesis_id,
         case when e.phase in ('phase3', 'phase2|phase3') then 'p3' when e.phase = 'phase2' then 'p2' end as ph,
         e.state
  from bank.hypothesis_evidence e
  where e.counts_toward_verdict and e.state in ('met', 'not_met', 'mixed', 'stopped_no_effect')),
g as (
  select hypothesis_id, ph,
         count(*) filter (where state = 'met') as n_met,
         count(*) filter (where state in ('not_met', 'stopped_no_effect')) as n_not_met,
         count(*) filter (where state = 'mixed') as n_mixed
  from r where ph is not null group by 1, 2),
c as (
  select hypothesis_id, ph, n_met, n_not_met,
         case when n_mixed > 0 or (n_met > 0 and n_not_met > 0) then 'mixed' when n_met > 0 then 'met' else 'not_met' end as result
  from g)
select h.hypothesis_id, h.approach_group, h.approach_group_label, h.approach_family, h.aim_label, h.population_label,
       p2.result as phase2_result, p2.n_met as phase2_met, p2.n_not_met as phase2_not_met,
       p3.result as phase3_result, p3.n_met as phase3_met, p3.n_not_met as phase3_not_met
from bank.hypotheses h
join c p2 on p2.hypothesis_id = h.hypothesis_id and p2.ph = 'p2'
join c p3 on p3.hypothesis_id = h.hypothesis_id and p3.ph = 'p3';

create or replace view bank.phase2_to_phase3_summary as
select phase2_result, phase3_result, count(*) as n_ideas
from bank.phase2_to_phase3 group by 1, 2 order by 1, 2;

-- how often controlled trials met their main goal, by kind of approach and phase
create or replace view bank.success_by_family as
select h.approach_family,
       case when e.phase in ('phase3', 'phase2|phase3') then 'phase3' when e.phase = 'phase2' then 'phase2' end as phase,
       count(distinct e.msf_trial_id) filter (where e.state = 'met') as n_met,
       count(distinct e.msf_trial_id) filter (where e.state in ('not_met', 'stopped_no_effect')) as n_not_met,
       count(distinct e.msf_trial_id) filter (where e.state = 'mixed') as n_mixed
from bank.hypothesis_evidence e join bank.hypotheses h using (hypothesis_id)
where e.counts_toward_verdict and e.phase in ('phase2', 'phase3', 'phase2|phase3') and h.population not in ('nmosd', 'mogad')
group by 1, 2 order by 1, 2;

-- trial design over time: size, length, placebo use and stopping, by phase and five-year period
create or replace view bank.design_benchmarks as
with t as (
  select v.*, (floor(v.start_year / 5) * 5)::int as period_start
  from bank.v_ms_trials v
  where v.top_phase in ('phase2', 'phase3') and v.start_year between 2000 and extract(year from current_date))
select top_phase as phase, period_start,
       count(*) as n_trials,
       percentile_cont(0.5) within group (order by enrollment) filter (where enrollment > 0) as median_participants,
       percentile_cont(0.5) within group (order by (primary_completion_date - start_date) / 30.44)
         filter (where primary_completion_date > start_date and status in ('completed', 'completed_inferred')) as median_months_to_main_result,
       round(100.0 * count(*) filter (where has_placebo_or_sham) / nullif(count(*), 0), 1) as pct_placebo_controlled,
       -- only for periods that ended at least six years ago: in recent years the trials that stop early finish first
       case when period_start + 5 <= extract(year from current_date) - 6 then
         round(100.0 * count(*) filter (where status = 'terminated')
               / nullif(count(*) filter (where status in ('completed', 'completed_inferred', 'terminated')), 0), 1)
       end as pct_stopped_early
from t group by 1, 2 order by 1, 2;

create or replace view bank.stop_reasons as
select top_phase as phase, coalesce(why_stopped_class, 'not_given') as reason, count(*) as n_trials
from bank.v_ms_trials where status = 'terminated' and top_phase in ('phase1', 'phase2', 'phase3', 'phase4')
group by 1, 2 order by 1, 3 desc;

-- lab evidence and trials in people, side by side, for each approach group
create or replace view bank.lab_to_people as
with lab as (
  select g as approach_group, count(distinct pmid) as n_lab_studies,
         count(distinct pmid) filter (where direction = 'benefit') as n_lab_helped
  from bank.preclinical_studies, unnest(approach_groups) g where study_type = 'intervention' group by 1),
hum as (
  select approach_group, max(approach_group_label) as approach_group_label,
         count(*) filter (where outcome_group = 'confirmed') as n_confirmed,
         count(*) filter (where outcome = 'promising') as n_promising,
         count(*) filter (where outcome = 'mixed') as n_mixed,
         count(*) filter (where outcome_group = 'failed') as n_failed,
         count(*) filter (where outcome = 'testing') as n_testing
  from bank.v_hypothesis_stage group by 1)
select lab.approach_group, hum.approach_group_label, lab.n_lab_studies, lab.n_lab_helped,
       round(100.0 * lab.n_lab_helped / nullif(lab.n_lab_studies, 0)) as pct_lab_helped,
       coalesce(hum.n_confirmed, 0) as n_confirmed, coalesce(hum.n_promising, 0) as n_promising,
       coalesce(hum.n_mixed, 0) as n_mixed, coalesce(hum.n_failed, 0) as n_failed, coalesce(hum.n_testing, 0) as n_testing
from lab left join hum using (approach_group)
where lab.n_lab_studies >= 5 and hum.approach_group_label is not null
order by lab.n_lab_studies desc;

-- before the result: placebo-controlled phase 3 trials due within 24 months, one row per trial, with what earlier
-- evidence showed for the same approach
create or replace view bank.phase3_before_result as
with up as (
  select e.msf_trial_id, e.hypothesis_id
  from bank.hypothesis_evidence e
  where e.state = 'ongoing' and e.phase in ('phase3', 'phase2|phase3') and e.eligible_for_verdict
    and e.has_placebo_or_sham),
p2 as (
  select hypothesis_id, count(*) filter (where state = 'met') as p2_met,
         count(*) filter (where state in ('not_met', 'stopped_no_effect')) as p2_not_met
  from bank.hypothesis_evidence where counts_toward_verdict and phase = 'phase2' group by 1),
grp as (
  select h.approach_group,
         count(distinct e.msf_trial_id) filter (where e.state = 'met') as group_p3_met,
         count(distinct e.msf_trial_id) filter (where e.state in ('not_met', 'stopped_no_effect')) as group_p3_not_met
  from bank.hypothesis_evidence e join bank.hypotheses h using (hypothesis_id)
  where e.counts_toward_verdict and e.phase in ('phase3', 'phase2|phase3') group by 1),
lab as (
  select g as approach_group, count(distinct pmid) as n_lab_studies
  from bank.preclinical_studies, unnest(approach_groups) g group by 1)
select t.msf_trial_id, t.acronym, t.title, t.drugs, t.enrollment, t.primary_completion_date, t.population_group,
       (array_agg(distinct h.approach_group_label))[1] as approach_group_label,
       array_agg(distinct h.aim_label) as aims,
       array_agg(distinct h.hypothesis_id) as hypothesis_ids,
       max(coalesce(p2.p2_met, 0)) as phase2_met_same_group,
       max(coalesce(p2.p2_not_met, 0)) as phase2_not_met_same_group,
       max(coalesce(grp.group_p3_met, 0)) as approach_phase3_met_any_group,
       max(coalesce(grp.group_p3_not_met, 0)) as approach_phase3_not_met_any_group,
       max(coalesce(lab.n_lab_studies, 0)) as n_lab_studies
from up join bank.v_ms_trials t using (msf_trial_id)
join bank.hypotheses h using (hypothesis_id)
left join p2 using (hypothesis_id) left join grp on grp.approach_group = h.approach_group
left join lab on lab.approach_group = h.approach_group
where t.running and t.primary_completion_date between current_date and current_date + interval '24 months'
group by t.msf_trial_id, t.acronym, t.title, t.drugs, t.enrollment, t.primary_completion_date, t.population_group
order by t.primary_completion_date;

-- ---------------------------------------------------------------- access
alter table bank.map_stages enable row level security;
alter table bank.map_stage_nodes enable row level security;
alter table bank.open_questions enable row level security;
drop policy if exists public_read on bank.map_stages;
create policy public_read on bank.map_stages for select using (true);
drop policy if exists public_read on bank.map_stage_nodes;
create policy public_read on bank.map_stage_nodes for select using (true);
drop policy if exists public_read on bank.open_questions;
create policy public_read on bank.open_questions for select using (true);
grant select on bank.map_stages, bank.map_stage_nodes, bank.open_questions, bank.v_ms_trials, bank.v_hypothesis_stage,
  bank.map_stage_summary, bank.map_stage_next_results, bank.gap_index, bank.open_question_trials,
  bank.open_questions_status, bank.phase2_to_phase3, bank.phase2_to_phase3_summary, bank.success_by_family,
  bank.design_benchmarks, bank.stop_reasons, bank.lab_to_people, bank.phase3_before_result to anon, authenticated;
grant all on bank.map_stages, bank.map_stage_nodes, bank.open_questions to service_role;
