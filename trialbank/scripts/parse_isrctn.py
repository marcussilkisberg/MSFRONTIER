"""Flatten ISRCTN XML into the MSF common schema."""
import glob
import re
import xml.etree.ElementTree as ET

import tags as T

NS = {"i": "http://www.67bricks.com/isrctn"}


def _t(el, path):
    x = el.find(path, NS)
    return (x.text or "").strip() if x is not None and x.text else None


def _all(el, path):
    return [(x.text or "").strip() for x in el.findall(path, NS) if x.text and x.text.strip()]


PHASE_MAP = [("phase iv", "phase4"), ("phase iii", "phase3"), ("phase ii", "phase2"), ("phase i", "phase1"),
             ("phase 4", "phase4"), ("phase 3", "phase3"), ("phase 2", "phase2"), ("phase 1", "phase1"),
             ("not applicable", "not_applicable")]


def _phase(raw):
    out = []
    for r in raw:
        rl = r.lower()
        found = []
        for k, v in PHASE_MAP:
            if k in rl and v not in found:
                found.append(v)
                rl = rl.replace(k, "")
        out += found
    return "|".join(sorted(set(out))) or None


def _date(s):
    return s[:10] if s else None


def parse(pattern):
    trials, ids, interventions, outcomes, refs = [], [], [], [], []
    seen = set()
    for f in sorted(glob.glob(pattern)):
        root = ET.parse(f).getroot()
        for ft in root.findall("i:fullTrial", NS):
            tr = ft.find("i:trial", NS)
            num = _t(tr, "i:isrctn")
            rid = f"ISRCTN{num}"
            if rid in seen:
                continue
            seen.add(rid)
            td = tr.find("i:trialDescription", NS)
            title, otitle = _t(td, "i:title"), _t(td, "i:scientificTitle")
            conds = _all(tr, "i:conditions/i:condition/i:description")
            diseases, focus = T.classify_diseases(conds, [], title, otitle)
            tier = T.tier_for(diseases, focus)
            parts = tr.find("i:participants", NS)
            inclusion = _t(parts, "i:inclusion") or ""
            lo = parts.find("i:lowerAgeLimit", NS)
            hi = parts.find("i:upperAgeLimit", NS)
            min_age = float(lo.get("value")) if lo is not None and lo.get("value") else None
            max_age = float(hi.get("value")) if hi is not None and hi.get("value") else None
            phenos = T.tag_phenotypes([*conds, title, otitle, inclusion], max_age, min_age)

            ivs = tr.findall("i:interventions/i:intervention", NS)
            iv_names, iv_types, phases = [], set(), []
            for iv in ivs:
                typ = (_t(iv, "i:interventionType") or "").lower()
                iv_types.add(typ)
                phases.append(_t(iv, "i:phase") or "")
                dn = _t(iv, "i:drugNames")
                desc = _t(iv, "i:description") or ""
                for name in (re.split(r",\s*|;\s*|\n", dn) if dn else []):
                    if name.strip():
                        comp = T.is_placebo(name)
                        interventions.append({"role": "placebo_or_sham" if comp else "experimental",
                                              "registry": "isrctn", "registry_id": rid, "intervention_type": typ,
                                              "name_raw": name.strip(), "other_names": "", "is_comparator": comp,
                                              "description": desc[:500]})
                        if not comp:
                            iv_names.append(name.strip())

            prim_tags = []
            for kind, path in (("primary", "i:primaryOutcomes/i:outcomeMeasure"), ("secondary", "i:secondaryOutcomes/i:outcomeMeasure")):
                for o in td.findall(path, NS):
                    text = f"{_t(o, 'i:variable') or ''} {_t(o, 'i:method') or ''}"
                    et = T.tag_endpoint(text)
                    if kind == "primary":
                        prim_tags.append(et)
                    outcomes.append({"registry": "isrctn", "registry_id": rid, "outcome_kind": kind,
                                     "measure": text[:400], "time_frame": (_t(o, "i:timepoints") or "")[:200],
                                     "endpoint_tags": "|".join(et)})
            # older records keep outcomes as free text
            for kind, path in (("primary", "i:primaryOutcome"), ("secondary", "i:secondaryOutcome")):
                txt = _t(td, path)
                if txt:
                    et = T.tag_endpoint(txt)
                    if kind == "primary":
                        prim_tags.append(et)
                    outcomes.append({"registry": "isrctn", "registry_id": rid, "outcome_kind": kind,
                                     "measure": txt[:400], "time_frame": "", "endpoint_tags": "|".join(et)})

            ext = tr.find("i:externalRefs", NS)
            ids.append({"registry": "isrctn", "registry_id": rid, "other_id": rid, "id_type": "isrctn"})
            eud = _t(ext, "i:eudraCTNumber")
            if eud and re.fullmatch(r"\d{4}-\d{6}-\d{2}", eud):
                ids.append({"registry": "isrctn", "registry_id": rid, "other_id": eud, "id_type": "eudract"})
            nct = _t(ext, "i:clinicalTrialsGovNumber")
            if nct and re.fullmatch(r"NCT\d{8}", nct.upper()):
                ids.append({"registry": "isrctn", "registry_id": rid, "other_id": nct.upper(), "id_type": "nct"})

            design = tr.find("i:trialDesign", NS)
            itd = design.find("i:interventionalTrialDesign", NS)
            alloc = (_t(itd, "i:allocation") or "").lower() if itd is not None else ""
            mask = (_t(itd, "i:masking") or "").lower() if itd is not None else ""
            control = (_t(itd, "i:control") or "").lower() if itd is not None else ""
            status_override = _t(parts, "i:recruitmentStatusOverride")
            end = _date(_t(design, "i:overallEndDate"))
            rec_start = _date(_t(parts, "i:recruitmentStart"))
            results = tr.find("i:results", NS)
            pub_stage = _t(results, "i:publicationStage") if results is not None else None
            basic_report = results is not None and results.find("i:basicReport", NS) is not None and \
                bool((_t(results, "i:basicReport") or ""))
            outputs = tr.findall("i:outputs/i:output", NS)
            n_res = 0
            for out in outputs:
                ot = (out.get("outputType") or "").lower()
                ext_link = out.find("i:externalLink", NS)
                url = ext_link.get("url") if ext_link is not None else None
                pm = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)|/pubmed/(\d+)", url or "")
                if pm:
                    refs.append({"registry_id": rid, "pmid": pm.group(1) or pm.group(2), "ref_type": ot,
                                 "citation": (_t(out, "i:description") or "")[:400]})
                    if "result" in ot:
                        n_res += 1
            study_type = (_t(design, "i:primaryStudyDesign") or "").lower()

            trials.append({
                "registry": "isrctn", "registry_id": rid, "url": f"https://www.isrctn.com/{rid}",
                "title": title, "official_title": otitle, "acronym": _t(td, "i:acronym"), "org_study_id": None,
                "study_type": study_type, "phase": _phase(phases),
                # ISRCTN has no status field in the API; infer from dates
                "status": status_override.lower() if status_override else None,
                "why_stopped": None, "why_stopped_class": None,
                "start_date": rec_start, "primary_completion_date": None, "completion_date": end,
                "last_update": _date(tr.get("lastUpdated")),
                "enrollment": _int(_t(parts, "i:totalFinalEnrolment")) or _int(_t(parts, "i:targetEnrolment")),
                "enrollment_type": "actual" if _int(_t(parts, "i:totalFinalEnrolment")) else "anticipated",
                "allocation": "randomized" if "random" in alloc else ("non_randomized" if alloc else None),
                "intervention_model": None,
                "masking": "none" if "open" in mask else ("blinded" if "blind" in mask else None),
                "primary_purpose": None, "n_arms": None,
                "has_placebo_or_sham": "placebo" in control or "sham" in control or any(T.is_placebo(n) for n in iv_names),
                "lead_sponsor": None, "sponsor_class": None,
                "countries": "|".join(sorted(set(_all(parts, "i:recruitmentCountries/i:country")))),
                "n_countries": len(set(_all(parts, "i:recruitmentCountries/i:country"))),
                "min_age_years": min_age, "max_age_years": max_age,
                "conditions_raw": "|".join(conds),
                "diseases": "|".join(diseases), "ms_focus": focus, "tier": tier,
                "phenotypes": "|".join(phenos), "population_group": T.population_group(phenos, diseases),
                "primary_endpoint_class": T.primary_endpoint_class(prim_tags),
                "primary_endpoint_tags": "|".join(sorted({t for ts in prim_tags for t in ts})),
                "interventions_raw": "|".join(iv_names), "intervention_types": "|".join(sorted(iv_types - {""})),
                "mesh_interventions": "",
                "has_posted_results": bool(basic_report), "results_first_posted": None,
                "n_result_pmids": n_res, "_prim_ps": [],
                "_publication_stage": pub_stage,
            })
    return trials, ids, interventions, outcomes, refs


def _int(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None
