-- 023_review_fixes.sql: fixes from the site review of 5 November 2026. Run after 022. Safe to re-run.
--   1. the ledger says why a trial does or does not count, in the words of the rule
--   2. a conference report carries the month of the meeting, not 1 January
--   3. medicine-level hypotheses list only their own medicine, not every arm of the trial
--   4. a trial marked as running long after it should have finished is not counted as running

-- ---------------------------------------------------------------- 1. why a trial counts
create or replace view bank.hypothesis_ledger as
select e.hypothesis_id, e.msf_trial_id, coalesce(n.name, e.acronym, e.title) as name, e.phase, e.state, e.is_rct,
       e.has_placebo_or_sham, e.enrollment, e.start_year, e.eligible_for_verdict, e.counts_toward_verdict,
       case
         -- counts, and has said something
         when e.counts_toward_verdict and e.state in ('met', 'not_met', 'mixed', 'stopped_no_effect', 'equivalent')
           then 'Counted'
         when e.counts_toward_verdict and e.state = 'ongoing' then 'Will count when it reports'
         when e.counts_toward_verdict and e.state in ('no_result_found', 'result_in_paper_unread')
           then 'Will count once its result is read'
         when e.counts_toward_verdict and e.state like 'stopped%' then 'Stopped before a result'
         when e.counts_toward_verdict then 'Counted'
         -- does not count, and why
         when not coalesce(e.is_rct, false) then 'Not counted: not randomised'
         when not e.eligible_for_verdict and e.phase !~ 'phase[23]'
           then 'Not counted: phase 1 or phase 4'
         when not e.eligible_for_verdict then 'Not counted: tested as the comparator'
         when coalesce(array_length(e.comparator_drugs, 1), 0) > 0 and e.state in ('not_met', 'equivalent', 'stopped_no_effect')
           then 'Not counted: did not beat an active medicine (' || array_to_string(e.comparator_drugs, ', ') || '), which says nothing about placebo'
         when coalesce(array_length(e.comparator_drugs, 1), 0) > 0 and e.state = 'ongoing'
           then 'Will count only if it beats ' || array_to_string(e.comparator_drugs, ', ')
         when coalesce(array_length(e.comparator_drugs, 1), 0) > 0
           then 'Counts only if it beats ' || array_to_string(e.comparator_drugs, ', ')
         when not coalesce(e.has_placebo_or_sham, false) then 'Not counted: no placebo or sham group'
         when e.aim = 'stop_inflammation' and e.state <> 'met'
           then 'Not counted: added on top of a medicine that already controls relapses, so a miss says little'
         when e.state = 'ongoing' then 'Not counted yet: still running'
         else 'Not counted: ' || replace(e.state, '_', ' ') end as why,
       e.readout_quote, e.readout_pmid,
       r.result as reported_result, r.kind_label as reported_kind
from bank.hypothesis_evidence e
left join bank.trial_names n using (msf_trial_id)
left join bank.trial_latest_report r using (msf_trial_id);

-- ---------------------------------------------------------------- 2. conference reports carry the meeting month
create or replace view bank.trial_reported_results as
select a.msf_trial_id, a.announcement_id as id, a.source_type, a.source, a.title, a.url, a.published_at,
       a.result,
       case a.result when 'met' then 'Main goal met' when 'not_met' then 'Main goal not met' when 'mixed' then 'Mixed'
                     when 'safety' then 'Safety finding' else 'Reported' end as result_label,
       a.measure, a.summary, a.peer_reviewed,
       case when a.source_type = 'conference' then 'Reported at a conference' else 'Reported by the sponsor' end as kind_label
from bank.trial_announcements a
union all
select c.msf_trial_id, c.report_id, 'conference', c.meeting || ' ' || c.year, c.title, c.url,
       make_date(c.year, case upper(c.meeting) when 'AAN' then 4 when 'ACTRIMS' then 2 when 'ECTRIMS' then 9 else 6 end, 1),
       null, 'Abstract', null, left(c.conclusion_text, 400), false, 'Presented at a conference'
from bank.conference_reports c
where not exists (select 1 from bank.trial_announcements a where a.announcement_id = c.report_id)
order by published_at desc nulls last;

-- ---------------------------------------------------------------- 3. one medicine for medicine-level hypotheses
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
              and e.approach_group = any(i.mechanism_nodes)
              -- "spasticity.fluoxetine" is about fluoxetine only, however many arms the trial had
              and (e.approach not like '%.%'
                   or regexp_replace(lower(i.drug_name), '[^a-z0-9]+', '-', 'g') = split_part(e.approach, '.', 2))) d) x
group by hypothesis_id;

-- ---------------------------------------------------------------- 4. a stale "running" is not running
-- The build now sets such records to 'unknown' (build.py, infer_status). This guard covers the rows loaded before
-- that change and any registry that keeps reporting a long-finished trial as ongoing.
create or replace view bank.v_ms_trials as
select t.*,
       coalesce(t.mechanism_nodes, '{}') || coalesce(array(select 'nd-' || x from unnest(t.nondrug_categories) x), '{}') as approach_tags,
       t.status in ('recruiting', 'not_yet_recruiting', 'active_not_recruiting', 'enrolling_by_invitation', 'ongoing',
                    'ongoing_inferred')
         and not (coalesce(t.primary_completion_date, t.completion_date) < current_date - interval '2 years'
                  and coalesce(t.last_update, date '1900-01-01') < current_date - interval '1 year')
         and not (t.primary_completion_date is null and t.completion_date is null
                  and t.start_date < current_date - interval '6 years'
                  and coalesce(t.last_update, date '1900-01-01') < current_date - interval '1 year') as running,
       case when 'phase3' = any(t.phase) then 'phase3' when 'phase2' = any(t.phase) then 'phase2'
            when 'phase4' = any(t.phase) then 'phase4' when 'phase1' = any(t.phase) or 'early_phase1' = any(t.phase)
            then 'phase1' else 'none' end as top_phase
from bank.trials t
where t.study_type = 'interventional' and 'ms' = any(t.diseases);

grant select on bank.hypothesis_ledger, bank.trial_reported_results, bank.hypothesis_medicines, bank.v_ms_trials
  to anon, authenticated;
