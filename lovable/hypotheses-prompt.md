# Lovable brief: Hypotheses page (`/hypotheses`) and its links across the site

Paste **Prompt A**, check the page, then paste **Prompt B**. The look and behaviour follow the prototype
"MSFrontier Hypotheses" (claude.ai artifact). Everything shown comes from the `bank` schema through the existing
read-only `bankClient` (`schema('bank')`). No content is typed into Lovable except the copy below. Use it exactly.

---

## PROMPT A — the `/hypotheses` page

Build a new page at `/hypotheses` and add **Hypotheses** to the main navigation between "Research" and "The
Project". Load all rows of `bank.hypotheses` once (a few hundred) and all rows of `bank.genetic_leads` where
`genetic_score >= 0.5` and `lead_status = 'drugs_exist_not_tested_in_ms'`. Filter in the browser. Same calm
editorial style as the rest of the site: plain text, no icons beyond small colour swatches and dots, no
illustrations.

### The nine statuses

Every hypothesis has one status in the column `outcome` (label in `outcome_label`). Genetic leads always have the
status `roadmap`. Use this order, these colours and these definitions everywhere on the page:

| outcome | Label | Colour (light / dark theme) | Definition |
|---|---|---|---|
| roadmap | Roadmap | violet outline only, no fill (#6d55a6 / #a48ee0) | Proposed or suggested by genetics. Not yet tested in MS. |
| testing | Being tested | blue (#3a74b4 / #5b95d6) | Trials are running now. No verdict yet. |
| pending | Results pending | grey diagonal hatching (#8e9ba4 / #5d6b74) | Trials finished, but not all results are read yet. |
| promising | Promising | light green (#8fc39b / #3f7a52) | Worked in a controlled phase 2 trial. A signal, not proof. |
| confirmed | Confirmed | deep green (#2c7a4d / #4fae78) | Worked in placebo-controlled phase 3, with no phase 3 failures. |
| mixed | Mixed | amber (#d39a2a / #c98f22) | Controlled trials disagree. |
| failed_early | Failed early | light rust (#df9f8b / #8a4c3d) | Controlled phase 2 trials were negative. |
| disproven | Disproven | deep rust (#a5402c / #d4644b) | Failed in placebo-controlled phase 3 for this patient group. |
| unclear | No clear answer | pale grey (#cfd7dc / #33434d) | Tried, but no controlled phase 2 or 3 result yet. |

### 1. Header

Eyebrow: "MSFrontier · Hypotheses". H1: **What has been tried against MS, and what worked**

Standfirst: "Every idea for treating MS that trials have tested, are testing now, or that is proposed for testing.
Each one is an approach, an aim and a group of patients, linked to the trials behind it."

Small grey note: "Machine-assembled from public registries and updated weekly. Not reviewed by people. Check the
linked trials before relying on any status."

### 2. Status strip

A white box titled "Where every hypothesis stands", with "Click a status to filter. Click again to clear." on the
right.

- A thin horizontal bar (14px) split into segments, one per status, each as wide as its count, in the colours above.
- Below it, nine buttons in a grid (three per row on desktop, two on mobile), one per status, in the order above.
  Each shows the swatch, the label, the count on the right in a monospace font, and the definition in small grey
  text (hide the definition on mobile).
- Clicking a button toggles that status as a filter (several can be on at once). The selected state has a dark
  border and a slightly darker fill.
- The counts reflect the patient, aim and search filters, but not the status filter itself.

### 3. Controls (sticky under the site header)

- A segmented switch: **Map · Board · List**. Remember the choice in localStorage.
- A search box: "Search a drug or approach, e.g. statin, BTK, exercise". Matches `approach_label`,
  `approach_group_label` and `drugs`.
- **Patients** pills, single choice: All · Relapsing (`relapsing`, `relapsing_and_progressive`) · Primary
  progressive (`ppms`) · Secondary progressive (`spms`) · Any progressive (`ppms`, `spms`, `progressive`) · Early MS
  (`early_cis_ris`) · NMOSD and MOGAD (`nmosd`, `mogad`) · Other (`unspecified`, `optic_neuritis`).
- **Aim** pills, single choice: All aims · Prevent or delay MS (`prevent`) · Stop inflammation (`stop_inflammation`)
  · Slow progression (`slow_progression`) · Protect nerves (`protect_nerves`) · Repair myelin (`repair`) · Restore
  function (`restore_function`) · Reset the immune system (`reset`).
- A line: "Showing N items", followed by the active status names and a "Clear filters" link when any filter is on.
- Genetic leads have no aim or patient group: include them only when both filters are "All".
- Keep all filters in the URL (`?view=board&pop=ppms&aim=repair&s=confirmed,disproven&q=statin`).

### 4. Map view (default)

A table inside its own horizontally scrolling box (the page itself never scrolls sideways).

- Columns: the seven aims in the order above. The first column, "Approach", stays fixed when scrolling sideways.
- Rows: approach groups (`approach_group`, `approach_group_label`), under grey section rows by `approach_family`:
  immunomodulation "Immune system", progression_biology "Nerve and brain biology", lifestyle_supplement
  "Supplements", symptomatic "Symptom treatments", non_drug "Non-drug approaches", proposed "Proposed, not yet
  tested". Within a section, order rows by total trials.
- Each cell is a rounded button filled with the colour of the best status among the filtered hypotheses in it, in
  this priority: confirmed, promising, mixed, disproven, failed_early, testing, pending, unclear, roadmap. It shows
  the total trials (sum of `n_trials`) in monospace. White text on deep green, blue, amber and deep rust; dark text on
  the others.
- A small dark dot in the top-right corner when any hypothesis in the cell has `n_ongoing > 0`.
- An inset outline in the site accent colour when any has a non-empty `project_study_ids`.
- Empty cells stay blank.
- Hover shows a tooltip listing each hypothesis in the cell: drug or approach, patient group and status.
- Clicking a cell opens the side panel with the hypotheses in that cell as cards (see Board cards).
- Under the table, one line: "Colour: the best result in the cell, across the patient groups selected. Number:
  trials. ● trials running now. Outline: part of the Project. Blank: no registered trial has tried this. That is not
  proof nobody is working on it." When both filters are "All", add: "Plus N roadmap leads from human genetics, not
  yet tied to an aim. See the Board or List view."

### 5. Board view

One column per status that has items, in the status order above. Columns are about 250px wide on a light grey
background; the board scrolls sideways inside its own box and each column scrolls vertically (max height about 78%
of the screen). Each column header shows the swatch, label and count, and stays visible while scrolling the column.
Show 25 cards per column, then "Show 25 more".

Card (white, thin border, whole card clickable), sorted by trials running, then total trials:
- Title: `approach_label` (bold).
- Second line: aim label · `population_label` (grey).
- Meta line: "N trials", "up to phase X" (from `highest_phase`: phase3 → 3, phase2|phase3 → 2/3, etc.), a blue
  outlined tag "N running" when `n_ongoing > 0`, an accent-coloured tag "Study 03" per `project_study_ids`, and a
  violet tag "Genetics: GENE" when `genetic_support_genes` is not empty.

Genetic lead card: title "SYMBOL: linked to MS by genetics, never tested"; second line: gene `name` and "Medicines
that act on it:" with the first three of `approved_drugs_any_disease`, else of `existing_drugs`; a violet tag
"Human genetics · strong/moderate".

### 6. List view

A table in its own scrolling box: Hypothesis (bold `approach_label` + aim, plus Project tags), Patients, Status
(swatch + label), Trials (with "(N running)" in blue), Furthest phase. Sorted by status order, then trials. 60 rows,
then "Show more". Rows are clickable.

### 7. Side panel (detail)

Opens from the right (full width on mobile) over a dim backdrop. Closes with a Close button, the backdrop or Escape.
Also give each hypothesis its own URL `/hypotheses/:id` (URL-encode `hypothesis_id`) that opens the panel.

For a hypothesis:
- Status swatch and label, then the title "`approach_label`: `aim label` in lower case", then `population_label`
  · `approach_group_label` in grey.
- A grey box with one sentence by `outcome`:
  - confirmed: "At least one placebo-controlled phase 3 trial met its main goal, and none failed."
  - disproven: "Placebo-controlled phase 3 trials missed their main goal, and none succeeded. This applies to this
    patient group only."
  - mixed: "Controlled trials disagree."
  - promising: "A controlled phase 2 trial was positive. Phase 2 trials are small and often measure early markers,
    so this is a signal, not proof."
  - failed_early: "Controlled phase 2 trials were negative."
  - testing: "Trials are running now and no controlled trial has a readable result yet."
  - pending: "Trials have finished, but some results have not been read yet. There is no verdict until they are,
    because one unread trial can change the answer."
  - unclear: "Trials have tried this, but none was a controlled phase 2 or 3 trial with a readable result."
  - roadmap: "No registered trial has tested this yet."
  - Add "N trial(s) stopped for safety reasons." when `n_stopped_safety > 0`.
- A warning line with a rust left border when a name in `drugs` matches a `treatments.name` whose `eu_status` is
  withdrawn or refused: "Daclizumab was withdrawn in the EU. A positive trial result does not mean the medicine is
  available." (fill in the name and status).
- Four small fact boxes: trials (`n_trials`), running now (`n_ongoing`), count toward status
  (`n_rct_phase2plus`), people in those trials (`n_participants_rct`).
- **In the Project**: rows from `project_hypotheses` whose `ledger_hypothesis_ids` contains this id: a "Study 03"
  tag and the Project's statement.
- **Human genetics**: "Genes linked to MS that these medicines act on: …" when `genetic_support_genes` is not empty.
- **Trials**: rows from `hypothesis_evidence` for this hypothesis, those that count first, then by phase and start
  year. Each row: trial name (`acronym`, else `title`) linking to `/research/trials/:msf_trial_id`; on the right the
  result in colour (met "Met main goal" green; not_met "Missed main goal" and stopped_no_effect "Stopped: not
  working" rust; stopped_safety "Stopped: safety" rust; ongoing "Ongoing" blue; mixed "Mixed" amber;
  stopped_other "Stopped, other reason", result_in_paper_unread "Result in a paper, not read yet", no_result_found
  "No result found" grey). Under it in small grey: "Phase X · start year · design · trial ID", where design is
  "Placebo-controlled" (has_placebo_or_sham and no comparator_drugs), "Compared with …" (comparator_drugs),
  "Randomised" or "Not randomised" (is_rct false); and a green "✓ counts" when `counts_toward_verdict`. When
  `state_source` is `paper_machine_read`, add the `readout_quote` in italics and "Read by machine from the paper's
  abstract", linking to `https://europepmc.org/article/MED/<readout_pmid>`.
  Footnote: "✓ counts: randomised, phase 2 or 3, and placebo-controlled or shown to beat a drug that works another
  way."
- **History**: rows from `hypothesis_history` where `field` is `created`, `outcome` or `n_trials`, newest first:
  "First listed as Being tested", "Status changed from Results pending to Confirmed" (use the status labels above for
  `old_value` and `new_value`), "Trials: 4 → 5", with dates.

For a genetic lead: Roadmap swatch, title "SYMBOL: linked to MS by genetics, never tested", gene name; grey box
"Human genetics links this gene to the risk of getting MS (Open Targets score 0.81, strong). Medicines that act on it
exist, but none has been tried in an MS trial."; warning line "Two cautions. These genes affect the risk of getting
MS, not necessarily how it progresses. And a genetic link does not say which way a medicine should push: medicines
that block TNF made MS worse."; "Medicines that act on it"; link "See the genetic evidence on Open Targets" (`ot_url`).

### 8. Footer: "How the statuses are decided"

- Only randomised phase 2 and 3 trials decide a status. They must be placebo-controlled, or beat a drug that works
  another way. Failing to beat another active drug does not count against an idea.
- If any finished trial at that phase has not been read yet, the status stays "Results pending". A single unread
  trial can change the answer.
- "Disproven" applies to the patient group shown. An idea can fail in primary progressive MS and work in relapsing
  MS.
- Roadmap items come from two places: hypotheses the Project has registered, and genes linked to MS by human
  genetics that existing medicines act on but that have never been tried in MS.
- Nothing here is linked or edited by hand. To report an error, use the contact form; we fix the rule, so the fix
  applies everywhere. (Link "contact form".)

### Style details

Display headings in the site's serif; body in the site's sans; counts and IDs in a monospace face with tabular
numbers. Swatches 12px with 3px radius. Cards 6px radius, thin borders, no shadows. Must work at 400px wide with no
sideways page scroll, and in dark mode with the dark colours above.

---

## PROMPT B — connect the rest of the site to the ledger

Use the same `bankClient`. No hand-written links anywhere: every connection below is a query.

1. **Trial pages** (`/research/trials/:msf_trial_id`): add a section **Hypotheses this trial tests**, from
   `hypothesis_evidence` where `msf_trial_id` matches, joined to `hypotheses` for `approach_label`, aim and `outcome_label`.
   One line each, linking to `/hypotheses/:id`, with a small tick if `counts_toward_verdict`.
2. **Treatment pages** (`/research/treatments/:treatment_id`): add **Hypotheses involving this medicine**, from
   `hypotheses` where `drugs` contains the treatment's `name`. Show `approach_label`, aim, population and the status swatch with `outcome_label`, at most 10, then
   "See all" linking to `/hypotheses?q=<name>`.
3. **Failures tab**: on each row, a small link "Hypotheses" to `/hypotheses?q=<first drug>`.
4. **The Project page** (`/project`), section "The studies":
   - For each study card (Study 01 = `P-01`, Study 02 = `P-02`, Study 03 = `P-03`, Study 04 = `P-04`), take the
     **status chip and the target date from `project_studies`** (`status`, `target`) instead of the fixed text.
     Status labels: planned "Planned"; in_preparation "In preparation"; seeking_partners "Seeking partners";
     in_progress "In progress"; published "Published"; stopped "Stopped". Colours as already defined, with
     in_progress blue, published green and stopped grey.
   - Add a part **Hypotheses registered** at the bottom of each card, from `project_hypotheses` where `study`
     matches. Show each `statement`, its `status` ("Registered", "Analysis plan published", "In analysis", "Result
     published") and `registered_on`. For `kind = 'therapeutic'`, add "What trials show so far" with one link per ID
     in `ledger_hypothesis_ids` to `/hypotheses/:id`, labelled with that hypothesis's `population_label` and
     `outcome_label` (with its status swatch). For `kind = 'method'`, add the label "About how trials are run".
   - In the "Built on open data" section, add a fifth box to the diagram between "Trial Bank" and "Studies":
     **Hypotheses** — "Every tested, ongoing and proposed idea, with what the evidence says." Link it to
     `/hypotheses`.
5. **Research Navigator** (`/research`): under the phenotype tool, add one line: "See every hypothesis tested in
   this group →", linking to `/hypotheses?pop=<matching population>` (early → early_cis_ris, relapsing → relapsing,
   spms → spms, ppms → ppms, nmosd_mogad → nmosd).
