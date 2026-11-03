# Hypothesis ledger (v0) — 27 Oct 2026

Every treatment hypothesis the trial bank shows being tested, plus those the Project registers and leads from human
genetics, with what the evidence says. Built every week by the same workflow as the trial bank, from the same data.
**Nothing is linked by hand.** The only hand-written inputs are `project/studies.yml` and `project/hypotheses.yml`,
and they refer to aims, mechanisms and populations, never to trial IDs.

## How it fits together

```
registries ─► trials ─► drugs (ChEMBL) ─► mechanism groups ─┐
                    └► main outcome ─► aim                   ├─► HYPOTHESES ◄── project/hypotheses.yml
                    └► inclusion criteria ─► population ─────┘        ▲
registry results ─┐                                                   │
paper abstracts ──┴► trial readouts (machine, gated) ─► verdicts ─────┘
Open Targets ─► genetic leads ◄─ drug targets (ChEMBL IDs) ─► "not yet tested" leads
```

A hypothesis is **approach × aim × population**, with a stable ID such as
`H:slow_progression:anti_cd20_b_cell:ppms`. Approaches are the mechanism groups; groups that hold unrelated drugs
(T-cell/cytokine, mitochondrial, remyelination, etc.) are split per drug, e.g.
`H:stop_inflammation:t_cell_costimulation.laquinimod:relapsing`.

| File (data/) | Table (bank.) | What |
|---|---|---|
| hypotheses | hypotheses | One row per hypothesis: statement, status, verdict, counts, drugs, genes, Project links |
| hypothesis_evidence | hypothesis_evidence | One row per hypothesis × trial, with the trial's result and whether it counts |
| — | hypothesis_history | Week-by-week changes in status, verdict and trial count (never replaced) |
| trial_readouts | trial_readouts | Machine-read results from paper abstracts, with the quoted sentence |
| genetic_leads, drug_targets | genetic_leads, drug_targets | MS-linked genes (Open Targets) and which drugs act on them |
| project_studies, project_hypotheses | project_studies, project_hypotheses | The Project, from `project/*.yml` |
| — | view gap_map | Aim × mechanism group summary for the map |

## Rules (rules_version hypotheses_v0)

- **Aim** from the trial's primary outcome: relapses/new lesions → stop inflammation; disability, walking, hand
  function, cognition → slow progression; brain volume, NfL, OCT → protect nerves; remyelination measures, evoked
  potentials → repair; symptom drugs and non-drug therapies → restore function; immune reconstitution, aHSCT and
  CAR-T → reset; early MS (CIS/RIS) trials → prevent. Steroid trials count only for relapses.
- **Attribution**: when a trial's drug list spans several mechanisms, only drugs named in the title count (rescue and
  background drugs, e.g. interferon in ORACLE MS, are dropped).
- **What counts toward a verdict**: randomised phase 2 or 3 trials that are placebo-controlled, or that beat a drug of
  another mechanism. A placebo used as a double-dummy alongside an active comparator is not a placebo control
  (GEMINI 1/2). Failing to beat an active drug, or a dose comparison within one mechanism (GAVOTTE), does not count.
- **Verdict** at the highest phase with controlled evidence: supported / not supported / mixed (phase 3), early
  signal / early negative / mixed early (phase 2). **If any completed controlled trial at that phase has not been
  read, there is no verdict** ("incomplete"). One case shows why: ORATORIO, the positive phase 3 of
  ocrelizumab in PPMS, posts no p-value in the registry; without this rule the machine would have called anti-CD20 in
  PPMS "not supported" on the strength of OLYMPUS alone.
- **Readouts from papers** (`readouts_layer.py`, needs `ANTHROPIC_API_KEY`): the reader names the main results paper
  and quotes one sentence; the readout is kept only if the sentence is found word for word in the abstract and a
  second model agrees. Otherwise it is stored as "unclear" with the reason. Since readout_v2, two more outcomes are
  recorded and neither count toward nor block a verdict: "equivalent" (non-inferiority or biosimilarity shown) and
  "not_efficacy" (primary endpoint was safety, PK, cell counts or vaccine response). v1 (first 150 readings) stripped
  "p < 0.001" from abstracts as if it were HTML, so positive results were wrongly discarded; v2 re-reads them. The cache is committed to the repository
  (`readouts/`) as the audit trail; each trial is read once unless new papers appear.
- **Genetic leads**: genes with an Open Targets genetic-association score ≥ 0.5 are shown; a lead is "tested" if any
  bank drug acts on it (or on its ligand/receptor partner, from a fixed partner list) in an MS trial.

## Rules added after the first full reading (28 Oct 2026)

- A trial enrolling both PPMS and SPMS counts for both groups; there is no separate "progressive (both)" row. The
  title decides when it names the type (O'HAND, EXPAND, ASCEND).
- A result is credited only to the aim its measure belongs to (lipoic acid: brain volume, not relapses). A
  disability result "in the MRI-active subgroup" is a disability result.
- "Phase 2/3" trials with fewer than 100 participants are judged as phase 2.
- Symptom treatments are judged on symptom and function measures only, per drug.
- A published result outranks a registry "terminated" label (SPI2).
- Paper choice: results papers first, oldest first; protocols and reviews excluded.
- (29 Oct) Any "phase 3" with fewer than 100 participants is judged as phase 2 (MOVING, fingolimod vs interferon, 88
  planned and 9 analysed, had made "S1P for repair" confirmed).
- (29 Oct) Add-on trials (both arms on an established medicine, e.g. POINT: ponesimod or placebo on top of dimethyl
  fumarate) count toward "stop inflammation" only when they succeed, as with active comparators. For progression,
  protection and repair they count both ways.
- (29 Oct) The background medicine in an add-on trial ("BIIB061 added to interferon beta", "BIIB033 when used
  concurrently with Avonex") is not attributed as a tested approach.

## First build (no paper readouts yet)

451 hypotheses (292 tested, 158 being tested, 1 proposed); 2,102 hypothesis-trial links.
Verdicts: 23 supported, 3 not supported, 4 early signal, 11 early negative, 2 mixed early, 111 incomplete
(results in papers not yet read), 296 no controlled result yet. About 325 trials qualify for paper reading;
the workflow reads up to 150 a week.

Genetic leads: 405 genes; of the 82 with score ≥ 0.5, 7 are tested in MS trials, 1 via a partner molecule, 13 have
medicines that were never tried in MS, and 61 have no medicines yet.

## Known limits

- Mechanism groups and aims come from regex rules over registry text; misclassified trials carry into hypotheses.
- Extension studies count as separate trials (REFLEXION after REFLEX).
- Registry p-values are taken as posted; a trial reported as "met" in the registry may be described differently in
  its paper.
- Genetic associations are about getting MS, not about progression, and do not say which direction a drug should act.
- Verdicts are machine-assigned and unreviewed. They are a map of the evidence, not medical advice.

## Rules v1 (1 Nov 2026): "Confirmed" needs replication or approval

- A hypothesis whose highest-phase verdict is "supported" is **Confirmed** only when two or more controlled phase 3
  trials that count toward the verdict met their main goal, **or** one did and a medicine of the same approach is
  approved in the EU or the US for that use. The approval is matched by rule from the approved indication text
  (relapsing, secondary progressive, primary progressive, clinically isolated syndrome, NMOSD, MOGAD), and only for the
  aims that approvals cover (prevent, stop inflammation, slow progression, reset, and symptom approvals for walking,
  spasticity and bladder). Sentences under "limitations of use" or saying "not recommended" never count. Comparator
  and background medicines never count as the approach's medicines.
- Otherwise it is **Supported by one trial** (`supported_one`). Effect on the first build: masitinib in primary and
  secondary progressive MS, daclizumab (withdrawn), cladribine in early MS (its US label says it is not recommended for
  CIS), and botulinum toxin type A as a group moved from Confirmed. BTK inhibition in non-relapsing secondary
  progressive MS stays Confirmed because tolebrutinib was authorised in the EU for that use in June 2026.
- Registry analyses that only compare an active comparator arm with placebo no longer count as the tested medicine's
  result (`parse_ctgov.py`). BRAVO posted laquinimod vs placebo (p = 0.0746) and interferon vs placebo (p = 0.0067), and
  the second had made laquinimod's relapse hypothesis Confirmed. It is now Mixed (ALLEGRO met, BRAVO did not).
- Pages show the trials that decide the status (`deciding_phase`, `n_met_deciding`, `n_not_met_deciding`) and count
  every other linked trial separately (`n_other_trials`), so the counts shown always match the status.


## Context that never changes a status (2 Nov 2026)

- Reviews and guidelines (`literature_layer.py`) and lab evidence (`preclinical_layer.py`: animal models of MS and
  human cell studies) are linked to hypotheses by approach group and aim, and shown beside them. Neither is counted
  in any status. Only trials in people set a status.
- Lab studies link to every population of a hypothesis's approach and aim, because animals have no type of MS. A
  hypothesis about one named medicine is linked only to lab studies of that medicine.

## Rules v1.1 (2 Nov 2026): unread extensions no longer hold back a clear result

- At the deciding phase, two or more trials that met their main goal, with none that failed and none mixed, give a
  verdict even when other trials at that phase are still unread. Those unread trials are mostly open-label
  extensions and sub-studies. Before this change, B-cell depletion, S1P modulators, fumarates and immune
  reconstitution in relapsing MS showed as "Being tested" because one extension study had no readable result.
- A single trial that met its goal is still held back by an unread trial at the same phase, because that trial could
  turn the result into "Mixed".

## Intervention roles (3 November 2026)

- A medicine given in the experimental arms and in the control arm too, added to the medicine being tested, is
  **background** therapy and is not credited with the trial's result (Mintaka: RO7268489 added to ocrelizumab
  against placebo added to ocrelizumab; TERACLES: teriflunomide added to interferon beta). If the same medicine is
  also given on its own in an experimental arm (a delayed-start design such as PreCISe), it stays the tested
  medicine. A medicine marked background in one registry record is background in the trial's other records too.
- Contrast agents, tracers and washout medicines given for the study's measurements are **ancillary** and are not
  credited either.
- Outcome labels: "Failed early" is now "Failed in phase 2" and "Disproven" is now "Failed in phase 3". The rule is
  unchanged: all counting trials at that phase for this approach, aim and group of people failed. One failure at
  phase 3 does not rule out the mechanism in other groups or with other medicines.
