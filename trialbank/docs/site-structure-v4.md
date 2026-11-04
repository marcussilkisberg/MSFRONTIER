# MSFrontier site structure v4.1 (4 November 2026)

Supersedes site-structure-v3 and the structure parts of v10-1 and v11-1 to v11-3.

## 1. What the site is for

One place that says three things about MS research and lets the reader check each of them against the records:

1. **What is known**: what works, for which type of MS, and what has failed.
2. **What is coming**: what is being tested now and when the results are due.
3. **What is still open**: where nothing works yet, and the questions whose answers would change treatment most.

## 2. Who comes, and what they ask

| Reader | First question | Where the answer is |
|---|---|---|
| Person with MS, family | What works for my type of MS? Is anything coming for progression or repair? | Research landing, then the research area page |
| Clinician | What is the evidence for this treatment in this group? What reports soon? | Research area page, then the trial or hypothesis record |
| Researcher, funder | Where are the gaps? What failed, and what is in the lab pipeline? | Treatment gaps, Lessons from trials, Not yet tested in people |
| Anyone new to MS | How does MS work? | Learn |

## 3. Three layers, each with one job

| Layer | Job | Sections |
|---|---|---|
| Understand | Explain the disease | Learn |
| The account | Say where research stands, in words and pictures, with verdicts set by fixed rules | Research |
| The records | Every trial, hypothesis, medicine, review and lab study, searchable and downloadable | Data |

News says what changed this week. About says who made it and how.

Research tells the story. Data is the library. Every statement in Research links down to the records in Data, and every
record in Data links back up to its place in Research ("Where this fits").

## 4. One spine: the research areas

The site was organised three ways at once: eight research areas, seven or eight map stages and thirty open questions,
with each area page also showing stage tabs. From now on the **research areas are the only spine**.

The areas are **goals of treatment**, in the order of the disease (v4.1, migration 020). Each hypothesis, trial,
review and lab study belongs to an area through its aim:

1. Preventing MS (aim: prevent or delay)
2. Stopping relapses (stop inflammation)
3. Slowing progression (slow progression)
4. Protecting and repairing (protect nerves, repair myelin)
5. Easing symptoms (restore function)

**Towards a cure** (lasting remission) is a goal that runs across the course.

Measuring MS, Related diseases and AI in MS research left Research in v4.1. Measuring MS moved to Learn module 7.

The stages of the disease (Triggers, Immune attack, Entry, Smouldering, Nerve damage, Repair, Daily life) become parts
within an area. They are never a navigation level of their own. The same five rows, in the same order, are used on
the landing page, the map, the timeline and the area pages, and in the sidebar.

Data: `research_areas`, `research_area_aims`, `research_area_summary`, `area_hypotheses`, `trial_areas`, `area_papers`,
`area_lab_studies`, `area_open_questions`, `results_timeline`, `research_numbers`, `research_effort`, `gap_cells`
and `trial_names` (migration 019).

## 5. One vocabulary

| Term | Meaning | Never |
|---|---|---|
| Approach | A kind of treatment that works the same way. B-cell depletion covers ocrelizumab, ofatumumab and ublituximab. | "frontier" |
| Hypothesis | One approach, for one aim, in one type of MS. | "idea" for the same thing |
| Confirmed | Two controlled phase 3 trials met their main goal, or one did and a regulator approved it. | Counting "supported by one trial" as confirmed |
| Trials running | Interventional trials that are recruiting or under way. | |
| Controlled trial | A randomised trial with a control group. | |
| Research area | One of the eight areas above. | "question", "frontier" |
| Open question | One of the thirty questions on the Open questions page. | |

Effect of the "confirmed" change: the number of confirmed hypotheses falls from 32 to about 27, because the eight
"supported by one trial" are now shown separately.

## 6. The flow

Home → Research landing (what research looks at, in numbers) → an area page (the same template for all eight) → a
record in Data → "Where this fits" → back to the area. Area pages end with links to the previous and next area along
the course of the disease, so a reader can go through MS from start to end.

The views that compare all areas (the map, treatment gaps, the timeline) are one click from the Research landing page.

## 7. Section maps

### Home
Hero · dark green band of key figures · What you will find here (four tiles) · closing line.

### Research
- Overview
- Current understanding: The map · Treatment gaps
- Research areas: the five, then Towards a cure
- What comes next: What we will learn and when · Open questions · Trials to watch · Not yet tested in people
- Lessons from trials: Negative and mixed results · Patterns across trials · From animals to people

### Data
- Overview
- The records: Trials · Hypotheses · Medicines · Reviews and guidelines · Lab studies · Organisations
- Across the data: Missing results
- Use the data: Open data · How the data is built

## 8. Page rules

- **Landing pages** (Home, Research, Data, Learn) have a two-column header: text on the left, an illustration on the
  right.
- **Content pages** have a compact header: breadcrumb, H1, one sentence. The view starts directly under it.
- The text width follows the content column. No paragraph sits at half the page width with an empty right half.
- How-to-read notes, legends and method notes go under the view, in a "How to read this" disclosure.
- "Updated" dates go in the source note at the foot of the page.
- A section with no rows is hidden, except "What works", which says so when nothing is confirmed.
