# Trial bank → Supabase: setup

Moves the MSFrontier Trial Bank into the Supabase database your site already uses, and keeps it refreshed every
week by a GitHub Action. About 20 minutes.

## What goes where in the myelin-ops repository

```
myelin-ops/
├── .github/workflows/trialbank.yml        weekly refresh (Sundays 03:23 UTC) + "Run workflow" button
├── supabase/migrations/003_trial_bank.sql the "bank" schema (next to your 001 and 002)
└── trialbank/
    ├── scripts/                           harvest → tag → build → load
    ├── curation/overrides.csv             hand corrections kept in the repo (each with a source)
    ├── requirements.txt
    ├── .gitignore                         keeps raw downloads and built data out of git
    └── data/                              v0.1.0 build, for the first load (not committed)
```

Everything lives in a separate schema, `bank`, so nothing touches the ledger tables from 001/002
(which already include a `public.trials`).

## Steps

**1. Create the tables.** Supabase → SQL Editor → paste and run `supabase/migrations/003_trial_bank.sql`.
It is safe to re-run. Run it after 001 (it uses your `editors` table for who may correct data).

**2. Get the database connection string.** Supabase → **Connect** (top of the dashboard) → **Session pooler** →
copy the URI and replace `[YOUR-PASSWORD]` with your database password (reset it under Database settings if you
don't have it). Use the session pooler, not the direct connection: GitHub's runners can't reach the direct one.
This string has full access to your database. It goes only into GitHub secrets, never into Lovable or the site.

**3. Add it to GitHub.** Repository → Settings → Secrets and variables → Actions → New repository secret:
`SUPABASE_DB_URL` = the string from step 2.

**4. Upload the files** into the repository in the layout above (keep the `.github` folder).

**5. First load.** Either:
- **From GitHub (recommended):** Actions → **Trial bank refresh** → Run workflow. The first run takes about
  45 minutes (the EU register is slow); later runs are faster because drug and publication lookups are cached.
- **From your laptop, using the included build (about a minute):**
  ```bash
  cd trialbank
  pip install -r requirements.txt
  export SUPABASE_DB_URL='postgresql://...'      # from step 2
  python scripts/load_supabase.py data
  ```

**6. Check it worked.** Supabase → SQL Editor:
```sql
select id, n_trials, n_new, n_changed, n_dropped, error from bank.load_runs order by id desc limit 5;
select population_group, count(*) from bank.trials_current group by 1 order by 2 desc;
```
You should see 4,364 trials.

**7. Let the site read it.** Supabase → Data API settings → **Exposed schemas** → add `bank`. Anyone can read
the bank (it is open data); only the loader can write machine data, and only editors can add corrections.
Then in Lovable, read from `bank.trials_current` (never from `bank.trials`, which lacks corrections), e.g.
`supabase.schema('bank').from('trials_current').select('*').eq('population_group', 'progressive')`.

## How it is maintained

| Table | Written by | Notes |
|---|---|---|
| `bank.trials` + child tables | Weekly loader (bot) | Overwritten every run with the latest registry data and tags |
| `bank.corrections` | You and editors | Never touched by the bot. Each row overrides one field of one trial and should carry a `source_url` |
| `bank.trials_current` | Automatic | Trials with corrections applied. Refreshes after every load and every correction. **Read this.** |
| `bank.change_log` | Weekly loader | Every change to status, phase, enrolment, dates, results or scope, per run. Feeds the public changelog and your review queue |
| `bank.edges` | Rebuilt each load | The knowledge graph (see below) |
| `bank.load_runs` | Weekly loader | One row per run, with counts and any error |

Trials that disappear from the registries are never deleted: they are marked `in_scope = false` and logged.

**Correcting a trial** (SQL Editor, or later from the admin):
```sql
insert into bank.corrections (row_key, field, value, source_url, note, created_by)
values ('MSFT-NCT01234567', 'population_group', '"progressive"', 'https://…', 'Inclusion criteria limit to SPMS', 'you@…');
```
`value` is JSON: a string in double quotes, or an array like `'["metformin","thioctic acid"]'`. A correction to a
column that doesn't exist is refused. To undo one, set `active = false`. Corrections that should live in the
repository instead go in `trialbank/curation/overrides.csv`; the loader syncs that file in on every run.

## The knowledge graph

`bank.edges` links trials, drugs, targets, mechanisms, populations, endpoints, sponsors, diseases and
publications (about 39,000 edges in v0.1.0). Relations: `tests`, `compares_against`, `acts_on`, `assigned_to`,
`part_of`, `studied_in`, `measures`, `about`, `sponsored_by`, `reported_in`. Every edge records its `source` and
`review_status`. Edges you add by hand with `origin = 'reviewed'` survive rebuilds; machine edges are regenerated.

Example — where each mechanism has been tested, progressive vs relapsing populations:
```sql
select e2.dst_id as mechanism,
       count(distinct t.msf_trial_id) filter (where t.population_group = 'progressive') as progressive_trials,
       count(distinct t.msf_trial_id) filter (where t.population_group = 'relapsing')   as relapsing_trials
from bank.edges e1
join bank.edges e2 on e2.src_type = 'drug' and e2.src_id = e1.dst_id and e2.relation = 'assigned_to'
join bank.trials_current t on t.msf_trial_id = e1.src_id and t.study_type = 'interventional'
where e1.relation = 'tests'
group by 1 order by progressive_trials desc;
```

## Tested

Before handing over, the migration and loader were run against a local PostgreSQL 16 with stand-ins for
Supabase's roles and `auth.uid()`: the migration applies twice without error; loading twice gives 0 new and
0 changed trials the second time; a simulated status change and a dropped trial appear in `change_log`; an
editor's correction survives reloads; a non-editor's correction is refused; anonymous users can read; the graph
query above runs in about 0.2 s. It has not been run against your actual Supabase project.
