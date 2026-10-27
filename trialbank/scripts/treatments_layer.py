"""Treatments layer: every medicine approved for MS or NMOSD in the EU (EMA) or US (FDA), machine-assembled.

Sources (all public, fetched each run):
  * EMA "Medicines output" report (centrally authorised medicines, EU/EEA incl. the Nordics)
  * EMA DHPC report (safety letters to doctors) and referrals report
  * openFDA drug labels (indication text), Drugs@FDA (approval dates), FAERS (adverse-event report counts)
  * ChEMBL (mechanism, targets) via the existing chembl cache
Writes data/treatments.parquet, treatment_products.parquet, treatment_safety_signals.parquet,
treatment_adverse_event_reports.parquet, regulatory_events.parquet (+ CSV).
Usage: python treatments_layer.py
"""
import re
import time
from pathlib import Path

import pandas as pd
import requests

import chembl as C
import mechanisms as M

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "raw", ROOT / "data"
EMA = RAW / "ema"
EMA_BASE = "https://www.ema.europa.eu/en/documents/report/"
EMA_FILES = ["medicines-output-medicines-report_en.xlsx", "medicines-output-dhpc-report_en.xlsx",
             "medicines-output-referrals-report_en.xlsx"]
FDA = "https://api.fda.gov"
S = requests.Session()
DISEASE_RX = re.compile(r"multiple sclerosis|neuromyelitis optica|myelin oligodendrocyte", re.I)


def fetch_ema():
    EMA.mkdir(parents=True, exist_ok=True)
    for f in EMA_FILES:
        r = S.get(EMA_BASE + f, timeout=180)
        r.raise_for_status()
        (EMA / f).write_bytes(r.content)


def read_ema(name):
    raw = pd.read_excel(EMA / name, header=None)
    hdr = next(i for i in range(20) if raw.iloc[i].notna().sum() > 5)
    df = pd.read_excel(EMA / name, header=hdr)
    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
    return df


def fda_get(path, params):
    for attempt in range(4):
        try:
            r = S.get(f"{FDA}/{path}", params=params, timeout=60)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def fda_label_substances():
    """Single-substance generic names whose FDA label indication mentions MS, NMOSD or MOGAD."""
    out = {}
    for q in ['indications_and_usage:"multiple sclerosis"', 'indications_and_usage:"neuromyelitis optica"']:
        skip = 0
        while skip < 1000:
            d = fda_get("drug/label.json", {"search": q, "limit": 100, "skip": skip})
            if not d:
                break
            for x in d["results"]:
                of = x.get("openfda", {})
                ind = " ".join(x.get("indications_and_usage", []))
                for g in of.get("generic_name", []):
                    g = g.lower().strip()
                    if "," in g or " and " in g or "kit" in g:
                        continue
                    e = out.setdefault(g, {"brands": set(), "indication": ind[:600]})
                    e["brands"].update(of.get("brand_name", []))
            skip += 100
            if skip >= d["meta"]["results"]["total"]:
                break
    return out


def fda_approvals(name, ms_brands=None):
    """First FDA approval of the MS/NMOSD product(s). With ms_brands, only applications for those brands count,
    so e.g. alemtuzumab dates from Lemtrada (MS) rather than Campath (leukaemia)."""
    apps = {}
    for q in (f'openfda.generic_name:"{name}"', f'products.active_ingredients.name:"{name.upper()}"'):
        d = fda_get("drug/drugsfda.json", {"search": q, "limit": 100})
        for app in (d or {}).get("results", []):
            apps[app.get("application_number")] = app
    if not apps:
        return None
    wanted = {b.upper() for b in (ms_brands or [])}
    first, first_any, brands, n_generic = None, None, set(), 0
    for num, app in apps.items():
        app_brands = {p.get("brand_name", "").upper() for p in app.get("products", []) if p.get("brand_name")}
        if num.startswith("ANDA"):
            n_generic += 1
            continue
        relevant = not wanted or bool(app_brands & wanted)
        if relevant:
            brands.update(b.title() if b.isupper() else b for b in app_brands)
        for sub in app.get("submissions", []):
            if sub.get("submission_type") == "ORIG" and sub.get("submission_status") == "AP":
                dt = sub.get("submission_status_date")
                if not dt:
                    continue
                if first_any is None or dt < first_any:
                    first_any = dt
                if relevant and (first is None or dt < first):
                    first = dt
    if first is None:  # brand names in labels don't always match Drugs@FDA (e.g. generics only); fall back
        first = first_any
        brands = {b.title() if b.isupper() else b for num, app in apps.items() if not num.startswith("ANDA")
                  for b in (p.get("brand_name", "") for p in app.get("products", [])) if b}
    fmt = lambda x: f"{x[:4]}-{x[4:6]}-{x[6:]}" if x else None
    return {"fda_first_approval": fmt(first), "fda_first_approval_any_indication": fmt(first_any),
            "fda_brands": "|".join(sorted(brands)), "fda_generic_applications": n_generic}


def faers(names):
    """FAERS report counts across all names a substance goes by (generic or product name)."""
    terms = sorted({n for n in names if n})
    q = " OR ".join([f'patient.drug.openfda.generic_name:"{n}"' for n in terms] +
                    [f'patient.drug.medicinalproduct:"{n}"' for n in terms])
    q = f"({q})"
    tot = fda_get("drug/event.json", {"search": q, "limit": 1})
    total = tot["meta"]["results"]["total"] if tot else 0
    top = fda_get("drug/event.json", {"search": q, "count": "patient.reaction.reactionmeddrapt.exact", "limit": 10}) or {}
    serious = fda_get("drug/event.json", {"search": q + " AND serious:1", "limit": 1})
    return total, (serious["meta"]["results"]["total"] if serious else 0), top.get("results", [])


def canon(name):
    _, mol = C.best_match(name, CACHE)
    return mol


def main(fetch=True):
    global CACHE
    if fetch:
        fetch_ema()
    med = read_ema(EMA_FILES[0])
    med = med[med["Category"].astype(str).str.contains("Human", case=False)]
    area = med["Therapeutic area (MeSH)"].astype(str)
    ind = med["Therapeutic indication"].astype(str)
    ema_ms = med[area.str.contains("Multiple Sclerosis|Neuromyelitis", case=False) |
                 ind.str.contains(r"neuromyelitis optica spectrum|anti-aquaporin|myelin oligodendrocyte", case=False)]
    ema_ms = ema_ms[ema_ms["International non-proprietary name (INN) / common name"].notna()]

    fda_lab = fda_label_substances()
    CACHE = C.load_cache()
    names = set(ema_ms["International non-proprietary name (INN) / common name"].str.lower().str.strip()) | set(fda_lab)
    C.resolve(names)
    CACHE = C.load_cache()

    # group everything by ChEMBL parent molecule (falls back to the name)
    def key_for(n):
        mol = canon(n)
        return (mol["molecule_chembl_id"] if mol else f"name:{n}"), mol

    subs = {}
    for _, r in ema_ms.iterrows():
        inn = r["International non-proprietary name (INN) / common name"].lower().strip()
        k, mol = key_for(inn)
        s = subs.setdefault(k, {"mol": mol, "names": set(), "ema": [], "fda_label": None})
        s["names"].add(inn)
        s["ema"].append(r)
    for g, info in fda_lab.items():
        k, mol = key_for(g)
        if k not in subs:
            # FDA-label-only substances: keep only if the indication is about MS/NMOSD itself, not a list of conditions
            if not re.search(r"(relapsing|progressive) forms? of multiple sclerosis|multiple sclerosis \(MS\)|"
                             r"neuromyelitis optica spectrum|walking in (adult )?patients with multiple sclerosis|"
                             r"acute exacerbations of multiple sclerosis|spasticity resulting from multiple sclerosis",
                             info["indication"], re.I):
                continue
            subs[k] = {"mol": mol, "names": set(), "ema": [], "fda_label": None}
        subs[k]["names"].add(g)
        subs[k]["fda_label"] = info

    dhpc = read_ema(EMA_FILES[1])
    refs = read_ema(EMA_FILES[2])
    drugs_bank = pd.read_parquet(OUT / "drugs.parquet").set_index("chembl_id") if (OUT / "drugs.parquet").exists() else pd.DataFrame()

    t_rows, p_rows, sig_rows, ae_rows, ev_rows = [], [], [], [], []
    for k, s in subs.items():
        mol = s["mol"] or {}
        name = (mol.get("pref_name") or sorted(s["names"])[0]).lower()
        mechs = CACHE["mech"].get(mol.get("molecule_chembl_id"), []) if mol else []
        moa = "|".join(sorted({x["mechanism_of_action"] for x in mechs if x.get("mechanism_of_action")}))
        targets = "|".join(sorted({CACHE["targets"].get(x["target_chembl_id"], "") for x in mechs} - {""}))
        atc = [CACHE["atc"].get(c, {}) for c in (mol.get("atc_classifications") or [])]
        node_text = " ".join([name, moa, targets, " ".join(a.get("level3") or "" for a in atc)] + sorted(s["names"]))
        nodes = M.assign(node_text)
        fams = {f for _, f in nodes}
        node_ids = {n for n, _ in nodes}

        # disease and category, from regulators' own indication text
        texts = [str(r["Therapeutic indication"]) for r in s["ema"]] + [str(r["Therapeutic area (MeSH)"]) for r in s["ema"]]
        if s["fda_label"]:
            texts.append(s["fda_label"]["indication"])
        alltext = " ".join(texts).lower()
        diseases = [d for d, rx in (("ms", r"multiple sclerosis"), ("nmosd", r"neuromyelitis optica"),
                                    ("mogad", r"myelin oligodendrocyte")) if re.search(rx, alltext)]
        if "corticosteroid" in node_ids or re.search(r"acute exacerbation", alltext) and not (fams - {"immunomodulation"}) and "corticosteroid" in node_ids:
            category = "relapse_treatment"
        elif "symptomatic" in fams or re.search(r"walking|spasticity", alltext) and "immunomodulation" not in fams:
            category = "symptom_treatment"
        elif diseases == ["nmosd"] or (diseases and "ms" not in diseases):
            category = "nmosd_mogad_treatment"
        else:
            category = "disease_modifying"

        # EU
        auth = [r for r in s["ema"] if str(r["Medicine status"]).lower() == "authorised"]
        orig = [r for r in auth if str(r["Generic"]).lower() != "yes" and str(r["Biosimilar"]).lower() != "yes"]
        eu_dates = pd.to_datetime([r["Marketing authorisation date"] for r in auth], dayfirst=True, errors="coerce")
        eu_first = min(eu_dates).date().isoformat() if len(eu_dates) and pd.notna(min(eu_dates)) else None
        for r in s["ema"]:
            p_rows.append({
                "treatment_id": k, "region": "EU/EEA", "product_name": r["Name of medicine"],
                "status": str(r["Medicine status"]).lower(), "generic": str(r["Generic"]).lower() == "yes",
                "biosimilar": str(r["Biosimilar"]).lower() == "yes",
                "conditional_approval": str(r.get("Conditional approval")).lower() == "yes",
                "additional_monitoring": str(r.get("Additional monitoring")).lower() == "yes",
                "holder": r.get("Marketing authorisation developer / applicant / holder"),
                "authorisation_date": _d(r.get("Marketing authorisation date")),
                "refusal_date": _d(r.get("Refusal of marketing authorisation date")),
                "withdrawal_date": _d(r.get("Withdrawal / expiry / revocation / lapse of marketing authorisation date")),
                "indication": str(r.get("Therapeutic indication"))[:600],
                "url": r.get("Medicine URL"), "source": "EMA medicines report",
            })
            st = str(r["Medicine status"]).lower()
            if st in ("refused", "withdrawn", "suspended", "revoked", "application withdrawn"):
                ev_rows.append({"treatment_id": k, "substance": name, "region": "EU", "event": st,
                                "product_name": r["Name of medicine"],
                                "date": _d(r.get("Refusal of marketing authorisation date")) or
                                        _d(r.get("Withdrawal / expiry / revocation / lapse of marketing authorisation date")) or
                                        _d(r.get("Withdrawal of application date")),
                                "url": r.get("Medicine URL"), "source": "EMA medicines report"})
        # US
        ms_brands = sorted((s["fda_label"] or {}).get("brands", []))
        fda = fda_approvals(name, ms_brands) or (fda_approvals(sorted(s["names"])[0], ms_brands) if s["names"] else None) or {}
        if fda.get("fda_first_approval"):
            p_rows.append({"treatment_id": k, "region": "US", "product_name": fda.get("fda_brands"), "status": "approved",
                           "generic": False, "biosimilar": False, "conditional_approval": None, "additional_monitoring": None,
                           "holder": None, "authorisation_date": fda["fda_first_approval"], "refusal_date": None,
                           "withdrawal_date": None, "indication": (s["fda_label"] or {}).get("indication"),
                           "url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=BasicSearch.process&searchTerm={name.replace(' ', '%20')}",
                           "source": "Drugs@FDA / openFDA"})

        # safety letters and referrals (EMA)
        subst_rx = re.compile("|".join(r"\b" + re.escape(n) + r"\b" for n in sorted(s["names"] | {name})), re.I)
        for _, r in dhpc[dhpc["Active substances"].astype(str).str.contains(subst_rx)].iterrows():
            sig_rows.append({"treatment_id": k, "substance": name, "type": "EMA safety letter (DHPC)",
                             "title": str(r.get("Name of medicine")) + ": " + str(r.get("DHPC type")),
                             "date": _d(r.get("Dissemination date")), "url": r.get("DHPC URL"), "source": "EMA DHPC report"})
        inn_col = "International non-proprietary name (INN) / common name"
        for _, r in refs[refs[inn_col].astype(str).str.contains(subst_rx)].iterrows():
            sig_rows.append({"treatment_id": k, "substance": name,
                             "type": "EMA referral" + (" (safety)" if str(r.get("Safety referral?")).lower() == "yes" else ""),
                             "title": str(r.get("Referral name")), "date": _d(r.get("Procedure start date")),
                             "url": r.get("Referral URL"), "source": "EMA referrals report"})

        # FAERS
        total, serious, top = faers(s["names"] | {name})
        for x in top:
            ae_rows.append({"treatment_id": k, "substance": name, "reaction": x["term"].lower(), "reports": x["count"]})

        bank = drugs_bank.loc[mol["molecule_chembl_id"]] if mol and mol.get("molecule_chembl_id") in drugs_bank.index else None
        t_rows.append({
            "treatment_id": k, "name": name, "other_names": "|".join(sorted(s["names"] - {name})),
            "chembl_id": mol.get("molecule_chembl_id"), "molecule_type": mol.get("molecule_type"),
            "category": category, "diseases": "|".join(diseases),
            "mechanism_of_action": moa or None, "targets": targets or None,
            "mechanism_nodes": "|".join(sorted(node_ids)) or None, "mechanism_families": "|".join(sorted(fams)) or None,
            "eu_status": "authorised" if auth else (str(s["ema"][0]["Medicine status"]).lower() if s["ema"] else "not centrally authorised"),
            "eu_first_authorisation": eu_first,
            "eu_brands": "|".join(sorted({str(r["Name of medicine"]) for r in orig})) or None,
            "eu_generics_or_biosimilars": len(auth) - len(orig),
            "eu_additional_monitoring": any(str(r.get("Additional monitoring")).lower() == "yes" for r in auth),
            # Drugs@FDA dates applications, not indications: a brand added to an older application (e.g. Lemtrada
            # under Campath's licence) inherits the older date. Both dates are kept so readers can see this.
            "us_first_approval_ms_product": fda.get("fda_first_approval"),
            "us_first_approval_any_indication": fda.get("fda_first_approval_any_indication"),
            "us_brands": fda.get("fda_brands") or None,
            "us_generic_applications": fda.get("fda_generic_applications"),
            "n_ema_safety_letters": sum(1 for x in sig_rows if x["treatment_id"] == k and "DHPC" in x["type"]),
            "faers_reports": total, "faers_serious_reports": serious,
            "n_trials": int(bank.n_trials) if bank is not None else 0,
            "n_trials_as_comparator": int(bank.n_trials_as_comparator) if bank is not None else 0,
            "n_phase3_trials": int(bank.n_phase3) if bank is not None else 0,
            "availability_note": "Centrally authorised medicines are authorised in all EU/EEA countries, including "
                                 "Sweden, Denmark, Finland, Norway and Iceland; reimbursement is decided nationally."
                                 if auth else None,
            "assembled_by": "machine", "sources": "EMA medicines report; Drugs@FDA/openFDA; ChEMBL",
        })
        time.sleep(0.3)

    frames = {"treatments": pd.DataFrame(t_rows).sort_values(["category", "name"]),
              "treatment_products": pd.DataFrame(p_rows), "treatment_safety_signals": pd.DataFrame(sig_rows),
              "treatment_adverse_event_reports": pd.DataFrame(ae_rows), "regulatory_events": pd.DataFrame(ev_rows)}
    for n, df in frames.items():
        df.to_parquet(OUT / f"{n}.parquet", index=False)
        df.to_csv(OUT / f"{n}.csv", index=False)
    t = frames["treatments"]
    print(f"treatments: {len(t)}"); print(t.category.value_counts().to_dict())
    print(t[["name", "category", "diseases", "eu_status", "eu_first_authorisation", "us_first_approval_ms_product",
             "n_ema_safety_letters", "faers_reports", "n_trials"]].to_string(max_colwidth=28))


def _d(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v) in ("nan", "NaT", ""):
        return None
    x = pd.to_datetime(v, dayfirst=True, errors="coerce")
    return None if pd.isna(x) else x.date().isoformat()


if __name__ == "__main__":
    import sys
    main(fetch="--no-fetch" not in sys.argv)
