"""Flatten CTIS (EU Clinical Trials Regulation) records into the MSF common schema."""
import json
import re
from pathlib import Path

import tags as T

PHASES = [("phase iv", "phase4"), ("phase iii", "phase3"), ("phase ii", "phase2"), ("phase i", "phase1")]


def _phase(text):
    t, out = (text or "").lower(), []
    for k, v in PHASES:
        if k in t:
            out.append(v)
            t = t.replace(k, "")
    return "|".join(sorted(set(out))) or None


def _dmy(s):
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _g(d, *path):
    for p in path:
        if d is None:
            return None
        d = d[p] if isinstance(d, list) and isinstance(p, int) and len(d) > p else (
            d.get(p) if isinstance(d, dict) else None)
    return d


def _status(rec):
    st = (rec.get("ctStatus") or "").lower()
    events = [e.get("notificationType") for te in (_g(rec, "events", "trialEvents") or [])
              for e in (te.get("events") or [])]
    if st == "ended":
        return "terminated" if "EARLY_TERMINATION" in events and "END_OF_TRIAL" not in events else "completed"
    if st == "halted":
        return "suspended"
    if st in ("not authorised", "expired", "withdrawn", "revoked", "cancelled"):
        return "withdrawn"
    if st in ("authorised", "ongoing", "authorised, recruiting", "authorised, not recruiting"):
        if "END_OF_RECRUITMENT" in events:
            return "active_not_recruiting"
        if "START_OF_RECRUITMENT" in events:
            return "recruiting"
        return "not_yet_recruiting"
    return st or None


def _ages(group):
    g = group or ""
    min_age = 0.0 if "0-17" in g else (18.0 if "18-64" in g else (65.0 if "65+" in g else None))
    max_age = None if "65+" in g else (64.0 if "18-64" in g else (17.0 if "0-17" in g else None))
    return min_age, max_age


def parse(raw_dir):
    raw_dir = Path(raw_dir)
    hits_path = raw_dir / "ctis_search.json"
    if not hits_path.exists():
        return [], [], [], [], []
    hits = json.loads(hits_path.read_text())
    trials, ids, interventions, outcomes, refs = [], [], [], [], []
    for ct, hit in hits.items():
        f = raw_dir / "ctis" / f"{ct}.json"
        if not f.exists():
            continue
        rec = json.loads(f.read_text())
        a = rec.get("authorizedApplication") or {}
        p1 = a.get("authorizedPartI") or {}
        td = p1.get("trialDetails") or {}
        ident = td.get("clinicalTrialIdentifiers") or {}
        info = td.get("trialInformation") or {}
        title = ident.get("publicTitle") or hit.get("ctTitle")
        otitle = ident.get("fullTitle") or title
        short = (ident.get("shortTitle") or "").strip() or None
        conds = [m.get("medicalCondition") for m in p1.get("medicalConditions") or [] if m.get("medicalCondition")]
        conds += [hit.get("conditions")] if hit.get("conditions") else []
        diseases, focus = T.classify_diseases(conds, [], title, otitle)
        tier = T.tier_for(diseases, focus)
        inclusion = " ".join(c.get("principalInclusionCriteria") or "" for c in
                             _g(info, "eligibilityCriteria", "principalInclusionCriteria") or [])
        min_age, max_age = _ages(hit.get("ageGroup"))
        phenos = T.tag_phenotypes([*conds, title or "", otitle or "", inclusion], max_age, min_age)

        # products: mpRoleInTrial 1 = test, 2 = comparator, 3 = placebo, 4 = auxiliary (rescue or background: left out)
        iv_names, has_placebo = [], False
        prods = [(str(p.get("mpRoleInTrial")), p) for p in p1.get("products") or []]
        if not prods:   # older records keep products only inside role groups
            code = {"test": "1", "comparator": "2", "placebo": "3", "auxiliary": "4"}
            prods = [(code.get((g.get("productRoleName") or "").lower(), "1"), p)
                     for g in p1.get("productRoleGroupInfos") or [] for p in g.get("products") or []]
        for code, prod in prods:
            if code == "4":
                continue
            di = prod.get("productDictionaryInfo") or {}
            cands = [di.get("activeSubstanceName"), prod.get("productName"), di.get("prodName")]
            name = next((c.strip() for c in cands if c and c.strip().lower() not in ("n/a", "-", "na", "none")), "")
            if code == "3" or T.is_placebo(name):
                has_placebo = True
                role, name = "placebo_or_sham", name or "placebo"
            elif not name:
                continue
            elif code == "2":
                role = "active_comparator"
            else:
                role = "experimental"
            interventions.append({"role": role, "registry": "ctis", "registry_id": ct,
                                  "intervention_type": "device" if prod.get("devices") else "drug",
                                  "name_raw": name, "other_names": di.get("productOtherName") or "",
                                  "is_comparator": role != "experimental",
                                  "description": (prod.get("productName") or "")[:500]})
            if role == "experimental":
                iv_names.append(name)

        prim_tags = []
        for kind, key in (("primary", "primaryEndPoints"), ("secondary", "secondaryEndPoints")):
            for e in _g(info, "endPoint", key) or []:
                text = e.get("endPoint") or ""
                et = T.tag_endpoint(text)
                if kind == "primary":
                    prim_tags.append(et)
                outcomes.append({"registry": "ctis", "registry_id": ct, "outcome_kind": kind,
                                 "measure": text[:400], "time_frame": "", "endpoint_tags": "|".join(et)})

        ids.append({"registry": "ctis", "registry_id": ct, "other_id": ct, "id_type": "ctis"})
        nct = _g(ident, "secondaryIdentifyingNumbers", "nctNumber", "number")
        if nct and re.fullmatch(r"NCT\d{8}", nct.strip().upper()):
            ids.append({"registry": "ctis", "registry_id": ct, "other_id": nct.strip().upper(), "id_type": "nct"})
        eud = _g(a, "eudraCt", "eudraCtCode")
        if eud and re.fullmatch(r"\d{4}-\d{6}-\d{2}", eud.strip()):
            ids.append({"registry": "ctis", "registry_id": ct, "other_id": eud.strip(), "id_type": "eudract"})
        for reg in _g(ident, "secondaryIdentifyingNumbers", "additionalRegistries") or []:
            n = (reg.get("number") or "").strip().upper()
            if re.fullmatch(r"ISRCTN\d{8}", n):
                ids.append({"registry": "ctis", "registry_id": ct, "other_id": n, "id_type": "isrctn"})

        text = f"{title} {otitle}".lower()
        countries = sorted({c.split(":")[0].strip() for c in hit.get("trialCountries") or [] if c})
        events = {e.get("notificationType"): e.get("date") for te in (_g(rec, "events", "trialEvents") or [])
                  for e in (te.get("events") or [])}
        sponsor = next((s for s in p1.get("sponsors") or [] if s.get("primary")), (p1.get("sponsors") or [None])[0])
        summaries = _g(rec, "results", "summaryResults") or []
        try:
            enrol = int(hit.get("totalNumberEnrolled") or 0) or None
        except ValueError:
            enrol = None
        status = _status(rec)
        trials.append({
            "registry": "ctis", "registry_id": ct,
            "url": f"https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT={ct}",
            "brief_summary": (_g(info, "trialObjective", "mainObjective") or "")[:6000] or None,
            "eligibility_text": ("Inclusion:\n" + "\n".join("- " + (c.get("principalInclusionCriteria") or "") for c in
                                 _g(info, "eligibilityCriteria", "principalInclusionCriteria") or [])
                                 + "\n\nExclusion:\n" + "\n".join("- " + (c.get("principalExclusionCriteria") or "")
                                 for c in _g(info, "eligibilityCriteria", "principalExclusionCriteria") or []))[:8000]
                                 if _g(info, "eligibilityCriteria", "principalInclusionCriteria") else None,
            "title": title, "official_title": otitle, "acronym": short, "org_study_id": short,
            "study_type": "interventional", "phase": _phase(hit.get("trialPhase")),
            "status": status, "why_stopped": None, "why_stopped_class": None,
            "start_date": rec.get("startDateEU") or _g(info, "trialDuration", "estimatedRecruitmentStartDate"),
            "primary_completion_date": None,
            "completion_date": events.get("END_OF_TRIAL") or _g(info, "trialDuration", "estimatedEndDate"),
            "last_update": _dmy(hit.get("lastUpdated")),
            "enrollment": enrol, "enrollment_type": "actual" if status in ("completed", "terminated") else "anticipated",
            "allocation": "randomized" if re.search(r"\brandomi[sz]ed\b", text) and "non-random" not in text
            else None,
            "intervention_model": None,
            "masking": "blinded" if "blind" in text else ("none" if "open-label" in text or "open label" in text else None),
            "primary_purpose": None, "n_arms": None,
            "has_placebo_or_sham": has_placebo or "placebo" in text,
            "lead_sponsor": _g(sponsor, "organisation", "name") if sponsor else hit.get("sponsor"),
            "sponsor_class": ("industry" if sponsor and sponsor.get("isCommercial") else "other") if sponsor else None,
            "countries": "|".join(countries), "n_countries": len(countries),
            "min_age_years": min_age, "max_age_years": max_age,
            "conditions_raw": "|".join(conds),
            "diseases": "|".join(diseases), "ms_focus": focus, "tier": tier,
            "phenotypes": "|".join(phenos), "population_group": T.population_group(phenos, diseases),
            "primary_endpoint_class": T.primary_endpoint_class(prim_tags),
            "primary_endpoint_tags": "|".join(sorted({t for ts in prim_tags for t in ts})),
            "interventions_raw": "|".join(iv_names), "intervention_types": "drug" if iv_names else "",
            "mesh_interventions": "",
            "has_posted_results": bool(summaries),
            "results_first_posted": (summaries[0].get("submissionDate") or "")[:10] if summaries else None,
            "n_result_pmids": 0, "_prim_ps": [],
        })
    return trials, ids, interventions, outcomes, refs
