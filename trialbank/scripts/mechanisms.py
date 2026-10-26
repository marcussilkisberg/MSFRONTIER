"""MS mechanism map v0: nodes and the rules that assign drugs to them.

DRAFT for advisor review. A drug is matched on its ChEMBL preferred name, the raw
registry name, ChEMBL mechanism-of-action text, target names and ATC descriptions.
A drug can sit on several nodes (e.g. BTK inhibitors act on B cells and microglia).
"""
import re

NODES = [
    # id, family, label, regex
    # ---- relapse-era immunomodulation
    ("anti_cd20_b_cell", "immunomodulation", "B-cell depletion (anti-CD20)",
     r"\bcd20\b|b-lymphocyte antigen cd20|ocrelizumab|ofatumumab|ublituximab|rituximab|divozilimab"),
    ("other_b_cell_plasma_cell", "immunomodulation", "Other B-cell / plasma-cell targeting",
     r"\bcd19\b|inebilizumab|\bbaff\b|\bapril\b|atacicept|belimumab|tabalumab|tnfrsf13|\bcd38\b|\bbcma\b|tnfrsf17"),
    ("btk_inhibition", "immunomodulation", "BTK inhibition (B cells and microglia)",
     r"bruton|tyrosine-protein kinase btk|\bbtk\b|tolebrutinib|evobrutinib|fenebrutinib|remibrutinib|orelabrutinib"),
    ("s1p_receptor_modulation", "immunomodulation", "S1P receptor modulation (lymphocyte trafficking)",
     r"sphingosine[ -]1[ -]phosphate|\bs1p|fingolimod|siponimod|ozanimod|ponesimod|etrasimod|amiselimod|ceralifimod|mt-1303"),
    ("integrin_trafficking", "immunomodulation", "Integrin blockade (lymphocyte trafficking)",
     r"integrin alpha-4|\bvla-?4\b|natalizumab|vatelizumab|\bitga4|integrin alpha-2"),
    ("immune_reconstitution", "immunomodulation", "Immune reconstitution (cladribine, alemtuzumab, aHSCT)",
     r"\bcd52\b|alemtuzumab|cladribine|haematopoietic stem cell|hematopoietic stem cell|\bahsct\b|autologous stem cell transplant"),
    ("interferon_beta", "immunomodulation", "Interferon beta",
     r"interferon beta|interferon-beta|peginterferon beta|ifn-?beta|ifn-?b\b|interferon alpha/beta receptor"),
    ("glatiramer", "immunomodulation", "Glatiramer acetate", r"glatiramer|copaxone"),
    ("dhodh_pyrimidine", "immunomodulation", "DHODH inhibition (pyrimidine synthesis)",
     r"dihydroorotate|\bdhodh\b|teriflunomide|leflunomide|vidofludimus"),
    ("nrf2_fumarate", "immunomodulation", "Fumarates / NRF2",
     r"dimethyl fumarate|diroximel|monomethyl fumarate|fumaric acid ester|\bnrf2\b|tecfidera|vumerity|bafiertam|hydroxycarboxylic acid receptor"),
    ("complement", "immunomodulation", "Complement inhibition",
     r"complement|eculizumab|ravulizumab|\bc5\b|\bc1s?\b|zilucoplan"),
    ("il6_pathway", "immunomodulation", "IL-6 pathway", r"interleukin-6|\bil-?6\b|tocilizumab|satralizumab"),
    ("fcrn_igg", "immunomodulation", "FcRn / IgG reduction, IVIG, plasma exchange",
     r"\bfcrn\b|neonatal fc receptor|efgartigimod|rozanolixizumab|batoclimab|nipocalimab|immune globulin|intravenous immunoglobulin|human (normal )?immunoglobulin|\bivig\b|plasma ?exchange|plasmapheresis|immunoadsorption"),
    ("t_cell_costimulation", "immunomodulation", "T-cell co-stimulation / cytokine targeting",
     r"\bcd40\b|cd40 ligand|frexalimab|laquinimod|aryl hydrocarbon|interleukin-2|aldesleukin|\bcd28\b|\bctla-?4\b|abatacept|il-?17|secukinumab|il-?12|ustekinumab|il-?2\b|daclizumab|\bcd25\b|\bjak\b|janus kinase|tofacitinib"),
    ("corticosteroid", "immunomodulation", "Corticosteroids (relapse treatment)",
     r"glucocorticoid receptor agonist|methylprednisolone|prednisolone|prednisone|dexamethasone|corticotropin|\bacth\b|corticosteroid"),
    ("broad_immunosuppression", "immunomodulation", "Broad immunosuppression / cytotoxics",
     r"cyclophosphamide|mitoxantrone|pixantrone|azathioprine|hydroxychloroquine|methotrexate|mycophenol|cyclosporin|ciclosporin|tacrolimus|dna topoisomerase"),
    ("cell_therapy_tolerance", "immunomodulation", "Cell therapies and tolerisation",
     r"car-?t|chimeric antigen|mesenchymal|stromal cell|\btreg|regulatory t cell|tolerogenic|autoleucel|star-t|t[- ]cell therapy|dirucotide|plovamer|myelin basic protein|antigen-specific|atx-ms|nanoparticle.*myelin|ebv-specific|tabelecleucel|atai?188"),
    ("antiviral_ebv", "immunomodulation", "Antiviral / EBV-targeting",
     r"epstein|\bebv\b|famciclovir|acyclovir|aciclovir|valacyclovir|tenofovir|raltegravir|antiretroviral|temelimab|herv|ganciclovir"),
    # ---- progression biology
    ("remyelination", "progression_biology", "Remyelination / oligodendrocyte repair",
     r"lingo-?1|opicinumab|clemastine|muscarinic acetylcholine receptor m1|thyroid hormone receptor|liothyronine|sobetirome|"
     r"retinoid x receptor|bexarotene|gpr17|pipe-307|elezanumab|ozanezumab|\brgma\b|remyelinat|histamine h3|gsk239512|nogo"),
    ("mitochondrial_oxidative", "progression_biology", "Mitochondrial / oxidative stress",
     r"lipoic|thioctic|biotin|md1003|idebenone|coenzyme q|ubiquinol|ubidecarenone|acetylcysteine|cnm-au8|gold nanocrystal|"
     r"metformin|ampk|nicotinamide riboside|\bnad\+?|creatine|antioxidant|ursodeoxycholic|tauroursodeoxycholic"),
    ("microglia_innate", "progression_biology", "Microglia / innate immunity in the CNS",
     r"ibudilast|phosphodiesterase|masitinib|minocycline|\bcsf1r\b|\btrem2\b|nlrp3|inflammasome|ripk1|oditrasertib|imatinib"),
    ("axonal_neuroprotection", "progression_biology", "Axonal protection / ion channels / excitotoxicity",
     r"sodium channel|phenytoin|oxcarbazepine|lamotrigine|amiloride|acid-sensing|\basic1\b|riluzole|glutamate|fluoxetine|"
     r"erythropoietin|\bepo\b|neuroprotect|calcium channel|memantine|dronabinol"),
    ("vascular_lipid", "progression_biology", "Lipid / vascular (statins etc.)",
     r"hmg-coa reductase|simvastatin|atorvastatin|rosuvastatin|statin|ezetimibe|pcsk9"),
    ("hormonal", "progression_biology", "Sex hormones / hormonal",
     r"estriol|estradiol|oestr|testosterone|progest|nomegestrol|androgen receptor|estrogen receptor|prolactin|growth hormone"),
    ("nutritional_supplement", "lifestyle_supplement", "Vitamin D and nutritional supplements",
     r"vitamin d|cholecalciferol|ergocalciferol|calcitriol|alfacalcidol|omega-?3|fish oil|docosahexa|eicosapent|probiotic|"
     r"vitamin a|retinol|vitamin b12|cobalamin|vitamin e|tocopherol|zinc|magnesium|melatonin|curcumin|resveratrol|green tea|"
     r"epigallocatechin|lipoic"),
    ("imaging_tracer", "diagnostic", "Imaging tracers and contrast agents (not a treatment)",
     r"gado(butrol|teridol|terate|pentetate|benate|xetate)|gadolinium|ferumoxytol|dpa-714|pbr06|\btspo\b|translocator protein|"
     r"\[1[18]f?\]|\[c-11\]|\[f-18\]|radioligand|tracer|contrast"),
    # ---- symptomatic
    ("walking_k_channel", "symptomatic", "Walking (potassium-channel blockade)",
     r"fampridine|dalfampridine|4-aminopyridine|aminopyridine|potassium channel"),
    ("spasticity", "symptomatic", "Spasticity",
     r"baclofen|tizanidine|dantrolene|nabiximols|sativex|cannabi|tetrahydrocannabinol|cannabidiol|\bcb1\b|cannabinoid receptor|"
     r"botulinum|arbaclofen|vsn-16r|gaba-?b|diazepam|tolperisone|nabilone"),
    ("fatigue_wakefulness", "symptomatic", "Fatigue / wakefulness",
     r"amantadine|modafinil|armodafinil|methylphenidate|amphetamine|solriamfetol|pitolisant"),
    ("bladder", "symptomatic", "Bladder",
     r"silodosin|tamsulosin|alpha-1[a-d]? adrenergic|oxybutynin|tolterodine|solifenacin|trospium|darifenacin|fesoterodine|mirabegron|vibegron|desmopressin|onabotulinum|"
     r"muscarinic acetylcholine receptor m3|beta-3"),
    ("pain_mood_cognition", "symptomatic", "Pain, mood, cognition and other symptoms",
     r"gabapentin|pregabalin|crisugabalin|mirogabalin|alpha-2/delta|duloxetine|amitriptyline|nortriptyline|venlafaxine|sertraline|escitalopram|citalopram|"
     r"donepezil|rivastigmine|dextromethorphan|quinidine|sildenafil|tadalafil|naltrexone|lidocaine|ketamine|"
     r"serotonin transporter|acetylcholinesterase"),
]
_COMPILED = [(i, fam, lab, re.compile(rx, re.I)) for i, fam, lab, rx in NODES]
VERSION = "mechmap_v0_draft"


def assign(text):
    """Return list of (node_id, family) for a drug description string."""
    out = []
    for i, fam, _, rx in _COMPILED:
        if rx.search(text or ""):
            out.append((i, fam))
    return out


NONDRUG_CATEGORIES = [
    ("cell_or_transplant", r"stem cell|transplant|car-?t|mesenchymal|cell therapy"),
    ("neuromodulation_device", r"stimulation|\btms\b|\btdcs\b|\brtms\b|neuromodulat|electrical|vagus|ultrasound|laser|photobiomod|vibration"),
    ("exercise_rehabilitation", r"exercise|training|rehabilit|physiotherap|physical therap|yoga|pilates|aerobic|resistance|balance|gait|walking|treadmill|robot|aquatic|hippotherap|occupational therap"),
    ("cognitive_psychological", r"cognitive|psycholog|mindful|behavio|counsel|education|self-management|coaching|therapy session|\bcbt\b|acceptance|relaxation|hypnos|meditat"),
    ("diet_nutrition", r"diet|fasting|ketogenic|nutrition|food|meal|calori|supplement"),
    ("digital_health", r"app\b|digital|online|web-based|internet|telehealth|tele|virtual reality|\bvr\b|game|smartphone|software"),
]
_NONDRUG = [(c, re.compile(rx, re.I)) for c, rx in NONDRUG_CATEGORIES]


def nondrug_category(intervention_type, text):
    t = (intervention_type or "").lower()
    for c, rx in _NONDRUG:
        if rx.search(text or ""):
            return c
    return {"device": "device_other", "behavioral": "cognitive_psychological", "procedure": "procedure_other",
            "diagnostic_test": "diagnostic", "radiation": "procedure_other"}.get(t, "other")
