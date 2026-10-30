-- 010_inbox.sql — messages sent through the site's forms. Run after 003-009. Safe to re-run.
--
-- The site never writes here directly. Forms post to the Edge Function "contact", which checks the spam test,
-- stores the message with the service role key and emails it to Marcus. Nobody can read this table through the
-- public API: there is no policy for anon or authenticated, so only the service role (the Edge Function, the weekly
-- report and the Supabase dashboard) can see it.

create table if not exists bank.inbox (
  id           bigint generated always as identity primary key,
  received_at  timestamptz not null default now(),
  kind         text not null check (kind in ('contact', 'results_known', 'claim_suggestion', 'correction', 'other')),
  name         text check (length(name) <= 200),
  email        text check (length(email) <= 320),
  subject      text check (length(subject) <= 300),
  message      text not null check (length(message) between 1 and 10000),
  page         text check (length(page) <= 500),
  trial_id     text check (length(trial_id) <= 100),
  status       text not null default 'new' check (status in ('new', 'replied', 'done', 'spam')),
  note         text
);
create index if not exists inbox_status_idx on bank.inbox (status, received_at desc);

alter table bank.inbox enable row level security;
revoke all on bank.inbox from anon, authenticated;
grant all on bank.inbox to service_role;
