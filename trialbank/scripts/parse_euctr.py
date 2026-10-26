"""Flatten EU Clinical Trials Register full-text downloads into the MSF common schema.

One EudraCT trial appears once per member state; protocol fields come from the
first copy, countries and statuses are aggregated across copies.
"""
import re
from collections import defaultdict

import tags as T

EUD = re.compile(r"^EudraCT Number: (\d{4}-\d{6}-\d{2})", re.M)


def _f(block, label):
    m = re.search(r"^" + re.escape(label) + r"[ \t]*:?[ \t]*(.*)$", block, re.M)
    v = m.group(1).strip() if m else None
    return v or None


def _yes(block, label):
    return (_f(block, label) or "").lower().startswith("yes")


def parse(path):
    text = open(path).read()
    text = re.sub(r"\n#### QUERY=.*\n", "\n", text)
    blocks = re.split(r"\n(?=Summary\nEudraCT Number:)", text)
    by_id = defaultdict(list)
    for b in blocks:
        m = EUD.search(b)
        if m:
            by_id[m.group(1)].append(b)

    trials, ids, interventions, outcomes = [], [], [], []
    for eud, bs in by_id.items():
        b = bs[0]
        states, statuses = [], []
        for x in bs:
            nca = _f(x, "National Competent Authority") or ""
            country = nca.split(" - ")[0].strip()
            if country:
                states.append(country)
            statuses.append((_f(x, "Trial Status") or "").lower())
        title = _f(b, "A.3 Full title of the trial")
        short = _f(b, "A.3.2 Name or abbreviated title of the trial where available")
        lay = _f(b, "A.3.1 Title of the trial for lay people, in easily understood, i.e. non-technical, language")
        conds = [c for c in [_f(b, "E.1.1 Medical condition(s) being investigated"), _f(b, "E.1.2 Term")] if c]
        diseases, focus = T.classify_diseases(conds, [], lay or "", title or "")
        tier = T.tier_for(diseases, focus)
        incl = _f(b, "E.3 Principal inclusion criteria") or ""
        phenos = T.tag_phenotypes([*conds, title, lay, incl])
        if _f(b, "F.1.1 Trial has subjects under 18") and (_f(b, "F.1.2 Adults (18-64 years)") or "").lower().startswith("no"):
            phenos = sorted(set(phenos) | {"paediatric"})

        phases = [p for lab, p in (("E.7.1 Human pharmacology (Phase I)", "phase1"), ("E.7.2 Therapeutic exploratory (Phase II)", "phase2"),
                                   ("E.7.3 Therapeutic confirmatory (Phase III)", "phase3"), ("E.7.4 Therapeutic use (Phase IV)", "phase4"))
                  if _yes(b, lab)]
        # IMPs: INN first, product name as fallback
        imps = re.split(r"^D\.IMP: \d+", b, flags=re.M)[1:]
        iv_names = []
        for imp in imps:
            role = (_f(imp, "D.1.2 and D.1.3 IMP Role") or "").lower()
            inn = _f(imp, "D.3.8 INN - Proposed INN")
            prod = _f(imp, "D.3.1 Product name")
            code = _f(imp, "D.3.9.2 Current sponsor code")
            name = inn or prod or code
            if not name:
                continue
            comp = "placebo" in role or T.is_placebo(name)
            interventions.append({"role": "placebo_or_sham" if comp else ("active_comparator" if "comparator" in role else "experimental"),
                                  "registry": "euctr", "registry_id": eud, "intervention_type": "drug",
                                  "name_raw": name, "other_names": "; ".join(x for x in (prod, code) if x and x != name),
                                  "is_comparator": comp, "description": f"role: {role}"})
            if not comp and "comparator" not in role:
                iv_names.append(name)
        prim = _f(b, "E.5.1 Primary end point(s)") or ""
        sec = _f(b, "E.5.2 Secondary end point(s)") or ""
        prim_tags = [T.tag_endpoint(prim)] if prim else []
        for kind, txt in (("primary", prim), ("secondary", sec)):
            if txt:
                outcomes.append({"registry": "euctr", "registry_id": eud, "outcome_kind": kind, "measure": txt[:400],
                                 "time_frame": "", "endpoint_tags": "|".join(T.tag_endpoint(txt))})

        ids.append({"registry": "euctr", "registry_id": eud, "other_id": eud, "id_type": "eudract"})
        for x in bs:
            for lab, typ, rx in (("A.5.2 US NCT (ClinicalTrials.gov registry) number", "nct", r"NCT\d{8}"),
                                 ("A.5.1 ISRCTN (International Standard Randomised Controlled Trial) number", "isrctn", r"ISRCTN\d+")):
                v = (_f(x, lab) or "").upper().replace(" ", "")
                m = re.search(rx, v)
                if m:
                    ids.append({"registry": "euctr", "registry_id": eud, "other_id": m.group(0), "id_type": typ})

        status = _agg_status(statuses)
        sponsor_status = (_f(b, "B.3.1 and B.3.2\tStatus of the sponsor") or _f(b, "B.3.1 and B.3.2 Status of the sponsor") or "").lower()
        n = _int(_f(b, "F.4.2.2 In the whole clinical trial")) or _int(_f(b, "F.4.1 In the member state"))
        trials.append({
            "registry": "euctr", "registry_id": eud,
            "url": f"https://www.clinicaltrialsregister.eu/ctr-search/search?query=eudract_number:{eud}",
            "title": lay or title, "official_title": title, "acronym": short, "org_study_id": _f(b, "A.4.1 Sponsor's protocol code number"),
            "study_type": "interventional", "phase": "|".join(phases) or None,
            "status": status, "why_stopped": None, "why_stopped_class": None,
            "start_date": _f(b, "Date on which this record was first entered in the EudraCT database"),
            "primary_completion_date": None, "completion_date": None, "last_update": None,
            "enrollment": n, "enrollment_type": "anticipated",
            "allocation": "randomized" if _yes(b, "E.8.1.1 Randomised") else ("non_randomized" if _f(b, "E.8.1.1 Randomised") else None),
            "intervention_model": "crossover" if _yes(b, "E.8.1.6 Cross over") else ("parallel" if _yes(b, "E.8.1.5 Parallel group") else None),
            "masking": "double" if _yes(b, "E.8.1.4 Double blind") else ("single" if _yes(b, "E.8.1.3 Single blind") else ("none" if _yes(b, "E.8.1.2 Open") else None)),
            "primary_purpose": "treatment" if _yes(b, "E.6.3 Therapy") else None, "n_arms": None,
            "has_placebo_or_sham": _yes(b, "E.8.2.2 Placebo"),
            "lead_sponsor": _f(b, "B.1.1 Name of Sponsor"),
            "sponsor_class": "industry" if sponsor_status.startswith("commercial") else ("other" if sponsor_status else None),
            "countries": "|".join(sorted(set(states))), "n_countries": len(set(states)),
            "min_age_years": None, "max_age_years": None,
            "conditions_raw": "|".join(conds), "diseases": "|".join(diseases), "ms_focus": focus, "tier": tier,
            "phenotypes": "|".join(phenos), "population_group": T.population_group(phenos, diseases),
            "primary_endpoint_class": T.primary_endpoint_class(prim_tags),
            "primary_endpoint_tags": "|".join(sorted({t for ts in prim_tags for t in ts})),
            "interventions_raw": "|".join(iv_names), "intervention_types": "drug", "mesh_interventions": "",
            "has_posted_results": None, "results_first_posted": None, "n_result_pmids": 0, "_prim_ps": [],
        })
    return trials, ids, interventions, outcomes


def _agg_status(sts):
    s = [x for x in sts if x and "no longer in eu" not in x]
    if s and all("transitioned" in x for x in s):
        return "transitioned_to_ctis"
    s = [x for x in s if "transitioned" not in x] or s
    if not s:
        return None
    for key in ("ongoing", "restarted", "temporarily halted", "suspended"):
        if any(key in x for x in s):
            return "ongoing" if key in ("ongoing", "restarted") else "suspended"
    if any("prematurely ended" in x for x in s) and not any(x == "completed" for x in s):
        return "terminated"
    if all("completed" in x for x in s):
        return "completed"
    if any("prematurely" in x for x in s):
        return "terminated"
    return s[0]


def _int(s):
    try:
        return int(re.sub(r"[^\d]", "", s)) if s and re.search(r"\d", s) else None
    except ValueError:
        return None
