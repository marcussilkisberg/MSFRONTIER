-- 015_preclinical.sql — lab evidence (animal and human cell studies), filled every week by
-- scripts/preclinical_layer.py through load_supabase.py. Run after 014. Safe to re-run. Public read.
-- Lab evidence is context: it never changes a hypothesis's status.

create table if not exists bank.preclinical_studies (
  pmid                 text primary key,
  doi                  text,
  pmcid                text,
  title                text not null,
  journal              text,
  pub_year             int,
  pub_date             date,
  authors              text,
  study_type           text not null,    -- intervention | genetic
  model_systems        text[],           -- eae, cuprizone, lysolecithin, theiler_virus, other_toxin, human_cells, other_animal
  species              text[],           -- mouse, rat, marmoset, other_primate, zebrafish, human_cells
  interventions        text[],           -- as written in the abstract
  intervention_type    text,             -- small_molecule, biologic, cell_therapy, gene_therapy, genetic_change, diet_microbiome, device_physical, other
  chembl_ids           text[],
  target_genes         text[],
  mechanism            text,
  aims                 text[],
  approach_groups      text[],
  frontiers            text[],
  dosing               text,             -- preventive | after_onset | both | not_stated | not_applicable
  direction            text,             -- benefit | no_benefit | mixed | harm | not_applicable
  randomised_reported  boolean,          -- the abstract mentions randomisation
  blinded_reported     boolean,          -- the abstract mentions blinding
  in_human_trials      boolean,          -- the intervention appears in a trial in the bank
  trial_drugs          text[],
  conclusion_quote     text,             -- copied word for word from the abstract, checked by the script
  summary              text,             -- one plain-English sentence written by software
  cited_by             int,
  open_access          boolean,
  url                  text,
  tagged_by            text,
  tags_version         text
);
create index if not exists preclinical_year_idx on bank.preclinical_studies (pub_year desc);
create index if not exists preclinical_groups_idx on bank.preclinical_studies using gin (approach_groups);
create index if not exists preclinical_frontiers_idx on bank.preclinical_studies using gin (frontiers);
create index if not exists preclinical_genes_idx on bank.preclinical_studies using gin (target_genes);

create table if not exists bank.preclinical_links (
  pmid         text not null references bank.preclinical_studies(pmid) on delete cascade,
  target_type  text not null,            -- approach_group | hypothesis | treatment | gene | frontier
  target_id    text not null,
  rule         text,
  primary key (pmid, target_type, target_id)
);
create index if not exists preclinical_links_target_idx on bank.preclinical_links (target_type, target_id);

create table if not exists bank.preclinical_ideas (
  idea_id            text primary key,   -- ChEMBL id, or the normalised name when ChEMBL has no match
  name               text not null,
  chembl_id          text,
  intervention_type  text,
  mechanism          text,
  n_papers           int,
  n_benefit          int,
  n_no_benefit       int,
  n_mixed            int,
  n_harm             int,
  n_after_onset      int,                -- papers that started treatment after the disease appeared
  model_systems      text[],
  approach_groups    text[],
  aims               text[],
  target_genes       text[],
  genetic_support    text[],             -- target genes with strong or moderate human genetic evidence (Open Targets)
  first_year         int,
  latest_year        int,
  in_human_trials    boolean,
  trial_drugs        text[],
  human_outcomes     text,               -- what the hypotheses for the same medicine show in people
  pmids              text[]
);
create index if not exists preclinical_ideas_papers_idx on bank.preclinical_ideas (n_papers desc);

create table if not exists bank.preclinical_targets (
  symbol             text primary key,
  n_papers           int,
  n_benefit          int,
  n_genetic_studies  int,
  trial_drugs        text[],
  in_human_trials    boolean,
  human_genetics     text,               -- strong | moderate | weak, from genetic_leads
  pmids              text[]
);

alter table bank.preclinical_studies enable row level security;
alter table bank.preclinical_links enable row level security;
alter table bank.preclinical_ideas enable row level security;
alter table bank.preclinical_targets enable row level security;
drop policy if exists public_read on bank.preclinical_studies;
create policy public_read on bank.preclinical_studies for select using (true);
drop policy if exists public_read on bank.preclinical_links;
create policy public_read on bank.preclinical_links for select using (true);
drop policy if exists public_read on bank.preclinical_ideas;
create policy public_read on bank.preclinical_ideas for select using (true);
drop policy if exists public_read on bank.preclinical_targets;
create policy public_read on bank.preclinical_targets for select using (true);
grant select on bank.preclinical_studies, bank.preclinical_links, bank.preclinical_ideas, bank.preclinical_targets
  to anon, authenticated;
grant all on bank.preclinical_studies, bank.preclinical_links, bank.preclinical_ideas, bank.preclinical_targets
  to service_role;
