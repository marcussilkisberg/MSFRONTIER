-- 011_literature.sql — reviews and guidelines (the literature layer). Run after 003-010. Safe to re-run.
-- Filled every week by scripts/literature_layer.py through load_supabase.py. Public read, like the rest of the bank.

create table if not exists bank.papers (
  pmid              text primary key,
  doi               text,
  pmcid             text,
  title             text not null,
  journal           text,
  pub_year          int,
  pub_date          date,
  authors           text,
  kind              text not null,      -- meta_analysis | systematic_review | umbrella_review | guideline | consensus
  populations       text[],             -- any_ms, relapsing, progressive, spms, ppms, early_cis_ris, paediatric, optic_neuritis, nmosd, mogad
  topics            text[],             -- treatment_effect, treatment_safety, diagnosis, prognosis, biomarkers_imaging, causes_risk, epidemiology, pathology_mechanism, symptoms_rehabilitation, pregnancy_family, other
  aims              text[],
  approach_groups   text[],
  frontiers         text[],
  drugs             text[],
  chembl_ids        text[],
  direction         text,               -- benefit | no_benefit | mixed | harm | uncertain | not_applicable
  conclusion_quote  text,               -- copied word for word from the abstract, checked by the script
  n_studies         int,                -- only when the number appears in the abstract
  summary           text,               -- one plain-English sentence written by software
  cited_by          int,
  open_access       boolean,
  url               text,
  tagged_by         text,
  tags_version      text
);
create index if not exists papers_year_idx on bank.papers (pub_year desc);
create index if not exists papers_frontiers_idx on bank.papers using gin (frontiers);
create index if not exists papers_groups_idx on bank.papers using gin (approach_groups);

create table if not exists bank.paper_links (
  pmid         text not null references bank.papers(pmid) on delete cascade,
  target_type  text not null,           -- hypothesis | treatment | trial | frontier
  target_id    text not null,
  rule         text,
  primary key (pmid, target_type, target_id)
);
create index if not exists paper_links_target_idx on bank.paper_links (target_type, target_id);

alter table bank.papers enable row level security;
alter table bank.paper_links enable row level security;
drop policy if exists public_read on bank.papers;
create policy public_read on bank.papers for select using (true);
drop policy if exists public_read on bank.paper_links;
create policy public_read on bank.paper_links for select using (true);
grant select on bank.papers, bank.paper_links to anon, authenticated;
grant all on bank.papers, bank.paper_links to service_role;
