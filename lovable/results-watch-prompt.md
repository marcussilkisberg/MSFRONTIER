# Lovable brief: Results watch (`/results-watch`)

Before pasting: run `009_results_watch.sql` in Supabase and finish one "Trial bank refresh" run. Paste everything
below the line as one Lovable message.

---

Build a new page at `/results-watch`, titled **Results watch**, linked from the Research page and from the footer
(not the main navigation). All data comes from the read-only `bankClient` with `schema('bank')`. Same calm editorial
style. Factual tone throughout: we report what we could not find; we do not accuse anyone.

### Header

H1: **Results watch**

Standfirst: "When a clinical trial ends, its results should become public, whatever they show. This page lists
finished MS trials whose results we could not find, a year or more after they ended."

Three short paragraphs:
- "People with MS took part in these trials. When results stay unpublished, especially disappointing ones, other
  researchers may repeat the same experiment and patients lose the knowledge their participation produced."
- "Rules in the United States and the European Union expect results to be posted within 12 months of the end of most
  phase 2 to 4 drug trials. Not every trial listed here was legally required to report, and some may have good
  reasons for delay. We list them so the gap is visible."
- "We may have missed results. If you know where a trial's results are published, tell us and we will correct this
  page within a week."

### Headline figures

Read from the view `results_watch_public` (one row per finished phase 2 to 4 trial that ended between 2008 and a year
ago). Four figure cards:
1. Finished trials checked: count of all rows.
2. Results found: rows where `public_status` = results_found, with the percentage.
3. No full results found: rows where `public_status` is no_results_found or partial_results_in_news, with the
   percentage. Under it in small text: "of which N with partial results in the news" (partial_results_in_news).
4. Waiting more than 3 years: those rows with `months_since_end` ≥ 36.

Small note: "Updated weekly. Trials still being checked are not counted."

### The list

Table of rows where `public_status` is no_results_found or partial_results_in_news, sorted by `months_since_end`
descending, 25 per page. Each row has a status label: "No results found" (grey) or "Partial results in the news"
(amber).
Columns: Trial (`acronym`, else `title`, linking to `/research/trials/:msf_trial_id`), Sponsor (`lead_sponsor`, with
"Company" or "Academic / public" from `sponsor_class`: industry = Company), Phase (plain, e.g. "Phase 3"),
Participants (`enrollment`), Ended (`end_date` as month and year), Waiting (`months_since_end` as "2 years 5 months").
Rows expand to show: "Where we looked: `checked_sources`."; for partial_results_in_news, the list from
`news_mentions` (JSON: source, date, title linking to `link`, and `summary`) under the heading "Reported in the news
(not a full results report)"; and links to each registry record in `registry_ids`
(same link rules as the trial page), plus a button **"I know where the results are"** that opens the contact form
pre-filled with the trial ID and name.

Filters above the table: status (No results found / Partial results in the news), phase (Phase 2 / Phase 3 / Phase 4), sponsor type (Company / Academic or public), and
"Waiting more than": 1 year / 2 years / 5 years. Search box over trial name and sponsor.

### By sponsor

A second table from `results_watch_sponsors` where `finished_trials` ≥ 3, sorted by `no_results_found` descending,
then `finished_trials`. Columns: Sponsor, Type, Finished trials, No results found, Share (`pct_missing`%). Collapsed
behind "Show sponsors" by default. Note: "Sponsor names are as registered; one company can appear under more than
one name."

### How we check (collapsed section)

"Before a trial is listed, we look in four places:
1. results posted in a trial registry (ClinicalTrials.gov, or the EU's CTIS portal);
2. the EU Clinical Trials Register's results pages, checked trial by trial;
3. papers that cite the trial's registry number, and results papers we have already read;
4. papers that do not cite the number: we search by medicine, condition and design for papers published after the
   trial started, and a machine checks whether each one reports this trial, quoting the sentence that shows it.

Press releases and news reports of conference presentations are shown as "Partial results in the news" with a
link, but do not count as full results: they rarely include the full data, the side effects or the methods. We
collect news from 28 October 2026 onwards; older coverage is added when readers tell us about it. Machine
checks can be wrong in both directions; tell us if you spot an error."

### Elsewhere

- On trial pages, when the trial has a `results_watch_public` row with `public_status` = no_results_found, show the
  amber note in "What it found" from this table instead of the earlier calculation: "This trial ended N years ago.
  We could not find its results in registries or papers. [How we check](/results-watch)". For
  partial_results_in_news: "This trial ended N years ago. Its full results are not public; partial results were
  reported in the news:" followed by the `news_mentions` links. When `found_where` =
  unlinked_paper, add under "Papers": "Results paper found by search (it does not cite the registry number)" with
  `found_link`.
