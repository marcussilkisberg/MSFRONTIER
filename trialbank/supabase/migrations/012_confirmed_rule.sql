-- 012_confirmed_rule.sql — hypotheses rules v1 (1 Nov 2026). Run after 011. Safe to re-run.
-- "Confirmed" now needs two positive controlled phase 3 trials, or one plus approval for that use. Hypotheses with a
-- single positive phase 3 trial get the new outcome 'supported_one' ("Supported by one trial").
-- New columns: the trials that decide the status, so pages can show counts that match it.

alter table bank.hypotheses add column if not exists deciding_phase text;          -- phase3 | phase2 | null
alter table bank.hypotheses add column if not exists n_met_deciding int;           -- counting trials at that phase that met their goal
alter table bank.hypotheses add column if not exists n_not_met_deciding int;       -- ... that did not, or stopped for no effect
alter table bank.hypotheses add column if not exists n_other_trials int;           -- every other linked trial
