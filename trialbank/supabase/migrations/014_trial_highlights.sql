-- 014_trial_highlights.sql — trials to watch, chosen by rule every week (scripts/highlights_layer.py). Run after 012.
-- Safe to re-run.
create table if not exists bank.trial_highlights (
  theme                    text not null,     -- progressive | repair | remission
  theme_label              text,
  rank                     int not null,
  msf_trial_id             text not null,
  name                     text,
  phase                    text,
  enrollment               int,
  population_group         text,
  drugs                    text[],
  approach                 text,
  primary_completion_date  date,
  new_for_group            boolean,          -- the approach is not yet confirmed for this group of people
  score                    real,
  why                      text,             -- one sentence built from the facts that selected it
  as_of                    date,
  primary key (theme, msf_trial_id)
);
alter table bank.trial_highlights enable row level security;
drop policy if exists public_read on bank.trial_highlights;
create policy public_read on bank.trial_highlights for select using (true);
grant select on bank.trial_highlights to anon, authenticated;
grant all on bank.trial_highlights to service_role;
