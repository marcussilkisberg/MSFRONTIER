# MSFrontier knowledge layers (v1, machine-only) — 27 Oct 2026

Everything below is machine-assembled from structured public sources, refreshed weekly by the "Trial bank refresh"
GitHub workflow, and loaded into the Supabase `bank` schema by migration 005. Nothing is human-reviewed.

| Layer | Table(s) | Source | Size (first build) |
|---|---|---|---|
| Trials | `trials_current` + child tables | ClinicalTrials.gov, EU CTR, ISRCTN, ChEMBL, Europe PMC | 4,364 trials |
| Results | `trial_results`, `trial_arm_safety` | ClinicalTrials.gov posted results (structured, no AI extraction) | 39,899 outcome-by-arm values from 552 trials; 1,480 arm safety rows |
| Treatments | `treatments`, `treatment_products`, `regulatory_events` | EMA medicines report, Drugs@FDA, openFDA labels, ChEMBL | 29 medicines (22 MS disease-modifying, 4 NMOSD, 3 symptom), 71 product records, 12 EU refusals/withdrawals |
| Safety signals | `treatment_safety_signals`, `treatment_adverse_event_reports` | EMA safety letters (DHPC) and referrals; FDA FAERS counts | Top 10 reported reactions per medicine |
| Measures | `measures` | Definitions written by Claude; usage counts computed from the trial bank | 27 measures |
| Failures | view `failures` | Registry evidence: posted primary analysis not met, or stopped for futility or safety | 98 trials |

## Known limits
- **Results** cover only trials that posted results on ClinicalTrials.gov. Results reported only in papers need an
  AI extraction step, deliberately left out of the machine-only v1 because unreviewed extracted numbers are the
  riskiest thing to publish.
- **Failures** therefore miss paper-only failures (e.g. MS-STAT2 / simvastatin).
- **Treatments**: centrally authorised EU medicines are authorised in all EU/EEA countries including the Nordics;
  national reimbursement decisions (TLV, Medicinrådet, Nye Metoder) are not yet included. Nationally authorised
  products (e.g. glatiramer acetate) show as "not centrally authorised". Corticosteroids for relapses are not listed.
- **FDA dates** are licence dates, not indication dates: alemtuzumab and ofatumumab show earlier cancer approvals.
- **FAERS** counts are reports, not rates, and do not prove causation.
- Drug lists inside trials can include pre-medications given in trial arms (e.g. methylprednisolone before infusions).
