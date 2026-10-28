# Lovable brief: richer trial page (`/research/trials/:msf_trial_id`)

Before pasting: run `007_trial_page.sql` in Supabase and finish one "Trial bank refresh" run, so `trial_texts` and
`trial_findings` have rows. Paste everything below the line as one Lovable message. If the page already has some of
these sections (Results, Hypotheses), replace them with this version.

---

Rebuild the trial detail page `/research/trials/:msf_trial_id` with the sections below, in this order. All data
comes from the read-only `bankClient` with `schema('bank')`. Keep the site's calm editorial style. On desktop use
a two-column layout: the main column holds sections 2 to 9; a narrower right column holds "At a glance" (1) and
stays visible while scrolling. On mobile, one column with "At a glance" after the header. Hide any section with no
data. Show a small grey line at the bottom of the page: "Assembled by machine from public registries and papers,
updated weekly. Check the registry record before relying on any detail." with a "Report an error" link to the
contact form, pre-filled with the trial ID.

### Header

- Title: `title` from `trials_current`, with `acronym` above it in small caps when present.
- A row of chips: status (plain words: recruiting "Recruiting", not_yet_recruiting "Not yet recruiting",
  active_not_recruiting "Running, not recruiting", completed "Completed", terminated "Stopped early", withdrawn
  "Withdrawn", suspended "Paused", unknown "Status unknown"), phase ("Phase 3"), population (`population_group`
  in words), and one chip per registry ID in `registry_ids`, each linking to the registry:
  - NCT… → `https://clinicaltrials.gov/study/<id>`
  - 2023-…-00 style (four groups) → `https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT=<id>`
  - 2006-…-31 style (three groups) → `https://www.clinicaltrialsregister.eu/ctr-search/search?query=eudract_number:<id>`
  - ISRCTN… → `https://www.isrctn.com/<id>`

### 1. At a glance (right column)

A compact list of label/value pairs:
- Participants: `enrollment` + "(actual)" or "(planned)" from `enrollment_type`.
- Design: build from `allocation` ("Randomised"), `masking` ("Double-blind", "Open-label", etc.),
  `has_placebo_or_sham` ("Placebo-controlled"), and `comparator_drugs` ("Compared with …").
- Dates: `start_date` → `primary_completion_date` → `completion_date`, as "Mar 2019 → Jun 2022".
- Sponsor: `lead_sponsor`, with "Company" or "Academic / public" from `sponsor_class` (industry = Company).
- Countries: `n_countries`, then the list of `countries` (first 8, then "+N more").
- Ages: from `min_age_years` and `max_age_years` ("18 to 65", "18 and over").
- Approach: one chip per `mechanism_families` / `mechanism_nodes`, using the same labels as elsewhere.

### 2. What it found

One box, driven by `trial_findings` for this trial. A large label and a sentence by `finding`:

| finding | Label | Sentence |
|---|---|---|
| met | Met its main goal | The main measure showed a statistically significant benefit. |
| not_met | Missed its main goal | The main measure did not show a significant benefit. |
| mixed | Mixed result | The main measures gave different results. |
| equivalent | Shown as good as the comparator | The trial was designed to show the treatment was not worse than another, and it did. |
| not_efficacy | Main goal was not benefit | The main measure was safety, drug levels or similar, not whether the treatment works. |
| stopped_no_effect | Stopped: not working | The trial was stopped early because the treatment was not working. |
| stopped_safety | Stopped: safety | The trial was stopped early for safety reasons. |
| stopped_other | Stopped early | The trial ended early for another reason (see below). |
| ongoing | Still running | No result yet. |
| results_posted_no_test | Results posted, no main test reported | Results are posted in the registry, but without a statistical test of the main measure. See the numbers below. |
| result_in_paper_unread | Result in a paper, not read yet | A paper reports the results; we have not read it yet. See Papers below. |
| no_result_found | No result found | We found no results in the registry or in papers. |

Colours: met green, not_met / stopped_no_effect / stopped_safety rust, mixed amber, ongoing blue, others grey.

Under the sentence:
- When `finding_source` is `registry_analysis`, a small table from `primary_analyses` (JSON array): measure
  (`outcome`), estimate (`estimate_type` `estimate`), 95% CI (`ci_lower`–`ci_upper`), p (`p`). Note: "Statistical
  analysis as posted on ClinicalTrials.gov."
- When `finding_source` is `paper_machine_read`, the `paper_quote` in italics in quotation marks, then "Read by
  machine from the results paper's abstract (PMID `paper_pmid`)", linking to
  `https://europepmc.org/article/MED/<paper_pmid>`.
- When `paper_result` (JSON) is present, show the main numbers under the quote, as a small table: the measure
  (`measure`) and time point (`follow_up`); one row per entry in `groups` (group name, n, value); then the effect
  (`effect.type` `effect.value`, 95% CI `effect.ci_lower`–`effect.ci_upper`) and p (`p`); and total participants
  (`n_randomised`). Leave out anything missing. Note: "Numbers copied by machine from the paper's abstract; each
  number was checked to appear in the abstract."
- When `why_stopped` is present on the trial, show it: "Reason given: …".
- When `months_since_end_without_results` ≥ 12, an amber note: "This trial finished N years ago (or N months
  when under 24). We found no results in the registry or in any paper that cites it." Round N down.

### 3. What was tested

From `trial_interventions` for this trial, grouped by `role`:
- "Treatment tested" (experimental): `drug_name` if present (capitalised), else `name_raw`; then the
  `mechanism_of_action` in grey; when the drug matches a `treatments.name`, link it to `/research/treatments/:id`.
- "Compared with" (active_comparator): same format.
- "Placebo or sham" (placebo_or_sham): one line, "Placebo" or the name.
Remove duplicates by drug name.

### 4. Results by group

From `trial_results` for this trial (only trials that posted results on ClinicalTrials.gov):
- Primary outcomes first. For each outcome: its title and time frame, then one row per arm: arm title, value with
  unit, the interval (`lower_limit`–`upper_limit`, or ± `spread` with `dispersion_type`), and number analysed.
- When an outcome has two to four arms with numeric values and the same unit, also draw a small horizontal chart:
  one bar per arm from zero to the value, with a thin line for the interval when present, the placebo arm
  (`arm_is_placebo`) in grey and others in the accent colour. Label each bar with its value. Keep it simple and to
  scale.
- Under it, the analysis line when present: "p = …; estimate type and value (95% CI …)".
- Secondary outcomes collapsed behind "Show all N outcomes".
- Note: "Values as posted on ClinicalTrials.gov. Outcomes measured differently across trials are not directly
  comparable."

### 5. Safety

From `trial_arm_safety`: one row per arm with participants at risk, serious adverse events (count and % of at
risk), deaths. Draw the serious-adverse-event % as a small bar per arm, placebo in grey. Note: "As posted on
ClinicalTrials.gov. Serious adverse events include any serious health event during the trial, whether or not the
treatment caused it."

### 6. What it measured

From `trial_outcomes`: "Main measures" (outcome_kind primary): `measure` and `time_frame`, with the measure tags
(`endpoint_tags`) as small chips that show the Measures glossary definition on hover. "Other measures" collapsed.

### 7. Who could take part

From `trial_texts.eligibility_text`. First a one-line summary from the trial row: population in words and the age
range. Then the criteria text, shown with line breaks kept, collapsed after about 12 lines behind "Show all
criteria". Note: "As registered. Criteria can change; ask the trial team or your neurologist." When the trial is
recruiting or not yet recruiting, add a link "Contact details on the registry" to the first registry link.

### 8. About this trial

From `trial_texts.brief_summary`, under the subheading "In the sponsor's words", collapsed after about 6 lines.

### 9. Papers

From `trial_publications` for this trial, without duplicate PMIDs. Two groups:
- "Results papers": rows where `is_trial_report_type` is true or `ref_type` is result, resultsarticle or derived.
- "Other papers that mention this trial": the rest, collapsed after 5.
Each row: title (linking to `https://pubmed.ncbi.nlm.nih.gov/<pmid>/` when there is a PMID, else
`https://doi.org/<doi>`), journal and year in grey. Sort by year, newest first.

### 10. Hypotheses this trial tests

From `hypothesis_evidence` where `msf_trial_id` matches, joined to `hypotheses`: one line per hypothesis with the
status swatch and `outcome_label`, linking to `/hypotheses/:id` (URL-encoded); a small "✓ counts" when
`counts_toward_verdict`.

### 10b. Development path

Shows where this trial sits among all trials of the same medicine, e.g. a phase 2 trial and the phase 3 trials
that followed it.
- For each value in the trial's `chembl_ids`, load `drug_programmes` rows with that `chembl_id`. Show the row for
  this trial's `population_group` first, then the other patient groups under "Same medicine in other patient
  groups" (collapsed).
- Draw each row as a horizontal timeline: one dot per trial in `trials` (JSON array, already ordered by phase then
  start year), placed in columns Phase 1 · Phase 2 · Phase 3 · Phase 4 (from `phase_rank`; 0 = "Other"). Each dot
  shows the acronym (or a short title), start year and a small coloured mark for `finding` (same colours as section
  2). Highlight the current trial. Each dot links to that trial's page.
- Heading text: "`drug_name` in `population label`: N trials since `first_year`".
- Also add this path to treatment pages (`/research/treatments/:id`), using the treatment's `chembl_id`, one
  timeline per patient group.

### 10c. Linked trials

From `trial_links` where this trial is `msf_trial_id` or `related_trial_id`. Phrase by `relation` and direction:
extension_of → "Extension of [parent]" / "Extended by [child]"; substudy_of → "Sub-study of" / "Has sub-study";
refers_to → "Refers to" / "Referred to by". Each links to the other trial's page with its phase and status. Note:
"Links found where a registry record names another trial's registry number."

### 11. Related trials

Up to 6 trials from `trials_current` with an overlapping `mechanism_nodes` value and the same `population_group`,
excluding this one, newest first. Show acronym or title, phase, status and the finding label from
`trial_findings`, linking to their pages.

### 12. History

From `change_log` where `msf_trial_id` matches, newest first: date (`changed_at`) and a sentence such as "Status
changed from Recruiting to Completed" or "Results posted". Then the fixed dates as a short timeline: started,
main results due (`primary_completion_date`), finished, results posted (`results_first_posted`). If there is
nothing, hide the section.
