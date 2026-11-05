-- 024_effect_sizes.sql: how much a treatment changed the main measures, from registry results and result papers.
-- Run after 023. Safe to re-run.

create table if not exists bank.trial_effects (
  effect_id              text primary key,
  msf_trial_id           text not null references bank.trials(msf_trial_id) on delete cascade,
  source                 text not null,          -- registry, paper
  pmid                   text,
  outcome_type           text,                   -- primary, secondary, other
  measure                text,
  time_frame             text,
  family                 text,                   -- relapse, disability_progression, mri_lesions, brain_atrophy, walking_mobility, ...
  effect_type            text,                   -- hazard_ratio, rate_ratio, odds_ratio, risk_ratio, mean_difference, percent_difference, percent_reduction, other
  effect_type_raw        text,
  estimate               double precision,
  ci_low                 double precision,
  ci_high                double precision,
  p_value                double precision,
  comparator             text,                   -- placebo, or the medicine(s) compared against
  comparator_is_placebo  boolean,
  treatment              text,
  treatment_value        double precision,       -- the arm's own value (a relapse rate, a proportion, a mean)
  comparator_value       double precision,
  treatment_n            int,
  comparator_n           int,
  value_unit             text,
  n_arms                 int,
  favours                text,                   -- treatment, comparator, neither, or null where the direction is not beyond doubt
  relative_reduction_pct double precision,       -- for a ratio below 1 on a bad event, when the result is significant
  absolute_diff_per_100  double precision,       -- comparator value minus treatment value, per 100 people
  quote                  text,
  version                text,
  loaded_at              timestamptz default now()
);
create index if not exists trial_effects_trial on bank.trial_effects (msf_trial_id);
create index if not exists trial_effects_family on bank.trial_effects (family, effect_type);

-- every effect with the trial's name, phase, population and year, and a slug for the medicine page
create or replace view bank.trial_effects_public as
select e.*, coalesce(n.name, t.acronym, t.title) as trial_name, t.top_phase, t.phase, t.population_group,
       bank.population_label(t.population_group) as population_label, t.start_year, t.enrollment, t.sponsor_class,
       regexp_replace(lower(split_part(e.treatment, ',', 1)), '[^a-z0-9]+', '-', 'g') as treatment_slug,
       case e.family when 'relapse' then 'Relapses' when 'disability_progression' then 'Disability progression'
                     when 'mri_lesions' then 'New lesions on MRI' when 'brain_atrophy' then 'Brain volume loss'
                     when 'walking_mobility' then 'Walking' when 'upper_limb' then 'Hand and arm function'
                     when 'cognition' then 'Cognition' when 'fatigue' then 'Fatigue' when 'spasticity' then 'Spasticity'
                     when 'pain' then 'Pain' when 'bladder_bowel_sexual' then 'Bladder and bowel'
                     when 'mood_sleep' then 'Mood and sleep' when 'quality_of_life_pro' then 'Quality of life'
                     when 'vision' then 'Vision' when 'fluid_biomarker' then 'Blood and fluid markers'
                     when 'remyelination' then 'Remyelination' when 'immune_response' then 'Immune response'
                     else 'Other' end as family_label,
       case e.effect_type when 'hazard_ratio' then 'Hazard ratio' when 'rate_ratio' then 'Rate ratio'
                          when 'odds_ratio' then 'Odds ratio' when 'risk_ratio' then 'Risk ratio'
                          when 'mean_difference' then 'Difference in means' when 'percent_difference' then 'Difference in per cent'
                          when 'percent_reduction' then 'Relative reduction' else 'Estimate' end as effect_type_label
from bank.trial_effects e
join bank.v_ms_trials t using (msf_trial_id)
left join bank.trial_names n using (msf_trial_id);

-- the chart: relapses and disability progression in phase 2 and 3 trials, one row per trial and measure,
-- the primary outcome where the trial has one for that measure, otherwise the first secondary
create or replace view bank.how_much_help as
with ranked as (
  select e.*, row_number() over (partition by e.msf_trial_id, e.family, e.comparator
                                 order by (e.outcome_type = 'primary') desc, (e.source = 'registry') desc, e.treatment_n desc nulls last) as rn
  from bank.trial_effects_public e
  where e.family in ('relapse', 'disability_progression')
    and e.effect_type in ('rate_ratio', 'hazard_ratio', 'risk_ratio', 'odds_ratio', 'percent_reduction')
    and e.top_phase in ('phase2', 'phase3')
    and e.estimate is not null)
select msf_trial_id, trial_name, top_phase, population_group, population_label, start_year, enrollment,
       treatment, treatment_slug, comparator, comparator_is_placebo, family, family_label, outcome_type, measure,
       effect_type, effect_type_label, estimate, ci_low, ci_high, p_value, favours, relative_reduction_pct,
       treatment_value, comparator_value, absolute_diff_per_100, source, pmid
from ranked where rn = 1
order by family, comparator_is_placebo desc, estimate;

-- one line per medicine for the medicine page: its best placebo-controlled or active-controlled result on relapses
create or replace view bank.medicine_headline_effect as
select distinct on (treatment_slug)
       treatment_slug, treatment, msf_trial_id, trial_name, comparator, estimate, ci_low, ci_high,
       relative_reduction_pct, treatment_value, comparator_value, absolute_diff_per_100, family, start_year
from bank.how_much_help
where favours = 'treatment' and family = 'relapse'
order by treatment_slug, (top_phase = 'phase3') desc, comparator_is_placebo desc, enrollment desc nulls last;

alter table bank.trial_effects enable row level security;
drop policy if exists public_read on bank.trial_effects;
create policy public_read on bank.trial_effects for select using (true);
grant select on bank.trial_effects, bank.trial_effects_public, bank.how_much_help, bank.medicine_headline_effect
  to anon, authenticated;
grant all on bank.trial_effects to service_role;
