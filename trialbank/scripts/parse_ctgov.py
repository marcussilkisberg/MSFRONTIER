"""Flatten ClinicalTrials.gov API v2 records into the MSF common schema."""
import json
import re
from datetime import date

import tags as T

AGE_RX = re.compile(r"([\d.]+)\s*(year|month|week|day)", re.I)


def age_years(s):
    if not s:
        return None
    m = AGE_RX.search(s)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2).lower()
    return round(v / {"year": 1, "month": 12, "week": 52, "day": 365}[unit], 2)


def norm_date(d):
    if not d:
        return None
    return d if len(d) == 10 else (d + "-01" if len(d) == 7 else d)


PHASE_MAP = {"EARLY_PHASE1": "early_phase1", "PHASE1": "phase1", "PHASE2": "phase2", "PHASE3": "phase3", "PHASE4": "phase4", "NA": "not_applicable"}


def parse(path):
    trials, ids, interventions, outcomes, analyses, refs = [], [], [], [], [], []
    today = date.today().isoformat()
    for line in open(path):
        rec = json.loads(line)
        s = rec["study"]
        p = s["protocolSection"]
        idm = p["identificationModule"]
        nct = idm["nctId"]
        st = p.get("statusModule", {})
        dm = p.get("designModule", {})
        di = dm.get("designInfo", {})
        cm = p.get("conditionsModule", {})
        el = p.get("eligibilityModule", {})
        sp = p.get("sponsorCollaboratorsModule", {})
        conditions = cm.get("conditions", [])
        keywords = cm.get("keywords", [])
        title = idm.get("briefTitle")
        otitle = idm.get("officialTitle")
        diseases, focus = T.classify_diseases(conditions, keywords, title, otitle)
        tier = T.tier_for(diseases, focus)
        inclusion = T.split_inclusion(el.get("eligibilityCriteria"))
        max_age = age_years(el.get("maximumAge"))
        min_age = age_years(el.get("minimumAge"))
        phenos = T.tag_phenotypes([*conditions, *keywords, title, otitle, inclusion], max_age, min_age)
        phases = [PHASE_MAP.get(x, x.lower()) for x in dm.get("phases", [])]
        countries = sorted({loc.get("country") for loc in p.get("contactsLocationsModule", {}).get("locations", []) if loc.get("country")})

        # ---- interventions
        arms = p.get("armsInterventionsModule", {})
        mesh_interv = [m["term"] for m in s.get("derivedSection", {}).get("interventionBrowseModule", {}).get("meshes", [])]
        trial_iv = []
        arm_type = {a.get("label"): (a.get("type") or "") for a in arms.get("armGroups", [])}
        for iv in arms.get("interventions", []):
            types = {arm_type.get(l, "") for l in iv.get("armGroupLabels", [])} - {""}
            if T.is_placebo(iv.get("name")) or (types and types <= {"PLACEBO_COMPARATOR", "SHAM_COMPARATOR"}):
                role = "placebo_or_sham"
            elif types and types <= {"ACTIVE_COMPARATOR", "PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION"} \
                    and "EXPERIMENTAL" in set(arm_type.values()):
                # only a comparator if the trial has a separate experimental arm; registrants often
                # label the drug arm of a drug-vs-placebo trial "active comparator"
                role = "active_comparator"
            else:
                role = "experimental"
            row = {
                "role": role,
                "registry": "ctgov", "registry_id": nct,
                "intervention_type": (iv.get("type") or "").lower(),
                "name_raw": iv.get("name"),
                "other_names": "; ".join(iv.get("otherNames", [])),
                "is_comparator": T.is_placebo(iv.get("name")) or T.is_placebo(iv.get("description")) and T.is_placebo(iv.get("name")),
                "description": (iv.get("description") or "")[:500],
            }
            interventions.append(row)
            trial_iv.append(row)

        # ---- outcomes
        om = p.get("outcomesModule", {})
        prim_tags = []
        for kind, key in (("primary", "primaryOutcomes"), ("secondary", "secondaryOutcomes")):
            for o in om.get(key, []):
                text = f"{o.get('measure', '')} {o.get('description', '')}"
                et = T.tag_endpoint(text)
                if kind == "primary":
                    # class from the measure title when it is taggable; descriptions often define
                    # relapses in EDSS terms, which would mislabel relapse trials as disability trials
                    prim_tags.append(T.tag_endpoint(o.get("measure", "")) or et)
                outcomes.append({
                    "registry": "ctgov", "registry_id": nct, "outcome_kind": kind,
                    "measure": (o.get("measure") or "")[:400],
                    "time_frame": (o.get("timeFrame") or "")[:200],
                    "endpoint_tags": "|".join(et),
                })

        # ---- results (posted primary-outcome analyses)
        res = s.get("resultsSection", {})
        prim_ps = []
        for m in res.get("outcomeMeasuresModule", {}).get("outcomeMeasures", []):
            if m.get("type") != "PRIMARY":
                continue
            for a in m.get("analyses", []):
                pv, op = T.parse_p(a.get("pValue"))
                analyses.append({
                    "registry_id": nct, "outcome_title": (m.get("title") or "")[:300],
                    "endpoint_tags": "|".join(T.tag_endpoint(m.get("title", "") + " " + m.get("description", ""))),
                    "p_value_raw": a.get("pValue"), "p_value": pv, "p_op": op,
                    "method": a.get("statisticalMethod"), "param_type": a.get("paramType"),
                    "param_value": a.get("paramValue"), "ci_lower": a.get("ciLowerLimit"), "ci_upper": a.get("ciUpperLimit"),
                    "non_inferiority_type": a.get("nonInferiorityType"),
                })
                if pv is not None:
                    prim_ps.append((pv, op, a.get("nonInferiorityType")))

        # ---- references
        n_result_refs = 0
        for r in p.get("referencesModule", {}).get("references", []):
            if r.get("pmid"):
                refs.append({"registry_id": nct, "pmid": r["pmid"], "ref_type": (r.get("type") or "").lower(),
                             "citation": (r.get("citation") or "")[:400]})
                if r.get("type") in ("RESULT", "DERIVED"):
                    n_result_refs += 1

        # ---- cross-registry ids
        ids.append({"registry": "ctgov", "registry_id": nct, "other_id": nct, "id_type": "nct"})
        for sec in idm.get("secondaryIdInfos", []):
            v = (sec.get("id") or "").strip()
            t = sec.get("type") or ""
            if t == "EUDRACT_NUMBER" or re.fullmatch(r"\d{4}-\d{6}-\d{2}", v):
                ids.append({"registry": "ctgov", "registry_id": nct, "other_id": v, "id_type": "eudract"})
            elif re.fullmatch(r"\d{4}-\d{6}-\d{2}-\d{2}", v):
                ids.append({"registry": "ctgov", "registry_id": nct, "other_id": v, "id_type": "ctis"})
            elif re.match(r"ISRCTN\d+", v, re.I):
                ids.append({"registry": "ctgov", "registry_id": nct, "other_id": v.upper(), "id_type": "isrctn"})

        status = (st.get("overallStatus") or "").lower()
        prim_completion = norm_date(st.get("primaryCompletionDateStruct", {}).get("date"))
        has_results = "resultsSection" in s

        trials.append({
            "registry": "ctgov", "registry_id": nct,
            "url": f"https://clinicaltrials.gov/study/{nct}",
            "brief_summary": (p.get("descriptionModule", {}).get("briefSummary") or "")[:6000] or None,
            "eligibility_text": (el.get("eligibilityCriteria") or "")[:8000] or None,
            "title": title, "official_title": otitle, "acronym": idm.get("acronym"),
            "org_study_id": idm.get("orgStudyIdInfo", {}).get("id"),
            "study_type": (dm.get("studyType") or "").lower(),
            "phase": "|".join(phases) or None,
            "status": status, "why_stopped": st.get("whyStopped"),
            "why_stopped_class": T.why_stopped_class(st.get("whyStopped")),
            "start_date": norm_date(st.get("startDateStruct", {}).get("date")),
            "primary_completion_date": prim_completion,
            "completion_date": norm_date(st.get("completionDateStruct", {}).get("date")),
            "last_update": norm_date(st.get("lastUpdatePostDateStruct", {}).get("date")),
            "enrollment": dm.get("enrollmentInfo", {}).get("count"),
            "enrollment_type": (dm.get("enrollmentInfo", {}).get("type") or "").lower() or None,
            "allocation": (di.get("allocation") or "").lower() or None,
            "intervention_model": (di.get("interventionModel") or "").lower() or None,
            "masking": (di.get("maskingInfo", {}).get("masking") or "").lower() or None,
            "primary_purpose": (di.get("primaryPurpose") or "").lower() or None,
            "n_arms": len(arms.get("armGroups", [])),
            "has_placebo_or_sham": any(r["is_comparator"] for r in trial_iv) or any(
                (a.get("type") or "") in ("PLACEBO_COMPARATOR", "SHAM_COMPARATOR") for a in arms.get("armGroups", [])),
            "lead_sponsor": sp.get("leadSponsor", {}).get("name"),
            "sponsor_class": (sp.get("leadSponsor", {}).get("class") or "").lower() or None,
            "countries": "|".join(countries), "n_countries": len(countries),
            "min_age_years": min_age, "max_age_years": max_age,
            "conditions_raw": "|".join(conditions),
            "diseases": "|".join(diseases), "ms_focus": focus, "tier": tier,
            "phenotypes": "|".join(phenos), "population_group": T.population_group(phenos, diseases),
            "primary_endpoint_class": T.primary_endpoint_class(prim_tags),
            "primary_endpoint_tags": "|".join(sorted({t for ts in prim_tags for t in ts})),
            "interventions_raw": "|".join(r["name_raw"] or "" for r in trial_iv if not r["is_comparator"]),
            "intervention_types": "|".join(sorted({r["intervention_type"] for r in trial_iv})),
            "mesh_interventions": "|".join(mesh_interv),
            "has_posted_results": has_results,
            "results_first_posted": norm_date(st.get("resultsFirstPostDateStruct", {}).get("date")),
            "n_result_pmids": n_result_refs,
            "_prim_ps": prim_ps,
        })
    return trials, ids, interventions, outcomes, analyses, refs
