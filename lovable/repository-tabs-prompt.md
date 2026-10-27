# Lovable prompt: Repository tabs (Trials · Treatments · Results · Measures · Failures)

Run `005_knowledge_layers.sql` in Supabase first (SQL Editor, same as before), then wait for the next weekly run
or start "Trial bank refresh" by hand so the new tables fill. Paste everything below the line as one Lovable message.

---

Turn the "All registered trials" repository at the bottom of the Research Navigator (`/research`) into a tabbed
repository with five tabs: **Trials**, **Treatments**, **Results**, **Measures**, **Failures**. Use the existing
read-only `bankClient` and `schema('bank')` for everything. Keep the selected tab in the URL (`?tab=treatments`).
When a phenotype is selected above, pre-filter the Trials, Results and Failures tabs as the Trials tab already does.

Show this small grey line at the top of every tab: "Machine-assembled from public registries and regulators,
updated weekly. Not reviewed by people; check the linked source before relying on any detail."

**Trials tab** — the existing trial explorer, unchanged. On the trial detail page (`/research/trials/:msf_trial_id`)
add a **Results** section when rows exist:
- From `trial_results` for this trial: group by `outcome_title` (primary outcomes first). For each outcome show a
  small table: arm (`arm_title`), value with unit, `lower_limit`–`upper_limit` or `spread` with `dispersion_type`,
  `n_analysed`; below it the analysis line "p = `analysis_p_value_raw`; `analysis_estimate_type` `analysis_estimate`
  (CI `analysis_ci_lower`–`analysis_ci_upper`)" when present. Collapse secondary outcomes behind "Show all N outcomes".
- From `trial_arm_safety`: a small table per arm with participants at risk, serious adverse events, deaths.
- Label: "Results as posted on ClinicalTrials.gov."

**Treatments tab** (`treatments`)
- Group into sections by `category`: "Disease-modifying treatments (MS)" (disease_modifying), "NMOSD and MOGAD
  treatments" (nmosd_mogad_treatment), "Symptom treatments" (symptom_treatment), "Relapse treatments"
  (relapse_treatment). Hide empty sections.
- Card per treatment: `name` (capitalise), brands (`eu_brands`, else `us_brands`), a tag per `mechanism_families`
  (same labels as elsewhere), `mechanism_of_action`, and two status chips:
  - EU: "Approved in the EU since YYYY" when `eu_status` = authorised (year of `eu_first_authorisation`);
    "Approved nationally (not via EMA)" when `eu_status` = not centrally authorised; otherwise show the status
    ("Refused", "Withdrawn").
  - US: "FDA approved YYYY" from `us_first_approval_ms_product`, else "Not FDA approved".
  - Small counts: trials in the bank (`n_trials`), EMA safety letters (`n_ema_safety_letters`).
- Detail page `/research/treatments/:treatment_id`:
  - Header: name, other names, molecule type, mechanism, targets, `availability_note`.
  - "Approvals": rows from `treatment_products` (region, product, status, generic/biosimilar flags, date, link `url`).
  - "Regulatory history": rows from `regulatory_events` (event, product, date, link).
  - "Safety communications": rows from `treatment_safety_signals` (type, title, date, link).
  - "Most-reported side effects (FDA reports)": bar list from `treatment_adverse_event_reports` (reaction, reports),
    with this note: "Reports to the FDA's adverse event system (FAERS) show what people and doctors reported while
    taking the medicine. They do not prove the medicine caused it, and they are not rates." Show totals
    `faers_reports` and `faers_serious_reports`.
  - "Trials": from `trials_current` where `chembl_ids` contains this `chembl_id`, newest first, linking to trial pages.
  - Note under US dates: "FDA dates refer to the first approval of the product's licence; for alemtuzumab and
    ofatumumab this was an earlier cancer approval."

**Results tab** (`trial_results`)
- Two pickers at the top: "Outcome" (endpoint_tags: relapse, disability_progression, mri_lesions, brain_atrophy,
  walking_mobility, cognition, fatigue, fluid_biomarker, remyelination, safety_tolerability; plain labels) and
  "Drug" (free text, matched against `arm_drugs`).
- Show primary outcomes by default (toggle to include secondary). One row per outcome × arm: trial (acronym or
  title, link), outcome title, arm, value + unit, interval, n, p-value. Group rows of the same outcome together
  with a subtle divider. 50 per page, server-side.
- Note: "Only trials that posted results on ClinicalTrials.gov; about 550 of the MS trials. Values are as reported;
  outcomes measured differently across trials are not directly comparable."

**Measures tab** (`measures`)
- A searchable glossary of cards ordered by `n_trials_measuring`: `name` (`short_name`), `kind` tag, `what_it_is`,
  `how_trials_use_it`, "Used in N trials, primary endpoint in M", and a link "Trials using this measure" that opens
  the Trials tab filtered by `primary_endpoint_tags` contains `endpoint_tag`. Link `further_reading` as "Research
  on this measure (Europe PMC)". Footer: "Definitions written by MSFrontier's automated assistant, not yet reviewed
  by clinicians."
- Make measure names clickable tooltips wherever they appear as tags elsewhere on the site (EDSS, ARR, NfL, PIRA…).

**Failures tab** (`failures`)
- Intro line: "Treatments that were tested and did not work, or were stopped. Negative results are as important as
  positive ones, and are often hard to find."
- Filters: failure type (`failure_type`: primary_endpoint_not_met → "Missed its main goal",
  stopped_for_lack_of_efficacy → "Stopped: not working", stopped_for_safety → "Stopped: safety"), approach
  (`mechanism_families`), phase, population.
- Rows: trial (acronym or title, link), drugs, phase, population, failure badge, `why_stopped` when present, year.
- Below the list, a second small table "Rejected or withdrawn in the EU" from `regulatory_events` where event is
  refused or withdrawn (product, substance, event, date, link).
- Note: "Only failures visible in registries (posted results or stated reasons for stopping). Failures reported only
  in journal papers, such as MS-STAT2 with simvastatin, are not yet included."

**Style:** same calm editorial style; tables collapse to cards on mobile; loading skeletons and friendly empty states.
