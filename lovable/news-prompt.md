# Lovable brief: News page (`/news`)

Before pasting: run `008_news.sql` in Supabase and run the "News refresh" workflow once. Paste everything below the
line as one Lovable message.

---

Build a new page at `/news`, titled **News**, and add **News** to the main navigation after "Hypotheses". All data
comes from the read-only `bankClient` with `schema('bank')`. Same calm editorial style as the rest of the site; no
images. Two tabs at the top, kept in the URL (`?tab=changes` / `?tab=articles`): **What changed** (default) and
**Articles of interest**.

### Tab 1: What changed

Intro line: "Every week the MSFrontier Trial Bank checks the trial registries, regulators and published papers. This
is what changed. Every line comes from an official record and links to it."

Load `weekly_changes`, newest first. Group by `week_start` with a heading "Week of 2 November 2026". Inside each week,
group by `kind` in this order, each with a small heading and a count, and one line per row:

| kind | Heading | Line |
|---|---|---|
| paper_result | Results published | "**name**: results paper read: Met its main goal / Missed its main goal / Mixed result" (from `new_value` met / not_met / mixed), linking to the trial page `/research/trials/:msf_trial_id`, plus a small "Paper" link to `link` |
| results_posted | Results posted in a registry | "**name** posted its results on ClinicalTrials.gov" → trial page |
| hypothesis_status | Hypotheses that changed status | "**name**: `old_value` → `new_value`" using the status labels from the Hypotheses page (confirmed "Confirmed", pending "Results pending", etc.) with the coloured swatches, → `/hypotheses/:hypothesis_id` (URL-encoded) |
| trial_status | Trials that changed status | "**name**: `old_value` → `new_value`" in plain words (recruiting "Recruiting", completed "Completed", terminated "Stopped early", etc.) → trial page |
| new_trial | New trials registered | "**name** (phase `new_value`)" → trial page |
| regulatory | Regulatory decisions | "**name**: `new_value` (`old_value`)", e.g. "Ocrevus: authorised (EU)", → `link` |
| safety_letter | Safety communications | "**name**: `new_value`" → `link` |

Collapse any group with more than 8 lines behind "Show all N". If there are no rows: "Tracking changes since 29
October 2026. The first weekly summary appears after the next Sunday update."

### Tab 2: Articles of interest

Intro line: "Selected news, research and announcements about MS, NMOSD and MOGAD. Each has a short summary and a link
to the original."

Load `news_items` where `is_published` is true, newest `published_at` first, 20 per page with "Show more".

Filters (chips, multi-choice): type, from `source_type`: news "News", research_news "Research news", paper "Papers",
patient_org "Patient organisations", regulator "Regulators". Topic, from `category`: research "Research", treatment
"Treatments", trial_news "Trials", regulatory "Approvals and safety", living_with_ms "Living with MS". Plus a search
box over `title` and `summary`.

Card for each article:
- Top line in small grey: `source` · date (`published_at`, e.g. "28 Oct 2026") · a small badge "Paper" when
  `source_type` = paper (then also `journal`).
- Title: `title`, linking to `link` in a new tab, with a small ↗.
- `summary` in body text.
- Tags along the bottom, all automatic:
  - one per `matched_drug_names` (capitalised), linking to the treatment page when a `treatments` row has that name,
    else to `/hypotheses?q=<name>`;
  - one per `matched_trial_ids`, labelled with the trial's acronym (or "Trial"), linking to its trial page;
  - "Related hypotheses (N)" when `matched_hypothesis_ids` is not empty, linking to `/hypotheses?q=<first drug>`.

Footer note under the list: "Summaries are written by machine from each source's headline and introduction, not
from the full article, and are not reviewed by people. Read the original before relying on it. We link to sources;
we do not endorse them."

### Elsewhere on the site

- **Home page**: a small "Latest" block with the 3 newest published articles (source, date, title linking out) and a
  line "N changes this week →" linking to `/news`, where N is the count of `weekly_changes` rows in the latest week.
- **Trial pages**: a section **In the news** listing published `news_items` where `matched_trial_ids` contains the
  trial's `msf_trial_id` (title linking out, source, date), hidden when empty.
- **Treatment pages** and **hypothesis detail panels**: the same **In the news** list, for `matched_drug_names`
  containing the treatment's name, or `matched_hypothesis_ids` containing the hypothesis ID.
