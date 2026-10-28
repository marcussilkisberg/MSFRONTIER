"""Articles of interest: collects MS news, patient-organisation posts, regulator announcements and new research papers,
writes a short summary of each from its title and teaser text, and links it to trials, medicines and hypotheses in the
bank. Runs daily (news.yml) and weekly (trialbank.yml).

- Every item keeps the source's link; only the title, the source's own teaser and our summary are stored.
- Summaries are written by machine from the title and teaser only. Every number in a summary must appear in the
  source text, or the summary is dropped.
- An item is published when the machine judges it to be about MS (or NMOSD/MOGAD) and of interest (relevance >= 3).
- The full history is kept in ../news/items.json (committed to the repository).
Env: SUPABASE_DB_URL (load), ANTHROPIC_API_KEY (summaries; without it items are collected but not published).
Usage: python news_layer.py
"""
import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "news" / "items.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; MSFrontierBot/0.1; open MS research data)"}
MODEL = os.environ.get("NEWS_MODEL", "claude-sonnet-5-5")
MAX_NEW_SUMMARIES = int(os.environ.get("NEWS_MAX_SUMMARIES", "120"))
API = "https://api.anthropic.com/v1/messages"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
MS_RX = re.compile(r"multiple sclerosis|\bMS\b|neuromyelitis|\bNMOSD\b|\bMOGAD\b|MOG antibod|optic neuritis|"
                   r"demyelinat|remyelinat|myelin", re.I)

# name, url, type, filter: "all" = every item is MS-related; "ms" = keep items that mention MS terms
FEEDS = [
    ("MS News Today", "https://multiplesclerosisnewstoday.com/feed/", "news", "all"),
    ("NeurologyLive", "https://www.neurologylive.com/rss", "news", "ms"),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/health_medicine/multiple_sclerosis.xml", "research_news", "ms"),
    ("Nature", "https://www.nature.com/subjects/multiple-sclerosis.rss", "research_news", "all"),
    ("MS Trust", "https://mstrust.org.uk/rss.xml", "patient_org", "all"),
    ("EMA", "https://www.ema.europa.eu/en/news.xml", "regulator", "ms"),
    ("FDA", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
     "regulator", "ms"),
]
JOURNALS = ["lancet neurol", "lancet", "n engl j med", "jama neurol", "jama", "brain", "ann neurol", "neurology",
            "mult scler", "nat med", "neurol neuroimmunol neuroinflamm", "j neurol neurosurg psychiatry", "bmj",
            "nat rev neurol", "mult scler relat disord"]

PROMPT = """You write short entries for a news list read by people with multiple sclerosis and their clinicians.

Source: {source}
Title: {title}
Text from the source: {text}

Reply with JSON only:
{{"about_ms": true/false,      // is it mainly about MS, NMOSD, MOGAD or related demyelinating disease?
  "relevance": 1-5,             // 5 = important new evidence or decision; 3 = useful; 1 = marginal or promotional
  "category": "research|treatment|regulatory|trial_news|living_with_ms|other",
  "summary": "..."}}            // 1-2 plain sentences, at most 45 words, only facts stated above; no advice,
                                // no hype words, no claims beyond the text; say "in mice" or "in a lab study" when so"""


def h(s):
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def strip(s, n=700):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


def when(s):
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except ValueError:
            return None


def get(url, tries=3, **kw):
    for k in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=40, **kw)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    return None


def collect_feeds():
    out = []
    atom = "{http://www.w3.org/2005/Atom}"
    for name, url, typ, flt in FEEDS:
        r = get(url)
        if r is None:
            print(f"feed unavailable: {name}")
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            print(f"feed unreadable: {name}")
            continue
        items = root.findall(".//item") or root.findall(f".//{atom}entry")
        n = 0
        for it in items:
            title = strip(it.findtext("title") or it.findtext(f"{atom}title"), 300)
            link = (it.findtext("link") or "").strip()
            if not link:
                le = it.find(f"{atom}link")
                link = le.get("href") if le is not None else ""
            desc = strip(it.findtext("description") or it.findtext(f"{atom}summary") or it.findtext(f"{atom}content"))
            pub = when(it.findtext("pubDate") or it.findtext(f"{atom}updated") or it.findtext(f"{atom}published")
                       or it.findtext("{http://purl.org/dc/elements/1.1/}date"))
            if not title or not link:
                continue
            if flt == "ms" and not MS_RX.search(f"{title} {desc}"):
                continue
            out.append({"id": h(link), "source": name, "source_type": typ, "title": title, "link": link,
                        "published_at": pub, "description": desc})
            n += 1
        print(f"feed {name}: {n} items kept")
    return out


def collect_papers(days=14):
    """New MS papers of the kinds that change practice: randomised trials, meta-analyses, systematic reviews and
    guidelines in major journals."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = ('(TITLE:"multiple sclerosis" OR TITLE:"neuromyelitis" OR TITLE:"MOGAD" OR TITLE:"NMOSD") AND '
         '(PUB_TYPE:"randomized controlled trial" OR PUB_TYPE:"meta-analysis" OR PUB_TYPE:"systematic review" OR '
         'PUB_TYPE:"practice guideline" OR PUB_TYPE:"guideline" OR PUB_TYPE:"clinical trial, phase iii") AND '
         f'FIRST_PDATE:[{since} TO 3000-01-01] AND SRC:MED')
    r = get(EPMC, params={"query": q, "format": "json", "resultType": "core", "pageSize": 100})
    out = []
    if r is None:
        print("Europe PMC unavailable")
        return out
    for p in r.json().get("resultList", {}).get("result", []):
        journal = ((p.get("journalInfo") or {}).get("journal") or {}).get("medlineAbbreviation") or ""
        types = [t.lower() for t in (p.get("pubTypeList") or {}).get("pubType", [])]
        major = journal.lower() in JOURNALS
        if not major and not any(t in types for t in ("randomized controlled trial", "meta-analysis",
                                                      "practice guideline", "guideline")):
            continue
        pmid = p.get("pmid")
        link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else f"https://doi.org/{p.get('doi')}"
        out.append({"id": h(link), "source": journal or "Europe PMC", "source_type": "paper",
                    "title": strip(p.get("title"), 300), "link": link,
                    "published_at": when(p.get("firstPublicationDate")),
                    "description": strip(p.get("abstractText"), 1500), "journal": journal, "pmid": pmid,
                    "doi": p.get("doi"), "pub_types": types})
    print(f"papers: {len(out)} kept")
    return out


NUM = re.compile(r"\d+(?:[.,·]\d+)?%?")


def numbers_ok(summary, source_text):
    """Every number in the summary must appear in the source text."""
    src = {n.replace("·", ".").replace(",", ".") for n in NUM.findall(source_text)}
    return all(n.replace("·", ".").replace(",", ".") in src for n in NUM.findall(summary))


def summarise(item):
    key = os.environ["ANTHROPIC_API_KEY"]
    prompt = PROMPT.format(source=item["source"], title=item["title"], text=item.get("description") or "(none)")
    for k in range(4):
        r = requests.post(API, timeout=90, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                                   "content-type": "application/json"},
                          json={"model": MODEL, "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]})
        if r.status_code == 200:
            text = "".join(b.get("text", "") for b in r.json()["content"])
            m = re.search(r"\{.*\}", re.sub(r"//[^\n]*", "", text), re.S)
            try:
                return json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                return None
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(5 * (k + 1))
            continue
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:200]}")
    return None


def main():
    STORE.parent.mkdir(exist_ok=True)
    store = json.loads(STORE.read_text()) if STORE.exists() else {}
    fresh = collect_feeds() + collect_papers()
    for it in fresh:
        if it["id"] not in store:
            store[it["id"]] = {**it, "collected_at": datetime.now(timezone.utc).isoformat()}

    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    n = 0
    for it in sorted(store.values(), key=lambda x: x.get("published_at") or "", reverse=True):
        if "summary_model" in it or not have_key or n >= MAX_NEW_SUMMARIES:
            continue
        try:
            j = summarise(it)
        except RuntimeError as e:
            print("stopping summaries:", e)
            break
        n += 1
        source_text = f"{it['title']} {it.get('description') or ''}"
        summary = (j or {}).get("summary") or ""
        ok = bool(summary) and numbers_ok(summary, source_text)
        rel = (j or {}).get("relevance")
        it.update({
            "summary": summary if ok else None,
            "summary_model": MODEL,
            "category": (j or {}).get("category"),
            "relevance": int(rel) if isinstance(rel, (int, float)) or str(rel).isdigit() else None,
            "about_ms": bool((j or {}).get("about_ms")),
        })
        it["is_published"] = bool(it["about_ms"] and ok and (it["relevance"] or 0) >= 3)
    STORE.write_text(json.dumps(store, indent=1, sort_keys=True, ensure_ascii=False))
    pub = sum(1 for v in store.values() if v.get("is_published"))
    print(f"news: {len(fresh)} fetched, {len(store)} stored, {n} summarised this run, {pub} published")

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL not set: not loaded")
        return
    import psycopg
    cols = ["id", "source", "source_type", "title", "link", "published_at", "description", "summary",
            "summary_model", "category", "relevance", "is_published", "journal", "pmid", "doi", "pub_types",
            "collected_at"]
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("select to_regclass('bank.news_items') is not null")
        if not cur.fetchone()[0]:
            print("migration 008 not applied: not loaded")
            return
        for v in store.values():
            row = [v.get(c) for c in cols]
            row[cols.index("is_published")] = bool(v.get("is_published"))
            cur.execute(f"""insert into bank.news_items ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})
                            on conflict (id) do update set {', '.join(f'{c} = excluded.{c}' for c in cols[1:])}""", row)
        cur.execute("select bank.link_news()")
        conn.commit()
    print("news loaded and linked")


if __name__ == "__main__":
    main()
