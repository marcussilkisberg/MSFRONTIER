# MSFrontier Trial Bank — v0.1.0 (draft, not yet released)

Every registered clinical trial in multiple sclerosis, NMOSD and MOGAD found in ClinicalTrials.gov, the EU Clinical
Trials Register (EudraCT) and ISRCTN, merged across registries and tagged for population, design, intervention,
mechanism, endpoint and result status. Other CNS demyelinating conditions (optic neuritis, ADEM, transverse myelitis)
are included as tier 2.

**Status: machine-tagged draft.** Every tag in this release was assigned by code (rules, controlled vocabularies and
ChEMBL lookups), not by people. No row has been human-reviewed. Tag accuracy is estimated from a hand-checked sample
(see "Known accuracy" below). Do not use this release for clinical decisions.

## Contents of v0.1.0 (built 2026-10-26)

| | Count |
|---|---|
| Registry records parsed | 5,690 (ClinicalTrials.gov 4,517 · EU CTR 689 · ISRCTN 484) |
| Unique trials after cross-registry merge | 5,399 (267 trials found in two or more registries) |
| In scope | **4,364** — tier 1 (MS, NMOSD, MOGAD) 4,298 · tier 2 (other CNS demyelinating) 66 |
| Interventional / observational | 3,166 / 1,192 |
| Distinct drugs normalised to ChEMBL | 336 (77% of drug intervention entries matched) |
| Registry-linked publications + Europe PMC matches | see `trial_publications*` |

## Files

| File | One row per | What it holds |
|---|---|---|
| `trials` | trial | The main table: identifiers, scope, population, design, status, interventions, mechanisms, endpoints, result signal |
| `trial_registry_ids` | identifier | Every NCT, EudraCT and ISRCTN number linked to a trial (how duplicates were merged) |
| `trial_interventions` | intervention arm entry | Raw intervention names, ChEMBL match, mechanism of action, targets, ATC class, mechanism nodes |
| `trial_outcomes` | registered outcome | Primary and secondary outcome measures with endpoint tags |
| `trial_primary_analyses_ctgov` | statistical analysis | Primary-outcome analyses posted on ClinicalTrials.gov (p-value, estimate, CI) |
| `trial_publications` | registry-linked paper | PMIDs that registries link to the trial |
| `trial_publications_europepmc` | paper | Papers in Europe PMC that cite one of the trial's registry IDs |
| `drugs` | molecule | Every ChEMBL molecule tested, with mechanism, targets and counts of trials, phase 3s, nulls and terminations |
| `mechanism_nodes` | node | The draft MS mechanism map (v0) and the rules that assign drugs to it |
| `unmatched_intervention_names` | name | Drug names that did not resolve to ChEMBL (curation queue) |
| `build_stats.json` | — | Counts and build metadata |

Each table ships as CSV and Parquet. Multi-value fields are pipe-separated (`a|b|c`).

## Key fields in `trials`

| Field | Meaning |
|---|---|
| `msf_trial_id` | Stable ID: `MSFT-` + the trial's primary registry ID (ClinicalTrials.gov preferred, then EudraCT, then ISRCTN) |
| `registry_ids`, `registries` | All registry records merged into this trial |
| `tier` | 1 = MS, NMOSD, MOGAD. 2 = other CNS demyelinating (optic neuritis, ADEM, transverse myelitis) |
| `diseases` | `ms`, `nmosd`, `mogad`, `optic_neuritis`, `adem`, `transverse_myelitis` |
| `ms_focus` | `primary`, or `mixed` when the condition list names another disease (e.g. MS + stroke rehab studies) |
| `phenotypes` | `cis`, `ris`, `rrms`, `relapsing_ms`, `spms`, `ppms`, `progressive_ms`, `paediatric` — from conditions, titles and the *inclusion* criteria only |
| `population_group` | One filterable label: `relapsing`, `progressive`, `relapsing_and_progressive`, `early_cis_ris`, `unspecified`, `not_ms` |
| `phase`, `status`, `allocation`, `masking` | From the registry. `status_inferred = true` means status was inferred from dates (ISRCTN has no status field) |
| `drugs`, `chembl_ids` | Normalised molecules (comparators and placebo excluded) |
| `mechanism_families` | `immunomodulation`, `progression_biology`, `symptomatic`, `lifestyle_supplement` |
| `mechanism_nodes` | Nodes on the draft MS mechanism map (see `mechanism_nodes`) |
| `nondrug_categories` | For non-drug trials: `exercise_rehabilitation`, `neuromodulation_device`, `cognitive_psychological`, `diet_nutrition`, `digital_health`, `cell_or_transplant`, … |
| `primary_endpoint_class` | The highest-priority class among the primary outcomes (disability progression > relapse > MRI lesions > atrophy > …) |
| `result_signal` | Machine-derived result status — see below |
| `why_stopped_class` | For terminated/withdrawn trials: `futility_or_efficacy`, `safety`, `business_or_sponsor`, `enrolment`, `covid`, … |

### `result_signal` values

This is a status flag, **not a verdict on whether a drug works.**

| Value | Meaning |
|---|---|
| `primary_p_lt_0.05` | ClinicalTrials.gov posted at least one superiority analysis of a primary outcome with p < 0.05. Multi-arm and dose-finding trials can carry this flag when only one arm or dose met it |
| `primary_p_ge_0.05` | Posted superiority analyses of primary outcomes, none with p < 0.05 |
| `primary_tested_noninferiority` | Only non-inferiority or equivalence analyses posted |
| `results_posted_no_primary_test` | Results posted without a statistical test of the primary outcome (common in single-arm and safety studies) |
| `publication_linked` | The registry links a results publication |
| `publication_found_europepmc` | No registry link, but a clinical-trial-type paper in Europe PMC cites the trial's ID |
| `completed_no_results_found` | Interventional, completed more than two years ago, with no posted results, no linked paper and no Europe PMC trial report found. A candidate for "unreported", to be confirmed by hand |
| `ongoing`, `terminated:<reason>`, `withdrawn:<reason>`, `status_unknown`, `completed_recent_or_undated` | As named |

## Method

1. **Harvest** (code, no AI): ClinicalTrials.gov API v2 (condition queries for MS, CIS/RIS, demyelinating disease, NMO, MOG antibody disease, optic neuritis); EU CTR full-text downloads (same terms); ISRCTN API.
2. **Scope**: rules over condition fields, titles and keywords. Broad registry searches return many off-target trials (ALS, tuberous sclerosis, CIDP, systemic sclerosis…); these are excluded.
3. **Dedupe**: registry records are merged when one lists another's ID (NCT ↔ EudraCT ↔ ISRCTN). Trials registered in two places without cross-referencing remain separate rows.
4. **Normalise interventions**: names are cleaned (doses, routes, formulations removed) and matched exactly to ChEMBL preferred names or synonyms; mechanisms, targets and ATC classes come from ChEMBL.
5. **Tag**: rule sets in `scripts/tags.py` (`rules_v0`) and `scripts/mechanisms.py` (`mechmap_v0_draft`).
6. **Publications**: registry-linked PMIDs, plus Europe PMC full-text search for each registry ID.

## Known accuracy (hand audit, not yet a gold standard)

Two random samples of interventional tier-1 trials were checked by hand against the registry records
(`audit_sample.csv`, 60 trials; `audit_sample_2.csv`, 50 trials, drawn after fixes). These checks were done by
the build author, not by clinicians, so they are indicative only.

- First sample: the main errors were paediatric false positives from phrases like "child-bearing potential" (4/60),
  off-target trials pulled in through keywords (a fingolimod asthma study, an IVIg CIDP study: 2/60), and drug arms
  that registrants had labelled "active comparator". All three rules were fixed.
- Second sample: no scope errors. Remaining issues were novel drugs with no mechanism node (fixed for the ones
  found) and a few debatable population or endpoint labels (about 2–4 of 50).
- 18 landmark trials were checked (`landmark_check.csv`, `validate.log`): all present with the expected population,
  drug and mechanism, except SPRINT-MS and CHAMPION-NMOSD, which are present but carry no acronym in the registry.

Before a public release, a gold set of ~200 trials tagged independently by two advisors should be used to report
per-field accuracy.

## Known gaps in v0

- **CTIS (EU trials authorised from 2023) is not yet included.** Many new EU-only trials are missing.
- WHO ICTRP sources (Chinese, Japanese, Iranian, Australian registries etc.) are not yet included.
- EudraCT records carry no completion dates and no results flag in this harvest.
- Results are only parsed from ClinicalTrials.gov posted analyses; papers are linked, not read. Effect sizes from publications come in the next stage (extractor + verifier bots, human review).
- The mechanism map is a draft. It needs review by a neurologist and a pharmacologist before tier-2 gating relies on it.
- Drug names that don't match ChEMBL exactly (misspellings, internal codes, combinations) are left unmatched and listed for curation.

## Licence and attribution

Proposed: **CC BY 4.0** for the data, Apache-2.0 for the code. Underlying registry records are public-domain or openly
reusable registry data; ChEMBL is CC BY-SA 3.0 — the ChEMBL-derived fields (mechanism text, targets, ATC) inherit
share-alike terms, so the licence for the `drugs` and `trial_interventions` tables must be confirmed before release.
Please cite: *MSFrontier Trial Bank, version 0.1.0* (DOI to be assigned at release).
