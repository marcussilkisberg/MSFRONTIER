"""Hypothesis ledger: every therapeutic hypothesis the trial bank shows being tested, plus those the Project and human
genetics propose. Everything is derived from the bank by rule; nothing is linked by hand.

A hypothesis is an APPROACH (mechanism node, or non-drug category) x an AIM x a POPULATION, e.g.
  H:slow_progression:anti_cd20_b_cell:progressive  ->  "B-cell depletion (anti-CD20) slow disability worsening in
  progressive MS". IDs are deterministic, so they stay stable from week to week.

Inputs : ../data/trials.parquet, mechanism_nodes.parquet, genetic_leads.parquet (optional),
         trial_readouts.parquet (optional, from readouts_layer.py), ../project/*.yml
Outputs: ../data/hypotheses.parquet, hypothesis_evidence.parquet, project_studies.parquet, project_hypotheses.parquet
Usage  : python hypotheses_layer.py
"""
from datetime import date
from pathlib import Path

import json
import re

import pandas as pd
import yaml

import tags as T

ROOT = Path(__file__).resolve().parent.parent
DATA, PROJECT = ROOT / "data", ROOT / "project"
RULES_VERSION = "hypotheses_v0"

AIMS = {  # order = display order
    "prevent":           {"label": "Prevent or delay MS",          "verb": "prevent or delay MS"},
    "stop_inflammation": {"label": "Stop inflammation",            "verb": "reduce relapses and new lesions"},
    "slow_progression":  {"label": "Slow progression",             "verb": "slow disability worsening"},
    "protect_nerves":    {"label": "Protect nerves",               "verb": "protect nerve tissue"},
    "repair":            {"label": "Repair myelin",                "verb": "repair myelin"},
    "restore_function":  {"label": "Restore function",             "verb": "improve symptoms or function"},
    "reset":             {"label": "Reset the immune system",      "verb": "reset the immune system for lasting remission"},
}
EFFICACY = {"relapse", "mri_lesions", "disability_progression", "walking_mobility", "upper_limb", "cognition",
            "brain_atrophy", "fluid_biomarker", "retina_oct", "remyelination", "neurophysiology",
            "smouldering_inflammation", "vision"}
ENDPOINT_AIM = {"relapse": "stop_inflammation", "mri_lesions": "stop_inflammation",
                "disability_progression": "slow_progression", "walking_mobility": "slow_progression",
                "upper_limb": "slow_progression", "cognition": "slow_progression",
                "smouldering_inflammation": "slow_progression",
                "brain_atrophy": "protect_nerves", "fluid_biomarker": "protect_nerves", "retina_oct": "protect_nerves",
                "remyelination": "repair", "neurophysiology": "repair"}
FUNCTION_ENDPOINTS = {"walking_mobility", "upper_limb", "cognition", "fatigue", "spasticity", "bladder_bowel_sexual",
                      "pain", "mood_sleep", "physical_function", "quality_of_life_pro", "vision",
                      "disability_progression"}
SYMPTOM_ENDPOINTS = FUNCTION_ENDPOINTS - {"disability_progression"}
RESET_NODES = {"immune_reconstitution"}
CAR_T = re.compile(r"\bcar[- ]?t\b|chimeric antigen receptor|autoleucel|cabtagene", re.I)
SKIP_NODES = {"imaging_tracer"}
# Mechanism groups that hold unrelated drugs. A verdict for the whole group would mislead (laquinimod and daclizumab
# share "T-cell / cytokine targeting"), so these get one hypothesis per drug; the group stays the row on the map.
MIXED_NODES = {"t_cell_costimulation", "broad_immunosuppression", "cell_therapy_tolerance", "axonal_neuroprotection",
               "mitochondrial_oxidative", "microglia_innate", "hormonal", "remyelination", "nutritional_supplement",
               "pain_mood_cognition", "other_b_cell_plasma_cell", "antiviral_ebv", "fatigue_wakefulness", "bladder",
               "complement", "fcrn_igg", "spasticity"}
NONDRUG = {"exercise_rehabilitation": "Exercise and rehabilitation", "cognitive_psychological": "Cognitive and psychological therapy",
           "neuromodulation_device": "Brain or nerve stimulation", "device_other": "Assistive and other devices",
           "digital_health": "Digital health", "diet_nutrition": "Diet", "cell_or_transplant": "Cell therapy or transplant"}
POPULATIONS = {"ppms": "primary progressive MS", "spms": "secondary progressive MS",
               "progressive": "progressive MS (primary and secondary)", "relapsing": "relapsing MS",
               "relapsing_and_progressive": "relapsing and progressive MS", "early_cis_ris": "early MS (CIS or RIS)",
               "unspecified": "MS (type not specified)", "nmosd": "NMOSD", "mogad": "MOGAD",
               "optic_neuritis": "optic neuritis"}
POP_FAMILY = {"progressive": ["ppms", "spms", "progressive"],
              "relapsing": ["relapsing", "relapsing_and_progressive"]}
ONGOING = {"recruiting", "active_not_recruiting", "not_yet_recruiting", "enrolling_by_invitation", "ongoing",
           "ongoing_inferred", "suspended", "transitioned_to_ctis"}
P3 = {"phase3", "phase2|phase3"}
P2 = {"phase2"}
VERDICT_LABEL = {
    "supported": "Supported in phase 3", "not_supported": "Not supported in phase 3", "mixed": "Mixed phase 3 results",
    "early_signal": "Positive in phase 2 only", "early_negative": "Negative in phase 2",
    "mixed_early": "Mixed phase 2 results",
    "incomplete_phase3": "Phase 3 results not all read yet", "incomplete_phase2": "Phase 2 results not all read yet",
    "no_readout": "No result yet", "untested": "Not yet tested",
}


def split(s):
    return [x for x in str(s or "").split("|") if x and x != "nan"]


def trial_aims(t, approach, family, tags=None):
    tags = set(split(t.primary_endpoint_tags)) if tags is None else set(tags)
    pop = t.population_group
    aims = set()
    car_t = approach == "cell_therapy_tolerance" and CAR_T.search(f"{t.title} {t.drugs} {t.interventions_raw}")
    if approach in RESET_NODES or approach == "nd-cell_or_transplant" or car_t:
        if tags & EFFICACY:
            aims.add("reset")
    function_only = family == "symptomatic" or (
        approach.startswith("nd-") and approach not in ("nd-diet_nutrition", "nd-cell_or_transplant"))
    if function_only:
        # symptom treatments are judged on symptoms and function, not on disability progression (CUPID tested
        # dronabinol for progression; that says nothing about spasticity relief)
        if tags & (SYMPTOM_ENDPOINTS | ({"vision", "walking_mobility", "upper_limb"} if approach.startswith("nd-") else set())):
            aims.add("restore_function")
        return aims
    if approach == "corticosteroid":
        # relapse treatment: disability scores here measure recovery from a relapse, not progression
        return {"stop_inflammation"} if tags & EFFICACY else set()
    if pop == "early_cis_ris" and tags & {"relapse", "mri_lesions", "disability_progression"}:
        aims.add("prevent")
    for tag in tags:
        if tag in ENDPOINT_AIM:
            aims.add(ENDPOINT_AIM[tag])
    return aims


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


BACKGROUND = re.compile(r"\b(?:added to|add[- ]?on (?:therapy |treatment )?to|as (?:an )?add[- ]?on to|"
                        r"(?:when used )?concurrently with|on top of|who are (?:being |already )?(?:treated with|"
                        r"receiving|on)|in (?:participants|patients|subjects) (?:treated with|receiving|on))\b"
                        r"([^.;:()]{0,80})", re.I)
BRANDS = {"avonex": "interferon beta", "rebif": "interferon beta", "betaseron": "interferon beta",
          "betaferon": "interferon beta", "plegridy": "peginterferon", "copaxone": "glatiramer",
          "tecfidera": "dimethyl fumarate", "gilenya": "fingolimod", "tysabri": "natalizumab",
          "ocrevus": "ocrelizumab", "aubagio": "teriflunomide", "kesimpta": "ofatumumab"}


def attributed_nodes(t, node_by_drug):
    """Mechanisms a trial actually tests. Experimental-arm drug lists also hold rescue and background medicines
    (ORACLE MS lists interferon beta as rescue therapy), so when a trial spans several mechanisms, keep only those
    whose drug is named in the trial's title; if the title names none, keep all."""
    nodes = [n for n in split(t.mechanism_nodes) if n not in SKIP_NODES]
    if len(nodes) < 2:
        return nodes
    text = f" {t.title} {t.official_title} {t.acronym} ".lower()
    # background medicines in add-on trials ("BIIB061 added to interferon-beta or glatiramer acetate", "BIIB033 ...
    # when used concurrently with Avonex") are not what the trial tests
    bg = " ".join(m.group(1) for m in BACKGROUND.finditer(text))
    main = BACKGROUND.sub(" ", text)
    def named_in(d, where):
        names = [d.split()[0].lower()] + [b for b, g in BRANDS.items() if d.lower().startswith(g)]
        return any(len(x) > 3 and re.search(r"\b" + re.escape(x), where) for x in names)
    bg_only = {n for d in split(t.drugs) if named_in(d, bg) and not named_in(d, main) for n in node_by_drug.get(d, [])}
    test_nodes = {n for d in split(t.drugs) if not (named_in(d, bg) and not named_in(d, main))
                  for n in node_by_drug.get(d, [])}
    nodes = [n for n in nodes if not (n in bg_only and n not in test_nodes)] or nodes
    if len(nodes) < 2:
        return nodes
    text = main
    named = {n for d in split(t.drugs) if len(d) > 3 and re.search(r"\b" + re.escape(d.split()[0].lower()), text)
             for n in node_by_drug.get(d, [])}
    kept = [n for n in nodes if n in named]
    return kept or nodes


def populations(t):
    """A trial that enrolled both PPMS and SPMS tests the hypothesis in each (SPI2 counts for biotin in PPMS and in
    SPMS); there is no separate 'progressive' hypothesis row."""
    g = t.population_group
    if g == "progressive":
        text = f"{t.title} {t.official_title}".lower()
        named = [p for p, rx in (("ppms", r"primary[- ]progressive|\bppms\b"), ("spms", r"secondary[- ]progressive|\bspms\b"))
                 if re.search(rx, text)]
        if named:                       # the title says which (O'HAND: "...Primary Progressive Multiple Sclerosis")
            return named
        ph = set(split(t.phenotypes)) & {"ppms", "spms"}
        return sorted(ph) if ph and not re.search(r"progressive multiple sclerosis|progressive ms\b", text) \
            else ["ppms", "spms"]       # "Progressive MS" with no type named: both (MS-SPI, SPI2)
    if g == "relapsing_and_progressive":
        # trials of SPMS that allow relapses (EXPAND, ASCEND) are tagged mixed from their criteria; the title decides
        text = f"{t.title} {t.official_title}".lower()
        named = [p for p, rx in (("ppms", r"primary[- ]progressive|\bppms\b"), ("spms", r"secondary[- ]progressive|\bspms\b"))
                 if re.search(rx, text)]
        if named and not re.search(r"relapsing|remitting|\brms\b|\brrms\b", text):
            return named
    return [g] if g in POPULATIONS else []


def verdict_phase(t):
    """A 'phase 2/3' trial with fewer than 100 participants is judged as phase 2 (lipoic acid in SPMS: 54)."""
    try:
        n = float(t.enrollment)
    except (TypeError, ValueError):
        n = None
    if t.phase in ("phase2|phase3", "phase3") and n is not None and n < 100:
        return "phase2"     # a "phase 3" of 88 people (MOVING, fingolimod vs interferon) is judged as phase 2
    return t.phase


ADD_ON = re.compile(r"\badd[- ]?on\b|\badjunct|\bwhen added to\b|\bon top of\b|\bbackground (?:therapy|treatment)\b"
                    r"|\bwho are (?:being |already )?(?:treated with|receiving|on)\b", re.I)


def is_add_on(t):
    """Both arms also take an established medicine (POINT: ponesimod or placebo, on top of dimethyl fumarate). A
    failure then says little about the approach, because the background medicine already controls the disease."""
    return bool(ADD_ON.search(f"{t.official_title or ''} {t.title or ''}"))


def aim_state(t, aim, g, family, state, source, analyses, readout):
    """The result for THIS aim. A trial with several primary measures can succeed on one and fail on another; a
    result is only credited to the aim its measure belongs to."""
    if source == "registry_analysis" and analyses:
        mine = [a for a in analyses if aim in trial_aims(t, g, family, a["tags"])]
        if not mine:
            return "other_endpoint_result"
        sup = [a for a in mine if a["ni"] not in ("NON_INFERIORITY", "EQUIVALENCE")]
        if any(a["p"] is not None and a["p"] < 0.05 for a in sup):
            return "met"
        if not sup and any(a["p"] is not None and a["p"] < 0.05 for a in mine):
            return "equivalent"
        return "not_met"
    if source == "paper_machine_read" and readout:
        res = readout.get("result")
        if not isinstance(res, dict):
            try:
                res = json.loads(readout.get("result_json") or "null")
            except (TypeError, ValueError):
                res = None
        measure = res.get("measure") if isinstance(res, dict) else None
        if measure:
            mtags = T.tag_endpoint(measure)
            maims = trial_aims(t, g, family, mtags) if mtags else set()
            if maims and aim not in maims:
                return "other_endpoint_result"
    return state


def evidence_state(t, readouts):
    rs = str(t.result_signal or "")
    if rs == "primary_p_lt_0.05":
        return "met", "registry_analysis"
    if rs == "primary_p_ge_0.05":
        return "not_met", "registry_analysis"
    if "futility" in rs:
        return "stopped_no_effect", "registry_stop_reason"
    if rs.startswith("terminated:safety"):
        return "stopped_safety", "registry_stop_reason"
    if t.status in ONGOING:
        return "ongoing", "registry_status"
    r = readouts.get(t.msf_trial_id)
    if r is not None and r["readout"] in ("met", "not_met", "mixed", "equivalent", "not_efficacy"):
        # 'equivalent' (non-inferiority shown) and 'not_efficacy' (safety/PK/cell-count endpoints) are read results
        # that say nothing about whether the approach works: they neither count nor block a verdict.
        # A published result outranks a registry "terminated" label (SPI2).
        return r["readout"], "paper_machine_read"
    if rs.startswith(("terminated", "withdrawn")):
        return "stopped_other", "registry_stop_reason"
    if rs in ("publication_linked", "publication_found_europepmc"):
        return "result_in_paper_unread", None
    return "no_result_found", None


def is_rct(t):
    return str(t.allocation or "").lower().startswith("random") and (
        bool(t.has_placebo_or_sham) or bool(split(t.comparator_drugs)))


UNREAD = {"result_in_paper_unread", "no_result_found"}


def verdict(ev):
    """Verdict at the highest phase with controlled evidence. If any completed controlled trial at that phase has not
    been read (no registry analysis, no machine-read paper), no verdict is given: one unread trial can be the one
    that decides it (ORATORIO, the positive phase 3 of ocrelizumab in PPMS, posts no p-value in the registry)."""
    d = ev[ev.counts_toward_verdict]
    def n(phases, states):
        return int((d.verdict_phase.isin(phases) & d.state.isin(states)).sum())
    def unread(phases):
        return int((ev.eligible_for_verdict & ev.verdict_phase.isin(phases) & ev.state.isin(UNREAD)).sum())
    for phases, (sup, neg, mix, inc) in ((P3, ("supported", "not_supported", "mixed", "incomplete_phase3")),
                                         (P2, ("early_signal", "early_negative", "mixed_early", "incomplete_phase2"))):
        m, nm, mx, u = n(phases, {"met"}), n(phases, {"not_met", "stopped_no_effect"}), n(phases, {"mixed"}), unread(phases)
        if not (m or nm or mx or u):
            continue
        if u:
            return inc
        if (m and nm) or mx:
            return mix
        return sup if m else neg
    return "no_readout"


OUTCOME_LABEL = {"roadmap": "Roadmap", "testing": "Being tested", "pending": "Results pending",
                 "promising": "Promising", "confirmed": "Confirmed", "mixed": "Mixed", "failed_early": "Failed early",
                 "disproven": "Disproven", "unclear": "No clear answer"}


def outcome(v, status, n_ongoing):
    """The one status the website shows. A verdict wins over 'being tested'; ongoing trials are shown as a dot."""
    if v == "supported":
        return "confirmed"
    if v == "not_supported":
        return "disproven"
    if v in ("mixed", "mixed_early"):
        return "mixed"
    if v == "early_signal":
        return "promising"
    if v == "early_negative":
        return "failed_early"
    if status == "proposed":
        return "roadmap"
    if n_ongoing:
        return "testing"
    if v.startswith("incomplete"):
        return "pending"
    return "unclear"


def main():
    trials = pd.read_parquet(DATA / "trials.parquet")
    trials = trials[trials.study_type == "interventional"]
    nodes = pd.read_parquet(DATA / "mechanism_nodes.parquet").set_index("node_id")
    analyses = {}
    apath = DATA / "trial_primary_analyses_ctgov.parquet"
    if apath.exists():
        for a in pd.read_parquet(apath).itertuples():
            pv = None if pd.isna(a.p_value) else float(a.p_value)
            if a.p_op in ("<", "<=") and pv is not None:
                pv = min(pv, 0.049) if pv <= 0.05 else pv
            tg = split(a.endpoint_tags)
            if "disability_progression" in tg:   # "disability ... in the MRI activity analysis set" is a disability result
                tg = [x for x in tg if x != "mri_lesions"]
            analyses.setdefault(a.msf_trial_id, []).append(
                {"tags": tg, "p": pv, "ni": str(a.non_inferiority_type or "").upper()})
    rpath = DATA / "trial_readouts.parquet"
    readouts = pd.read_parquet(rpath).set_index("msf_trial_id").to_dict("index") if rpath.exists() else {}

    drugs = pd.read_parquet(DATA / "drugs.parquet")
    node_by_drug = {r.drug_name: split(r.mechanism_nodes) for r in drugs.itertuples()}
    approach_label = {n: r.label for n, r in nodes.iterrows()}
    approach_family = {n: r.family for n, r in nodes.iterrows()}
    approach_label.update({"nd-" + k: v for k, v in NONDRUG.items()})
    approach_family.update({"nd-" + k: "non_drug" for k in NONDRUG})

    rows, drug_label = [], {}
    for t in trials.itertuples():
        pops = populations(t)
        if not pops:
            continue
        approaches = []
        for n in attributed_nodes(t, node_by_drug):
            if n in MIXED_NODES:
                ds = [d for d in split(t.drugs) if n in node_by_drug.get(d, [])]
                for d in ds:
                    approaches.append(f"{n}.{slug(d)}")
                    drug_label[f"{n}.{slug(d)}"] = d[:1].upper() + d[1:]
                if not ds:
                    approaches.append(n)
            else:
                approaches.append(n)
        approaches += ["nd-" + c for c in split(t.nondrug_categories) if c in NONDRUG]
        if not approaches:
            continue
        state, source = evidence_state(t, readouts)
        rct = is_rct(t)
        comp_nodes = {n for d in split(t.comparator_drugs) for n in node_by_drug.get(d, [])}
        r = readouts.get(t.msf_trial_id) or {}
        vphase = verdict_phase(t)
        add_on = is_add_on(t)
        for a in approaches:
            g = a.split(".")[0]
            for aim in trial_aims(t, g, approach_family.get(g)):
              st = aim_state(t, aim, g, approach_family.get(g), state, source, analyses.get(t.msf_trial_id),
                             readouts.get(t.msf_trial_id))
              for pop in pops:
                rows.append({
                    "hypothesis_id": f"H:{aim}:{a}:{pop}", "msf_trial_id": t.msf_trial_id, "aim": aim,
                    "approach": a, "approach_group": g, "population": pop, "phase": t.phase,
                    "verdict_phase": vphase, "status": t.status, "state": st,
                    "state_source": source, "is_rct": rct, "has_placebo_or_sham": bool(t.has_placebo_or_sham),
                    # A verdict counts placebo/sham-controlled RCTs, plus active-comparator RCTs that BEAT a drug
                    # of another mechanism. Failing to beat an active drug, or dose comparisons within one
                    # mechanism (e.g. GAVOTTE, high- vs standard-dose ocrelizumab), say nothing about whether
                    # the approach works.
                    "eligible_for_verdict": bool(rct and vphase in (P3 | P2) and g not in comp_nodes),
                    # placebo with an active comparator is a double-dummy, not a placebo control (GEMINI 1/2)
                    # For stopping inflammation, an add-on trial counts only when it succeeds: the background
                    # medicine already controls relapses, so a failure says little. For progression, protection
                    # and repair the background medicine does not do the same job, so a failure there counts.
                    "counts_toward_verdict": bool(rct and vphase in (P3 | P2) and g not in comp_nodes and (
                        (bool(t.has_placebo_or_sham) and not split(t.comparator_drugs)
                         and not (add_on and aim == "stop_inflammation"))
                        or st == "met")),
                    "add_on": add_on,
                    "comparator_drugs": split(t.comparator_drugs),
                    "enrollment": t.enrollment, "start_year": t.start_year, "drugs": split(t.drugs),
                    "acronym": t.acronym, "title": t.title, "primary_endpoint_tags": split(t.primary_endpoint_tags),
                    "readout_quote": r.get("quote"), "readout_pmid": r.get("pmid"),
                })
    ev = pd.DataFrame(rows)

    # ---- Project registrations (the only hand-written input, versioned in this repository)
    studies = yaml.safe_load((PROJECT / "studies.yml").read_text()) if (PROJECT / "studies.yml").exists() else []
    proj = yaml.safe_load((PROJECT / "hypotheses.yml").read_text()) if (PROJECT / "hypotheses.yml").exists() else []
    proj_rows = []
    for p in proj or []:
        hid = (f"H:{p['aim']}:{p['approach']}:{p['population']}" if p.get("kind", "therapeutic") == "therapeutic"
               else None)
        proj_rows.append({**p, "hypothesis_id": hid})
        if hid and p["approach"] not in approach_label:
            approach_label[p["approach"]] = p.get("approach_label", p["approach"])
            approach_family[p["approach"]] = "proposed"
    projdf = pd.DataFrame(proj_rows)
    # a Project hypothesis about "progressive" MS joins the ledger rows for ppms, spms and mixed progressive trials
    ledger_ids = set(ev.hypothesis_id)
    def family_ids(hid, drugs):
        _, aim, a, pop = hid.split(":", 3)
        pops = set(POP_FAMILY.get(pop, [pop]))
        want = {slug(d) for d in (drugs if isinstance(drugs, (list, tuple)) else [])}
        out = []
        for lid in ledger_ids:
            _, la, lap, lp = lid.split(":", 3)
            grp, _, drug = lap.partition(".")
            if la == aim and lp in pops and (lap == a or (grp == a and (not want or drug in want))):
                out.append(lid)
        return sorted(out)
    if len(projdf):
        projdf["ledger_hypothesis_ids"] = [family_ids(h, d) if isinstance(h, str) else []
                                           for h, d in zip(projdf.hypothesis_id, projdf.get("drugs", [None] * len(projdf)))]
        # a registered hypothesis with no matching trials yet becomes its own 'proposed' ledger row
        projdf["hypothesis_id"] = [h if (isinstance(h, str) and not linked) else None
                                   for h, linked in zip(projdf.hypothesis_id, projdf.ledger_hypothesis_ids)]
        projdf["ledger_hypothesis_ids"] = [linked or ([h] if isinstance(h, str) else []) for h, linked in
                                           zip(projdf.hypothesis_id, projdf.ledger_hypothesis_ids)]
    study_by_hid = {}
    for r in projdf.itertuples() if len(projdf) else []:
        for h in r.ledger_hypothesis_ids:
            study_by_hid.setdefault(h, set()).add(r.study)

    # ---- one row per hypothesis
    leads = pd.read_parquet(DATA / "genetic_leads.parquet") if (DATA / "genetic_leads.parquet").exists() else None
    keys = set(ev.hypothesis_id) | set(projdf.hypothesis_id.dropna() if len(projdf) else [])
    out = []
    for hid in sorted(keys):
        _, aim, a, pop = hid.split(":", 3)
        g = a.split(".")[0]
        label = drug_label.get(a) or approach_label.get(a, a)
        e = ev[ev.hypothesis_id == hid] if len(ev) else ev
        v = verdict(e) if len(e) else "untested"
        n_ongoing = int((e.state == "ongoing").sum()) if len(e) else 0
        n_done = len(e) - n_ongoing if len(e) else 0
        status = "being_tested" if n_ongoing else "tested" if n_done else "proposed"
        dec = e[e.counts_toward_verdict] if len(e) else e
        phases = [p for p in ("phase4", "phase3", "phase2|phase3", "phase2", "phase1|phase2", "phase1", "early_phase1")
                  if len(e) and (e.phase == p).any()]
        verb = "prevent attacks" if aim == "stop_inflammation" and pop in ("nmosd", "mogad") else AIMS[aim]["verb"]
        n_unread3 = int((e.eligible_for_verdict & e.verdict_phase.isin(P3) & e.state.isin(UNREAD)).sum()) if len(e) else 0
        note = None
        out.append({
            "hypothesis_id": hid, "verdict_note": note, "n_unread_phase3": n_unread3, "aim": aim, "aim_label": AIMS[aim]["label"], "approach": a,
            "approach_label": label, "approach_group": g, "approach_group_label": approach_label.get(g, g),
            "approach_family": approach_family.get(g), "population": pop, "population_label": POPULATIONS.get(pop, pop),
            "statement": f"{label}: {verb} in {POPULATIONS.get(pop, pop)}",
            "status": status, "verdict": v, "verdict_label": VERDICT_LABEL[v],
            "outcome": outcome(v, status, n_ongoing), "outcome_label": OUTCOME_LABEL[outcome(v, status, n_ongoing)],
            "n_trials": len(e), "n_ongoing": n_ongoing,
            "n_rct_phase2plus": len(dec), "n_participants_rct": int(pd.to_numeric(dec.enrollment, errors="coerce").fillna(0).sum()) if len(dec) else 0,
            "n_met": int(e.state.isin({"met"}).sum()) if len(e) else 0,
            "n_not_met": int(e.state.isin({"not_met", "stopped_no_effect"}).sum()) if len(e) else 0,
            "n_stopped_safety": int((e.state == "stopped_safety").sum()) if len(e) else 0,
            "n_unread": int(e.state.isin({"result_in_paper_unread", "no_result_found"}).sum()) if len(e) else 0,
            "highest_phase": phases[0] if phases else None,
            "first_trial_year": int(e.start_year.min()) if len(e) and e.start_year.notna().any() else None,
            "latest_trial_year": int(e.start_year.max()) if len(e) and e.start_year.notna().any() else None,
            "drugs": sorted({d for x in e.drugs for d in x})[:40] if len(e) else [],
            "project_study_ids": sorted(study_by_hid.get(hid, [])),
            "origin": "project" if not len(e) else "trials",
            "rules_version": RULES_VERSION, "as_of": date.today().isoformat(),
        })
    hyp = pd.DataFrame(out)

    # gene symbols per hypothesis approach (drugs' targets), so genetic leads join without hand links
    if (DATA / "drug_targets.parquet").exists():
        dt = pd.read_parquet(DATA / "drug_targets.parquet")
        sym_by_drug = dt.groupby("drug_name").symbol.agg(lambda x: sorted(set(x.dropna()))).to_dict()
        hyp["target_genes"] = hyp.drugs.apply(lambda ds: sorted({s for d in ds for s in sym_by_drug.get(d, [])})[:40])
        if leads is not None:
            gl = leads[leads.genetic_score >= 0.5].set_index("symbol").genetic_score.to_dict()
            hyp["genetic_support_genes"] = hyp.target_genes.apply(lambda g: [s for s in g if s in gl])
    hyp.to_parquet(DATA / "hypotheses.parquet", index=False)
    hyp.to_csv(DATA / "hypotheses.csv", index=False)
    ev.to_parquet(DATA / "hypothesis_evidence.parquet", index=False)

    pd.DataFrame(studies or []).to_parquet(DATA / "project_studies.parquet", index=False)
    projdf.to_parquet(DATA / "project_hypotheses.parquet", index=False)
    print(f"hypotheses: {len(hyp)} ({hyp.status.value_counts().to_dict()}); evidence rows: {len(ev)}")
    print("verdicts:", hyp.verdict.value_counts().to_dict())


if __name__ == "__main__":
    main()
