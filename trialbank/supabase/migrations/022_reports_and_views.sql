-- 022_reports_and_views.sql: conference reports and company announcements as provisional results, plus the views
-- for "how a verdict was reached", "who funds what", "reviews against trials" and "time to publication".
-- Run after 021. Safe to re-run.

-- ---------------------------------------------------------------- 1. provisional results
create table if not exists bank.conference_reports (
  report_id         text primary key,          -- <meeting><year>-<number>:<msf_trial_id>
  meeting           text not null,             -- AAN, ECTRIMS, ACTRIMS
  year              int not null,
  abstract_number   text,
  msf_trial_id      text not null references bank.trials(msf_trial_id) on delete cascade,
  title             text,
  authors           text,
  results_text      text,
  conclusion_text   text,
  kind              text,                      -- trial_result, late_breaking, other
  match_rule        text,
  url               text,
  harvested_version text,
  loaded_at         timestamptz default now()
);
create index if not exists conference_reports_trial on bank.conference_reports (msf_trial_id);

create table if not exists bank.trial_announcements (
  announcement_id text primary key,            -- <news item id>:<msf_trial_id>
  msf_trial_id    text not null references bank.trials(msf_trial_id) on delete cascade,
  source          text,
  source_type     text,                        -- announcement (press release or news), conference
  title           text,
  url             text,
  published_at    date,
  result          text,                        -- met, not_met, mixed, safety
  measure         text,
  summary         text,
  peer_reviewed   boolean default false,
  match_rule      text,
  read_by         text,
  provisional     boolean default true,
  loaded_at       timestamptz default now()
);
create index if not exists trial_announcements_trial on bank.trial_announcements (msf_trial_id);

-- one list per trial, newest first: what has been reported before the paper
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
       make_date(c.year, 1, 1), null, 'Abstract', null, left(c.conclusion_text, 400), false, 'Presented at a conference'
from bank.conference_reports c
where not exists (select 1 from bank.trial_announcements a where a.announcement_id = c.report_id)
order by published_at desc nulls last;

-- the latest provisional result per trial, for lists and cards
create or replace view bank.trial_latest_report as
select distinct on (msf_trial_id) msf_trial_id, result, result_label, kind_label, source, published_at, url, summary
from bank.trial_reported_results
where result is not null
order by msf_trial_id, published_at desc nulls last;

-- ---------------------------------------------------------------- 2. how a verdict was reached
create or replace view bank.hypothesis_ledger as
select e.hypothesis_id, e.msf_trial_id, coalesce(n.name, e.acronym, e.title) as name, e.phase, e.state, e.is_rct,
       e.has_placebo_or_sham, e.enrollment, e.start_year, e.eligible_for_verdict, e.counts_toward_verdict,
       case when e.counts_toward_verdict then 'Counted'
            when not e.eligible_for_verdict and not coalesce(e.is_rct, false) then 'Not counted: not randomised'
            when not e.eligible_for_verdict then 'Not counted: no control group or too early a phase'
            when e.state = 'ongoing' then 'Not counted yet: still running'
            when e.state in ('no_readout', 'unread') then 'Not counted: no result read yet'
            else 'Not counted: ' || replace(e.state, '_', ' ') end as why,
       e.readout_quote, e.readout_pmid,
       r.result as reported_result, r.kind_label as reported_kind
from bank.hypothesis_evidence e
left join bank.trial_names n using (msf_trial_id)
left join bank.trial_latest_report r using (msf_trial_id);

-- ---------------------------------------------------------------- 3. who funds what
create or replace view bank.area_funding as
select ta.area_id, ra.title, ra.ord,
       case when t.sponsor_class = 'industry' then 'Industry'
            when t.sponsor_class in ('nih', 'fed', 'other_gov') then 'Government'
            when t.sponsor_class in ('other', 'network', 'indiv') then 'Academic and charities'
            else 'Other' end as funder,
       count(*) filter (where t.running) as n_running,
       count(*) as n_trials,
       count(*) filter (where t.status in ('terminated', 'withdrawn', 'suspended')) as n_stopped,
       round(100.0 * count(*) filter (where t.running) / nullif(sum(count(*) filter (where t.running)) over (partition by ta.area_id), 0)) as pct_of_running
from bank.trial_areas ta
join bank.v_ms_trials t using (msf_trial_id)
join bank.research_areas ra on ra.area_id = ta.area_id
group by 1, 2, 3, 4;

-- ---------------------------------------------------------------- 4. reviews against trials
-- where meta-analyses and the hypothesis verdicts agree or disagree, per approach and aim
create or replace view bank.review_vs_verdict as
with rev as (
  select g as approach_group, a as aim,
         count(*) filter (where p.direction = 'benefit') as n_benefit,
         count(*) filter (where p.direction = 'no_benefit') as n_no_benefit,
         count(*) filter (where p.direction = 'mixed') as n_mixed,
         count(*) as n_reviews
  from bank.papers p, unnest(p.approach_groups) g, unnest(p.aims) a
  where p.kind in ('meta_analysis', 'systematic_review', 'umbrella_review') and p.direction is not null
  group by 1, 2),
hyp as (
  select approach_group, max(approach_group_label) as approach_group_label, aim, max(aim_label) as aim_label,
         count(*) filter (where outcome in ('confirmed', 'supported_one')) as n_confirmed,
         count(*) filter (where outcome in ('failed_early', 'disproven')) as n_failed,
         count(*) filter (where outcome in ('testing', 'pending', 'unclear')) as n_open
  from bank.v_hypothesis_stage group by 1, 3)
select h.approach_group, h.approach_group_label, h.aim, h.aim_label, h.n_confirmed, h.n_failed, h.n_open,
       coalesce(r.n_reviews, 0) as n_reviews, coalesce(r.n_benefit, 0) as n_benefit,
       coalesce(r.n_no_benefit, 0) as n_no_benefit, coalesce(r.n_mixed, 0) as n_mixed,
       case when r.n_reviews is null or r.n_reviews = 0 then 'no reviews'
            when h.n_confirmed > 0 and r.n_benefit >= r.n_no_benefit then 'agree: works'
            when h.n_failed > 0 and h.n_confirmed = 0 and r.n_no_benefit >= r.n_benefit then 'agree: does not work'
            when h.n_confirmed = 0 and h.n_failed = 0 and r.n_benefit > r.n_no_benefit then 'reviews ahead of trials'
            when h.n_confirmed > 0 and r.n_no_benefit > r.n_benefit then 'disagree'
            when h.n_failed > 0 and h.n_confirmed = 0 and r.n_benefit > r.n_no_benefit then 'disagree'
            else 'unclear' end as agreement
from hyp h left join rev r using (approach_group, aim)
where coalesce(r.n_reviews, 0) >= 2 or h.n_confirmed > 0 or h.n_failed > 0;

-- ---------------------------------------------------------------- 5. time from trial end to first result
create or replace view bank.time_to_result as
with first_paper as (
  select msf_trial_id, min(pub_year) as first_paper_year
  from bank.trial_publications
  where coalesce(is_trial_report_type, false) or ref_type in ('result', 'derived', 'resultsarticle')
  group by msf_trial_id)
select w.msf_trial_id, coalesce(n.name, w.acronym) as name, w.phase, w.sponsor_class,
       case when w.sponsor_class = 'industry' then 'Industry' else 'Academic and other' end as funder,
       w.end_date, w.results_found, w.found_where, w.months_since_end, f.first_paper_year,
       case when f.first_paper_year >= extract(year from w.end_date)
            then (f.first_paper_year - extract(year from w.end_date)) * 12 end as months_to_first_paper
from bank.results_watch_public w
left join bank.trial_names n using (msf_trial_id)
left join first_paper f using (msf_trial_id);

-- ---------------------------------------------------------------- 6. access
alter table bank.conference_reports enable row level security;
alter table bank.trial_announcements enable row level security;
drop policy if exists public_read on bank.conference_reports;
create policy public_read on bank.conference_reports for select using (true);
drop policy if exists public_read on bank.trial_announcements;
create policy public_read on bank.trial_announcements for select using (true);
grant select on bank.conference_reports, bank.trial_announcements, bank.trial_reported_results, bank.trial_latest_report,
  bank.hypothesis_ledger, bank.area_funding, bank.review_vs_verdict, bank.time_to_result to anon, authenticated;
grant all on bank.conference_reports, bank.trial_announcements to service_role;
