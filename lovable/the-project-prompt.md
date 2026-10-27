# Lovable brief: "The Project" page (rebuild from scratch)

Paste as two Lovable messages: **Prompt 1** clears the old Project pages and builds the first half of the new
page; **Prompt 2** adds the studies and the rest.

Check before pasting (marked ⚑ in the copy): target dates, the funding policy line, and the open-release date.
Change them if they don't match your plans. Figures are from the MSFrontier Trial Bank as of 27 October 2026.

---

## PROMPT 1 — clear the old pages, build the structure and first sections

Rebuild the Project section from scratch.

**Remove the old content.** Delete the current Project page content and these sub-pages: Discovery programmes,
Hypothesis workbench, Validation stage-gates, Open questions, Critical assessment, Proposed approach for PPMS,
System map, and the "How participation will work" page. Redirect all their old URLs to `/project`. Remove the
generated illustration. Keep the site navigation item, labelled "The Project".

**Build one long page at `/project`** with an in-page table of contents (sticky on desktop, a dropdown on mobile) and
these sections in order: Overview · The problem · What the Project is · What it is not · Why independent · Built on
open data · The studies · How to judge our work · Take part · Who is behind it · Changelog. Sections "The studies"
onwards are added in the next prompt; leave placeholders.

**Style.** Same calm, editorial look as the rest of the site. Plain text, generous spacing, no stock or AI imagery,
no gradients or glowing effects. Use simple diagrams drawn in code only where specified. Body text 17–18px,
maximum line length about 70 characters.

**Use the copy below exactly.** Do not add adjectives, slogans or marketing phrases, and do not rewrite it.

### Overview (hero)

H1: **Why progressive MS trials fail, and how to make the next ones succeed**

Standfirst: The Project is an independent, open research effort on one problem: most trials in progressive multiple
sclerosis do not show a benefit, and we rarely learn enough from them. We use the public record of every MS trial
to find out why, and publish what we find, including when we are wrong.

Buttons: "Read Study 01" (scrolls to Study 01) · "Take part" (scrolls to Take part).

### The problem

Intro paragraph: Treatment of relapsing MS has improved a great deal in thirty years. Progressive MS has not kept
pace. In Europe, one medicine is approved for primary progressive MS (ocrelizumab), and the first for secondary
progressive MS without relapses (tolebrutinib) was approved in June 2026. In their main trials, each reduced the
risk of worsening by roughly a quarter to a third. Neither stops it.

Four figure cards in a row (two by two on mobile), each with a large number, a one-line label and a small source line:

1. **724** — mid- and late-stage drug trials (phase 1/2 to phase 3) registered in MS. Source: MSFrontier Trial Bank.
2. **97** — of those enrol only people with progressive MS. Source: MSFrontier Trial Bank.
3. **52** — of those 97 test medicines that act on the immune system, the approach that works in relapsing MS.
   Source: MSFrontier Trial Bank.
4. **4** — of those 97 report a positive main result in a registry. 11 are recorded as failed. For most of the
   rest, the outcome is only in a journal paper or not reported at all. Source: MSFrontier Trial Bank.

Small note under the cards: "Figures as of 27 October 2026. The Trial Bank updates weekly. Counts come from
registry records and their machine-assigned tags." Link "MSFrontier Trial Bank" to `/research`.

Closing paragraph: A trial can fail because the drug does not work. It can also fail because it measured the wrong
thing, enrolled people unlikely to worsen during the trial, ran too short, or was sized on a wrong guess about how
fast the placebo group would decline. These are not the same failure, and they call for different fixes. Today they
are rarely told apart.

### What the Project is

Paragraph: The Project is a short series of numbered studies. Each asks one question, publishes its analysis plan
before looking at the results, and ends with a public output: a dataset, a tool or a report. Each study feeds the
next.

Three short points, as a list:
- **Focused.** One problem: why progressive MS trials fail, and what would make the next ones more likely to succeed.
- **Open.** Methods, data, code and changes of mind are public.
- **Cumulative.** Every study builds on the MSFrontier Trial Bank and adds to it.

### What it is not

A plain list:
- **Not medical advice.** We do not recommend treatments to individuals. Talk to your neurologist.
- **Not a laboratory or a clinical trial.** We do not test drugs on people. Studies that need patients or a lab are
  done with partners who have them.
- **Not a claim of discovery.** A hypothesis is worth as much as the test it survives.
- **Not a replacement for academic or industry research.** It is meant to help that research aim better.
- **Not funded by companies whose medicines we assess.** ⚑
- **Not a patient forum.** For stories and support, see MS patient organisations.

### Why independent

Intro: The Project is not part of a university, a hospital or a company. That is a deliberate choice, with real
advantages and real costs. Show the two lists side by side on desktop, stacked on mobile.

**What independence allows**
- We choose questions by what blocks progress, not by what fits a grant call or a single lab's speciality.
- We can publish null results and criticise trial designs, including those of large sponsors.
- We can move in weeks rather than grant cycles.
- Everything is public from the start: the analysis plan before the results, the data and code with each release.
- We can work with anyone, in any institution or country.

**What independence costs**
- We have no laboratory, no access to patient data and no ethics committee of our own. Studies that need them depend
  on partners.
- We cannot borrow an institution's reputation. Our credibility has to come from our methods, our openness and named
  outside reviewers.
- We are small, so we do a few things at a time and say no to the rest.

### Built on open data

Intro: The Project stands on the MSFrontier Trial Bank, the open repository this site maintains.

A simple horizontal diagram drawn in code (vertical on mobile), four boxes connected by arrows, with a return arrow
from the last box back to the first:
1. **Trial Bank** — Every registered MS trial, updated weekly from ClinicalTrials.gov, the EU Clinical Trials
   Register and ISRCTN, with posted results, approved treatments, safety reports and failures.
2. **Studies** — Each study takes a defined slice of the Trial Bank and asks one question of it.
3. **Outputs** — Datasets, tools and reports, each versioned and citable.
4. **Back into the Trial Bank** — What a study learns is added back, so the next study starts further ahead.

Below the diagram, a short paragraph: Every number we publish links to its source record. The Trial Bank is
assembled by software from public registries and regulators, and is labelled as machine-assembled wherever it
appears. The code and data will be released under open licences, with the first versioned release planned for
Q1 2027. ⚑

Then a sub-heading **How we use software and AI**, and this paragraph: Software collects registry and regulatory
data every week, tags it and flags changes. AI models draft summaries and extract numbers from papers; every
extracted number must appear word for word in its source, or it is discarded. Anything produced by a machine is
labelled as such. The conclusions of each study are written and signed by people and reviewed by named experts
before release.

---

## PROMPT 2 — the studies, how to judge us, take part, who we are, changelog

Fill the remaining sections of `/project`. Use the copy exactly.

### The studies

Intro: Four studies, in the order we will run them. Dates are targets and will be updated in the changelog if they
move. ⚑

Show each study as a large card with a number badge, title, status chip and target date in the header, and these
labelled parts in the body: **The question**, **Why it matters**, **How**, **What we will publish**, **What could
go wrong**. Status chip colours: "In preparation" blue, "Seeking partners" amber, "Planned" grey.

**Study 01 · The progression baseline** — status "In preparation" — target "First release: Q1 2027"
- The question: How fast do people with progressive MS worsen on placebo, on each of the measures trials use, and how
  many participants and how much time does each measure need to detect a realistic treatment effect?
- Why it matters: Every progressive MS trial is sized on an assumption about how fast its placebo group will worsen.
  If that assumption is wrong, the trial is too small or too short, and a useful drug can look like a failure. Trial
  teams each rebuild these numbers privately. There is no open, current source.
- How: We collect results from the placebo groups of progressive MS trials. The Trial Bank already holds posted
  placebo-group results from 42 progressive trials, 30 of them with disability measures. Results reported only in
  papers are added as our paper extraction comes online. We publish the analysis plan before pooling any data.
- What we will publish: An open table of placebo worsening rates by MS type, age, disability level and measure
  (EDSS, timed 25-foot walk, nine-hole peg test, brain volume, neurofilament light). A free calculator that turns
  these rates into the number of participants and the trial length needed.
- What could go wrong: The trials may differ too much to pool. If so, we will publish ranges and explain why a single
  number would mislead.

**Study 02 · Did the early signal predict the result?** — status "Planned" — target "Q2 2027"
- The question: When a drug improved MRI, brain volume or blood markers in a phase 2 trial in progressive MS, did it
  go on to slow disability in phase 3?
- Why it matters: Phase 2 trials rely on these early measures to decide which drugs deserve a large, expensive
  phase 3. If they predict poorly, money and patients' time go to the wrong drugs. Simvastatin slowed brain shrinkage
  by 43% in phase 2, then had no effect on disability in a 964-person phase 3 trial.
- How: We pair every drug and drug class that has both phase 2 and phase 3 results in progressive MS and compare the
  early and late results. The analysis plan is published first.
- What we will publish: The paired dataset, a report, and a plain guide to which early measures have earned trust and
  which have not.
- What could go wrong: There may be too few pairs for a firm answer. "Not enough evidence yet" is a result we will
  report as such.

**Study 03 · What everyday medicines tell us** — status "Seeking partners" — target "Protocol: 2027"
- The question: Do people with progressive MS who take common medicines for other conditions, such as statins,
  metformin, blood pressure drugs or antidepressants, worsen more slowly?
- Why it matters: The Nordic countries record diagnoses, prescriptions and MS disability for whole populations. Used
  with careful methods that mimic a trial on existing records, these registers can test ideas years faster and far
  more cheaply than a trial, and can rule out ideas that are not worth one.
- How: We write the protocol in the open. The analysis is run by registry researchers inside their own secure
  systems, under ethics approval. We never hold patient data.
- What we will publish: The protocol, the analysis code and the results, whatever they show.
- What could go wrong: Registry studies show associations, not proof. They can rank ideas for trials; they cannot
  replace trials. Without registry partners this study does not happen.

**Study 04 · What to test next, and how** — status "Planned" — target "Late 2027"
- The question: Which existing medicines, alone or in combination, are most worth testing in progressive MS, and how
  should each be tested?
- Why it matters: Platform trials such as Octopus add new drugs over time and need well-argued candidates. A shortlist
  is more useful if it also says which patients, which measures and what trial length each candidate needs.
- How: We combine the Trial Bank's record of what has been tried and failed, the mechanisms each drug acts on, human
  genetic evidence, and what Studies 01 to 03 teach about measures, patients and early signals.
- What we will publish: An open shortlist with a dossier per candidate, the candidates we ruled out and why, and the
  scoring method, which anyone can rerun with different weights.
- What could go wrong: Similar exercises have been run before, most notably by the MS Society with Medicines
  Discovery Catapult when choosing drugs for Octopus. Ours adds openness, continuous updating and advice on how to
  test each candidate. If it does no better than those exercises, we will say so.

### How to judge our work

Intro: Judge us by these commitments. If we break one, tell us.

A plain list:
- Analysis plans are published before results.
- Every number links to its source.
- Data and code are versioned and citable.
- Null and negative results are published with the same prominence as positive ones.
- Errors are corrected publicly, with the date and what changed.
- Each study is reviewed by named outside experts before release, and their comments are published.

### Take part

Intro: Specific help we need now. No affiliation is required.

Cards, one per group, each with a heading, two or three sentences on what we would ask, and a "Get in touch" button
that opens the form below with that group pre-selected:
- **Biostatisticians and epidemiologists** — Review the analysis plans for Studies 01 and 02. Help lead Study 03.
- **Registry researchers in Sweden, Denmark, Norway and Finland** — Host the Study 03 analyses in your secure
  environment, as co-investigators.
- **Neurologists and trial designers** — Tell us which assumptions you use when sizing progressive MS trials, and
  review our outputs before release.
- **Data and software contributors** — Improve the extraction checks, the Trial Bank pipelines and the Study 01
  calculator.
- **People living with progressive MS** — Tell us which measures reflect what matters in daily life: walking, hands,
  thinking, fatigue or something else. This decides which measures Study 01 covers first.
- **Funders** — Support analysis time and open data hosting. We publish all funding sources.

Contact form: name, email, role (dropdown with the six groups above plus "Other"), study of interest (01–04 or
"General"), message. A consent checkbox: "I agree that MSFrontier may store my message to reply to me." Under the
button: "Please do not send medical records or personal health information." Store submissions in the site's own
backend and send me an email notification.

### Who is behind it

Paragraph: MSFrontier is run by Marcus [surname], based in Sweden. ⚑ Outside reviewers for each study will be named
here as they join. Funding sources, if any, are listed here with amounts. As of October 2026, the Project has no
external funding. ⚑

### Changelog

A dated list, newest first, with this first entry:
- **27 October 2026** — The Project relaunched with a single focus: why progressive MS trials fail. Earlier pages
  on discovery programmes and hypotheses were removed because they described work that had not been done.
