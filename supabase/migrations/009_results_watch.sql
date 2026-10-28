-- 009_results_watch.sql — finished trials whose results we cannot find. Run after 003-008. Safe to re-run.

create table if not exists bank.results_watch (
  msf_trial_id      text primary key references bank.trials(msf_trial_id) on delete cascade,
  acronym           text,
  title             text,
  phase             text,
  status            text,
  lead_sponsor      text,
  sponsor_class     text,
  enrollment        int,
  registry_ids      text,
  end_date          date,
  months_since_end  int,
  results_found     boolean,
  found_where       text,     -- registry | eu_register | paper_citing_registry_number | unlinked_paper | reported_by_reader
  found_link        text,
  fully_checked     boolean,
  checked_sources   text,     -- where we looked, in words
  watch_status      text,     -- results_found | no_results_found | not_fully_checked
  as_of             date
);
create index if not exists results_watch_status_idx on bank.results_watch (watch_status);
alter table bank.results_watch enable row level security;
drop policy if exists public_read on bank.results_watch;
create policy public_read on bank.results_watch for select using (true);
grant select on bank.results_watch to anon, authenticated;
grant all on bank.results_watch to service_role;

-- Per sponsor: finished trials, and how many have no results we can find.
drop view if exists bank.results_watch_sponsors;
create view bank.results_watch_sponsors with (security_invoker = true) as
select lead_sponsor,
       min(sponsor_class)                                            as sponsor_class,
       count(*)                                                      as finished_trials,
       count(*) filter (where watch_status = 'no_results_found')     as no_results_found,
       round(100.0 * count(*) filter (where watch_status = 'no_results_found') / count(*))::int as pct_missing,
       max(months_since_end) filter (where watch_status = 'no_results_found') as longest_wait_months
from bank.results_watch
where lead_sponsor is not null
group by lead_sponsor;
grant select on bank.results_watch_sponsors to anon, authenticated;

-- Partial results: a news item or press release about THIS trial (matched by its registry number or its name written
-- as a trial name; see bank.link_news). Shown alongside, never counted as full results.
drop view if exists bank.results_watch_public;
create view bank.results_watch_public with (security_invoker = true) as
select w.*,
       case when w.watch_status = 'no_results_found' and n.items is not null then 'partial_results_in_news'
            else w.watch_status end                                         as public_status,
       n.items                                                              as news_mentions
from bank.results_watch w
left join lateral (
  select jsonb_agg(jsonb_build_object('title', ni.title, 'link', ni.link, 'source', ni.source,
                                      'date', ni.published_at::date, 'summary', ni.summary)
                   order by ni.published_at desc) as items
  from bank.news_items ni
  where to_regclass('bank.news_items') is not null and w.msf_trial_id = any(ni.matched_trial_ids)
) n on true;
grant select on bank.results_watch_public to anon, authenticated;
