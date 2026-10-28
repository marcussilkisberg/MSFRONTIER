-- 008_news.sql — "What changed" digest and "Articles of interest". Run after 003-007. Safe to re-run.

-- ------------------------------------------------------------------ settings
create table if not exists bank.settings (
  key    text primary key,
  value  text not null
);
-- the digest starts after the build-up of the bank, so set-up runs are not reported as news
insert into bank.settings (key, value) values ('digest_start', '2026-10-29') on conflict (key) do nothing;
alter table bank.settings enable row level security;
drop policy if exists public_read on bank.settings;
create policy public_read on bank.settings for select using (true);
grant select on bank.settings to anon, authenticated;
grant all on bank.settings to service_role;

-- ------------------------------------------------------------------ articles of interest
create table if not exists bank.news_items (
  id                      text primary key,       -- sha1 of the link
  source                  text not null,          -- e.g. "MS News Today", "EMA", "Europe PMC"
  source_type             text not null,          -- news | patient_org | regulator | research_news | paper
  title                   text not null,
  link                    text not null,
  published_at            timestamptz,
  description             text,                   -- the source's own teaser text (from its feed / abstract start)
  summary                 text,                   -- our summary, written by machine from the title and teaser only
  summary_model           text,
  category                text,                   -- research | treatment | regulatory | trial_news | living_with_ms | other
  relevance               int,                    -- 1-5, machine-rated
  is_published            boolean not null default false,
  journal                 text,
  pmid                    text,
  doi                     text,
  pub_types               text[],
  matched_drug_names      text[],
  matched_chembl_ids      text[],
  matched_trial_ids       text[],
  matched_hypothesis_ids  text[],
  collected_at            timestamptz not null default now()
);
create index if not exists news_items_pub_idx on bank.news_items (is_published, published_at desc);
alter table bank.news_items enable row level security;
drop policy if exists public_read on bank.news_items;
create policy public_read on bank.news_items for select using (true);
grant select on bank.news_items to anon, authenticated;
grant all on bank.news_items to service_role;

-- Links each article to the bank by rule: medicine names, trial acronyms and registry numbers that appear in its
-- title, teaser or summary. Nothing is linked by hand.
create or replace function bank.link_news() returns int language plpgsql as $$
declare n int;
begin
  with txt as (
    select id, lower(coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(summary,'')) as t,
           coalesce(title,'') || ' ' || coalesce(description,'') || ' ' || coalesce(summary,'') as o
    from bank.news_items
  ), names as (
    select distinct lower(drug_name) as name, chembl_id from bank.drugs
    where drug_name is not null and length(drug_name) >= 6
      and lower(drug_name) not in ('calcium', 'sodium', 'potassium', 'magnesium', 'oxygen', 'saline', 'placebo',
                                   'glucose', 'water', 'vitamin', 'protein', 'caffeine', 'nicotine', 'alcohol')
    union
    select distinct lower(name), chembl_id from bank.treatments where name is not null and length(name) >= 6
    union
    select distinct lower(b), t.chembl_id from bank.treatments t, unnest(t.eu_brands || t.us_brands) b
    where b is not null and length(b) >= 6
  ), drug_hits as (
    select x.id, array_agg(distinct n.name) as names, array_agg(distinct n.chembl_id) filter (where n.chembl_id is not null) as ids
    from txt x join names n on x.t ~ ('\m' || regexp_replace(n.name, '([.*+?^${}()|\[\]\\])', '\\\1', 'g') || '\M')
    group by x.id
  ), trial_hits as (
    select x.id, array_agg(distinct t.msf_trial_id) as trials
    from txt x join bank.trials_current t
      -- trial acronyms only in capitals, and only when they cannot be ordinary words: they contain a digit or
      -- hyphen (MS-STAT2), or sit next to "trial"/"study" ("the ORATORIO trial"). Avoids TODAY, START, BRAIN...
      on (upper(t.acronym) ~ '^[A-Z][A-Z0-9-]{3,}$'
          and x.o ~ ('\m' || regexp_replace(upper(t.acronym), '([.*+?^${}()|\[\]\\-])', '\\\1', 'g') || '\M')
          and (t.acronym ~ '[0-9-]'
               or x.o ~* (regexp_replace(t.acronym, '-', '\-', 'g') || '\M.{0,12}\m(trial|study)')
               or x.o ~* ('\m(trial|study)\M[ (]{1,3}' || regexp_replace(t.acronym, '-', '\-', 'g') || '\M')))
      or exists (select 1 from unnest(t.registry_ids) r where length(r) >= 8 and x.t like '%' || lower(r) || '%')
    where t.in_scope
    group by x.id
  )
  update bank.news_items ni
     set matched_drug_names = d.names,
         matched_chembl_ids = d.ids,
         matched_trial_ids  = th.trials,
         matched_hypothesis_ids = (select array_agg(distinct h.hypothesis_id) from bank.hypotheses h
                                   where h.drugs && coalesce(d.names, '{}'))
    from (select id from bank.news_items) all_ids
    left join drug_hits d on d.id = all_ids.id
    left join trial_hits th on th.id = all_ids.id
   where ni.id = all_ids.id;
  get diagnostics n = row_count;
  return n;
end $$;
grant execute on function bank.link_news() to service_role;

-- ------------------------------------------------------------------ what changed, week by week
-- One row per change since the digest start. Built from the bank's own records; no news source involved.
drop view if exists bank.weekly_changes;
create view bank.weekly_changes with (security_invoker = true) as
with s as (select value::date as start from bank.settings where key = 'digest_start'),
runs as (select r.id, r.finished_at, r.n_new from bank.load_runs r, s
         where r.error is null and r.finished_at >= s.start),
changes as (
  -- trial status changes (e.g. recruiting -> completed)
  select c.changed_at, 'trial_status'::text as kind, c.msf_trial_id, null::text as hypothesis_id,
         null::text as treatment_id, coalesce(t.acronym, t.title) as name,
         c.old_value #>> '{}' as old_value, c.new_value #>> '{}' as new_value, t.url as link
  from bank.change_log c join runs on runs.id = c.run_id
  join bank.trials_current t on t.msf_trial_id = c.msf_trial_id
  where c.field = 'status'
  union all
  -- results posted in a registry
  select c.changed_at, 'results_posted', c.msf_trial_id, null, null, coalesce(t.acronym, t.title),
         null, null, t.url
  from bank.change_log c join runs on runs.id = c.run_id
  join bank.trials_current t on t.msf_trial_id = c.msf_trial_id
  where c.field = 'has_posted_results' and c.new_value #>> '{}' = 'true'
  union all
  -- newly registered trials (not the set-up loads)
  select runs.finished_at, 'new_trial', t.msf_trial_id, null, null, coalesce(t.acronym, t.title),
         null, array_to_string(t.phase, '/'), t.url
  from bank.trials_current t join runs on runs.id = t.first_seen_run
  where t.in_scope and runs.n_new < 300
  union all
  -- a hypothesis changed status (e.g. Results pending -> Disproven)
  select hh.changed_at, 'hypothesis_status', null, hh.hypothesis_id, null, h.statement,
         hh.old_value, hh.new_value, null
  from bank.hypothesis_history hh, s
  join bank.hypotheses h on true
  where h.hypothesis_id = hh.hypothesis_id and hh.field = 'outcome' and hh.changed_at >= s.start
    and hh.old_value is not null
  union all
  -- a result read from a published paper
  select r.read_on::timestamptz, 'paper_result', r.msf_trial_id, null, null, coalesce(t.acronym, t.title),
         null, r.readout, 'https://europepmc.org/article/MED/' || r.pmid
  from bank.trial_readouts r, s
  join bank.trials_current t on true
  where t.msf_trial_id = r.msf_trial_id and r.read_on >= s.start
    and r.readout in ('met', 'not_met', 'mixed') and r.reason is null
  union all
  -- EU and US regulatory decisions
  select e.date::timestamptz, 'regulatory', null, null, e.treatment_id, coalesce(e.product_name, e.substance),
         e.region, e.event, e.url
  from bank.regulatory_events e, s where e.date >= s.start
  union all
  select ss.date::timestamptz, 'safety_letter', null, null, ss.treatment_id, ss.substance,
         ss.type, ss.title, ss.url
  from bank.treatment_safety_signals ss, s where ss.date >= s.start
)
select date_trunc('week', changed_at)::date as week_start, * from changes;

grant select on bank.weekly_changes to anon, authenticated;
