"""Rule-based tagging shared by every registry parser. Version: rules_v0.

Every tag function returns plain values; the method label for all of them is
TAG_METHOD, so downstream users can tell rule tags from reviewed ones.
"""
import re

TAG_METHOD = "rules_v0"

def _rx(p):
    return re.compile(p, re.I)

# ---------------------------------------------------------------- disease
DISEASE_RULES = [
    ("ms", _rx(r"multiple\s+sclerosis|sclerosis,\s*multiple|clinically\s+isolated\s+syndrome|radiologically\s+isolated|"
              r"\b(rr|sp|pp|r)ms\b|\bcis\b|ms[- ]related|esclerosis\s+m[uú]ltiple|scl[ée]rose\s+en\s+plaques|"
              r"multipler?\s+sklerose|sclerosi\s+multipla|demyelinating\s+diseases?\s+of\s+the\s+(cns|central)|cns\s+demyelinat|"
              r"central\s+nervous\s+system\s+demyelinat|^ms$|\bms\s*\(|\(ms\)")),
    ("nmosd", _rx(r"neuromyelitis\s+optica|\bnmosd\b|\bnmo\b|devic|aquaporin|\baqp-?4\b")),
    ("mogad", _rx(r"\bmog\b|mogad|myelin\s+oligodendrocyte\s+glycoprotein")),
    ("optic_neuritis", _rx(r"optic\s+neuritis")),
    ("adem", _rx(r"acute\s+disseminated\s+encephalomyelitis|\badem\b")),
    ("transverse_myelitis", _rx(r"transverse\s+myelitis")),
]
# Standalone "MS" in a condition field (not in free titles, where it is ambiguous)
MS_ABBR = _rx(r"^\s*(m\.?s\.?|pwms|pwm?s)\s*$|\bMS\b")
TIER1 = {"ms", "nmosd", "mogad"}
CNS_DEMYELINATING_OTHER = {"optic_neuritis", "adem", "transverse_myelitis"}


def classify_diseases(conditions, keywords, title, official_title):
    """Return (diseases sorted, ms_focus) where ms_focus is 'primary' or 'mixed'."""
    found = set()
    primary_texts = list(conditions) + [title or "", official_title or ""]
    for name, rx in DISEASE_RULES:
        if any(rx.search(t) for t in primary_texts):
            found.add(name)
    for c in list(conditions) + [title or ""]:
        if re.search(r"\bMS\b", c) and not re.search(r"\bMS/MS\b|mass spec", c, re.I):
            found.add("ms")
    # another named disease in the condition list marks the population as mixed
    other = [c for c in conditions if _OTHER_DISEASE.search(c) and not any(rx.search(c) for _, rx in DISEASE_RULES)]
    # keywords alone only count when the condition list names no other disease
    # (otherwise e.g. a fingolimod asthma study tagged "multiple sclerosis" leaks in)
    if not found and not other:
        for name, rx in DISEASE_RULES:
            if any(rx.search(k) for k in keywords):
                found.add(name)
    # peripheral demyelinating disease is out of scope even if CNS terms appear
    if found and all(re.search(r"cidp|polyneuropath|polyradiculo|guillain|peripheral", c, re.I) for c in conditions if c) \
            and not re.search(r"multiple sclerosis|neuromyelitis|\bMS\b", " ".join(primary_texts)):
        found = set()
    focus = "mixed" if other else "primary"
    return sorted(found), focus


_OTHER_DISEASE = _rx(r"stroke|parkinson|spinal cord injur|cerebral palsy|amyotrophic|\bals\b|alzheimer|dementia|brain injur|"
                     r"\btbi\b|epilep|muscular dystroph|myasthen|rheumatoid|lupus|psoria|crohn|colitis|inflammatory bowel|"
                     r"cancer|tumou?r|leuka?emia|lymphoma|myeloma|diabet|huntington|guillain|\bcidp\b|polyneuropath|"
                     r"polyradiculo|migraine|\bhiv\b|spina bifida|amputat|arthritis|charcot-marie|neuromuscular disease|"
                     r"sarcoidosis|uveitis|sj[oö]gren|vasculitis|behcet|myositis|hemophilia|sickle|thalass|leukodystroph|"
                     r"tuberous|systemic sclerosis|scleroderma|essential tremor|dystonia|glaucoma|macular|retinitis|"
                     r"autism|schizophren|bipolar|healthy volunteer|covid|chronic fatigue syndrome|fibromyalgia|obesity|"
                     r"heart failure|copd|asthma|kidney|renal|transplant|graft")


# Symptom / generic condition words that do not make a population mixed
_GENERIC_COND = _rx(r"fatigue|spastic|pain|bladder|urinary|bowel|incontinen|gait|walking|cognit|depress|anxiety|sleep|"
                    r"insomnia|tremor|ataxia|dysphagia|balance|mobility|quality of life|relapse|demyelinat|autoimmun|"
                    r"neuroinflam|inflamma|healthy|vaccin|influenza|covid|sars-cov|optic|visual|vision|rehabilit|"
                    r"neurolog|nervous system|disabilit|exercise|obesity|vitamin d|lymphopenia|immunosuppress|leukoenceph|"
                    r"sexual|erectile|nocturia|overactive|constipation|weakness|numbness|paresthes|pseudobulbar|nystagmus")


def tier_for(diseases, ms_focus):
    if TIER1 & set(diseases):
        return 1
    if CNS_DEMYELINATING_OTHER & set(diseases):
        return 2
    return None  # out of scope for v0


# ---------------------------------------------------------------- phenotype
PHENOTYPES = [
    ("ris", _rx(r"radiologically\s+isolated|\bris\b")),
    ("cis", _rx(r"clinically\s+isolated|\bcis\b|first\s+demyelinating\s+event|first\s+clinical\s+(demyelinating\s+)?event")),
    ("rrms", _rx(r"relapsing[- ]?remitting|\brrms\b|\brr[- ]ms\b")),
    ("relapsing_ms", _rx(r"relapsing\s+(forms?\s+of\s+)?(multiple\s+sclerosis|ms)|\brms\b|relapsing\s+ms|active\s+relapsing")),
    ("spms", _rx(r"secondary[- ]?progressive|\bspms\b|\bsp[- ]ms\b")),
    ("ppms", _rx(r"primary[- ]?progressive|\bppms\b|\bpp[- ]ms\b")),
    ("progressive_ms", _rx(r"progressive\s+(forms?\s+of\s+)?(multiple\s+sclerosis|ms)|chronic\s+progressive|progressive\s+relapsing")),
    ("healthy_volunteers", _rx(r"healthy (subjects|volunteers|participants|adults)")),
]
PAEDIATRIC = _rx(r"p(a)?ediatric|\bchildren\b|\bchild\b(?!-?bearing)|adolescen|juvenile")


def split_inclusion(elig_text):
    """Inclusion part of an eligibility text (exclusion criteria often name phenotypes to exclude)."""
    if not elig_text:
        return ""
    m = re.search(r"exclusion\s+criteria|key\s+exclusion|exclusion:", elig_text, re.I)
    return elig_text[: m.start()] if m else elig_text


def tag_phenotypes(texts, max_age_years=None, min_age_years=None):
    tags = set()
    for name, rx in PHENOTYPES:
        if any(rx.search(t or "") for t in texts):
            tags.add(name)
    # paediatric: from age limits or the first texts (conditions/titles), never from free inclusion text,
    # where "child-bearing potential" and similar phrases are common
    if max_age_years is not None and max_age_years < 18:
        tags.add("paediatric")
    elif any(PAEDIATRIC.search(t or "") for t in texts[:-1]):
        tags.add("paediatric")
    if "spms" in tags or "ppms" in tags:
        tags.add("progressive_ms")
    return sorted(tags)


def population_group(phenos, diseases):
    """One coarse label for filtering: relapsing / progressive / mixed / early / unspecified."""
    if "ms" not in diseases:
        for d in ("nmosd", "mogad", "optic_neuritis", "adem", "transverse_myelitis"):
            if d in diseases:
                return d
        return "other"
    p = set(phenos)
    rel = bool(p & {"rrms", "relapsing_ms"})
    prog = bool(p & {"spms", "ppms", "progressive_ms"})
    early = bool(p & {"cis", "ris"})
    if rel and prog:
        return "relapsing_and_progressive"
    if prog:
        return "progressive"
    if rel:
        return "relapsing"
    if early:
        return "early_cis_ris"
    return "unspecified"


# ---------------------------------------------------------------- endpoints
ENDPOINTS = [
    ("disability_progression", _rx(r"\bedss\b|expanded disability|disability (progression|worsening|accumulation)|"
                                   r"confirmed disability|\bcd[pw]\b|\bpira\b|time to (confirmed )?(disability )?progression|"
                                   r"\bmsfc\b|t25fw|timed 25|9[- ]?hole peg|\b9hpt\b|composite.*(disability|progression)|"
                                   r"progression independent")),
    ("relapse", _rx(r"relapse|annuali[sz]ed relapse|\barr\b|\battacks?\b|time to first (attack|relapse)")),
    ("mri_lesions", _rx(r"lesion|gadolinium|\bgd[+-]?\b|enhancing|\bt2\b|\bt1\b|new or enlarging|\bcuals?\b|combined unique active|\bmri\b|"
                        r"magnetic resonance|diffusion|fractional anisotropy|\bdti\b")),
    ("brain_atrophy", _rx(r"atrophy|brain volume|\bpbvc\b|\bsiena\b|whole[- ]brain|gr[ae]y matter volume|cord (area|volume)|"
                          r"thalamic volume|brain parenchymal fraction|\bbpf\b")),
    ("smouldering_inflammation", _rx(r"paramagnetic rim|rim lesion|slowly expanding|\bsel\b|\bprl\b|\btspo\b|microglia|chronic active")),
    ("fluid_biomarker", _rx(r"neurofilament|\bnf-?l\b|\bgfap\b|biomarker|cerebrospinal fluid|\bcsf\b")),
    ("remyelination", _rx(r"remyelinat|magneti[sz]ation transfer|\bmtr\b|myelin water|evoked potential|\bm?vep\b|"
                          r"latency|myelin (content|imaging|pet)")),
    ("retina_oct", _rx(r"optical coherence|\boct\b|\brnfl\b|\bgcipl\b|retinal nerve fib|ganglion cell")),
    ("vision", _rx(r"visual acuity|low[- ]contrast|vision|visual function")),
    ("cognition", _rx(r"cogniti|\bsdmt\b|symbol digit|\bpasat\b|memory|\bbicams\b|processing speed|attention")),
    ("fatigue", _rx(r"fatigue|\bmfis\b|\bfss\b")),
    ("walking_mobility", _rx(r"walk|gait|mobility|\bmsws|6[- ]?minute|\b6mwt?\b|timed up and go|\btug\b|balance|falls?\b")),
    ("upper_limb", _rx(r"upper (limb|extremit)|hand function|dexterity|arm function|\barat\b|action research arm|motor activity log|grip")),
    ("physical_function", _rx(r"exercise|physical activity|steps per day|sedentary|muscle (strength|power|endurance)|isokinetic|"
                              r"inspiratory|respiratory muscle|fitness|vo2|aerobic|strength|motricity|ataxia|tremor|kinesiophobia|body composition|fat mass")),
    ("neurophysiology", _rx(r"\beeg\b|neurophysiolog|cortical (activity|excitability)|\btms\b|motor evoked|\bmeps?\b|saccad|eye movement|connectivity|\bfmri\b")),
    ("spasticity", _rx(r"spastic|ashworth|spasm")),
    ("bladder_bowel_sexual", _rx(r"bladder|urinary|bowel|incontinen|overactive|nocturia|void|constipation|sexual|erectile")),
    ("pain", _rx(r"\bpain\b|neuropathic|trigeminal")),
    ("mood_sleep", _rx(r"depress|anxiety|\bmood\b|sleep|insomnia|\bhads\b|\bbdi\b")),
    ("quality_of_life_pro", _rx(r"quality of life|\bqol\b|msqol|\bmsis\b|eq-?5d|sf-?36|patient[- ]reported|\bproms?\b|"
                                r"satisfaction|adherence")),
    ("immune_response", _rx(r"antibody (response|titer|titre)|seroprotect|seroconver|immunogenicity|vaccine response|"
                            r"b[- ]cell|lymphocyte|immune (cell|response)|cd\d+|interleukin|\bil-?\d+|cytokine|interferon|neutrali[sz]ing antibod|"
                            r"anti-drug antibod|\bada\b|seroresponders|vaccine responders|\bmxa\b|mrna|gene expression|\bebv\b|epstein")),
    ("pharmacokinetics", _rx(r"pharmacokinetic|\bpk\b|\bcmax\b|\bauc\b|plasma concentration|serum concentration|bioavailab|half[- ]life|"
                             r"trough|\bctrough\b|steady state|clearance")),
    ("safety_tolerability", _rx(r"adverse (event|effect|reaction)|\bteaes?\b|\bsaes?\b|safety|tolerab|laboratory abnormalit|vital sign|"
                                r"injection[- ]site|infusion[- ]related|flu-like|\bdlts?\b|dose[- ]limiting|side effect")),
    ("feasibility", _rx(r"feasibil|recruitment rate|retention|acceptability")),
]
# priority when we need one "primary endpoint class" per trial
ENDPOINT_PRIORITY = [e for e, _ in ENDPOINTS]


def tag_endpoint(text):
    return [name for name, rx in ENDPOINTS if rx.search(text or "")]


def primary_endpoint_class(tags_per_outcome):
    flat = {t for tags in tags_per_outcome for t in tags}
    for e in ENDPOINT_PRIORITY:
        if e in flat:
            return e
    return "other" if tags_per_outcome else None


# ---------------------------------------------------------------- results / stopping
WHY_STOPPED = [
    ("futility_or_efficacy", _rx(r"futil|lack of (efficacy|effect)|efficacy|did not meet|no benefit|interim analysis|endpoint")),
    ("safety", _rx(r"safety|adverse|toxicit|death|risk")),
    ("business_or_sponsor", _rx(r"business|sponsor|strategic|portfolio|commercial|company|fund|financ|budget|priorit|acquisition|license")),
    ("enrolment", _rx(r"enrol|enroll|recruit|accrual|participants")),
    ("covid", _rx(r"covid|pandemic|coronavirus")),
    ("regulatory_or_supply", _rx(r"regulator|fda|ema|supply|manufactur|drug availability")),
    ("investigator_or_site", _rx(r"investigator|\bpi\b|site|staff|left the institution|relocat")),
]


def why_stopped_class(text):
    if not text:
        return None
    for name, rx in WHY_STOPPED:
        if rx.search(text):
            return name
    return "other"


def parse_p(pstr):
    """'< 0.0001' -> (0.0001, '<'); '0.23' -> (0.23, '='); unparseable -> (None, None)."""
    if not pstr:
        return None, None
    s = pstr.strip().replace(",", ".")
    m = re.search(r"(<=|>=|<|>|=|≤|≥)?\s*([0-9]*\.?[0-9]+(?:e-?\d+)?)", s, re.I)
    if not m:
        return None, None
    op = m.group(1) or "="
    try:
        return float(m.group(2)), op
    except ValueError:
        return None, None


# ---------------------------------------------------------------- comparators
PLACEBO = _rx(r"placebo|sham|vehicle|dummy|matching tablet|normal saline|saline (control|infusion)")


def is_placebo(name):
    return bool(PLACEBO.search(name or ""))
