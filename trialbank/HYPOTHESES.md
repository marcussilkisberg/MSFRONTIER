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
  second model agrees. Otherwise it is stored as "unclear" with the reason. The cache is committed to the repository
  (`readouts/`) as the audit trail; each trial is read once unless new papers appear.
- **Genetic leads**: genes with an Open Targets genetic-association score ≥ 0.5 are shown; a lead is "tested" if any
  bank drug acts on it (or on its ligand/receptor partner, from a fixed partner list) in an MS trial.

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
