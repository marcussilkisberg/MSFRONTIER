"""Weekly newsletter: builds a digest of the past week from the bank and sends it through Buttondown.

Runs after the weekly load. Everything in it comes from the bank (weekly_changes, news_items, trials_current), so the
newsletter says nothing the site does not already say.

Environment
  SUPABASE_DB_URL      Postgres connection string (GitHub secret)
  BUTTONDOWN_API_KEY   Buttondown API key (GitHub secret)
  NEWSLETTER_MODE      send | draft | off   (default: draft; the workflow passes send on the weekly schedule)
  SITE_URL             public address of the site, e.g. https://msfrontier.org

Usage: python newsletter.py [--dry-run]     --dry-run prints the email instead of sending it
"""
import os
import sys
from datetime import date, timedelta
from urllib.parse import quote

import psycopg
import requests

SITE = (os.environ.get("SITE_URL") or "https://msfrontier.org").rstrip("/")
MODE = (os.environ.get("NEWSLETTER_MODE") or "draft").strip().lower()
DRY = "--dry-run" in sys.argv
API = "https://api.buttondown.com/v1/emails"

OUTCOME = {"roadmap": "Proposed", "testing": "Being tested", "pending": "Results pending", "promising": "Promising",
           "confirmed": "Confirmed", "mixed": "Mixed", "failed_early": "Failed early", "disproven": "Disproven",
           "unclear": "No clear answer"}
READOUT = {"met": "met its main goal", "not_met": "did not meet its main goal", "mixed": "had mixed results"}
STATUS = {"completed": "finished", "terminated": "was stopped early", "withdrawn": "was withdrawn before it started",
          "suspended": "was paused", "recruiting": "started recruiting"}
CATEGORY = {"research": "Research", "treatment": "Treatments", "trial_news": "Trials", "regulatory": "Regulatory",
            "living_with_ms": "Living with MS"}


def trial_link(tid, name):
    return f"[{name}]({SITE}/research/trials/{tid})" if tid else name


def fetch(cur, sql, args=()):
    cur.execute(sql, args)
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def gather(cur):
    ch = fetch(cur, """select kind, msf_trial_id, hypothesis_id, treatment_id, name, old_value, new_value, link
                       from bank.weekly_changes where changed_at >= now() - interval '8 days'
                       order by changed_at desc""")
    stories = fetch(cur, """select title, link, source, summary, category from bank.news_items
                            where is_published and published_at >= now() - interval '8 days'
                            order by relevance desc nulls last, published_at desc limit 5""")
    soon = fetch(cur, """select msf_trial_id, coalesce(acronym, title) as name, primary_completion_date as due,
                                array_to_string(drugs, ', ') as drugs
                         from bank.trials_current
                         where in_scope and primary_completion_date between current_date and current_date + 60
                           and ('phase3' = any(phase))
                           and status in ('recruiting', 'active_not_recruiting', 'enrolling_by_invitation', 'ongoing',
                                          'ongoing_inferred')
                         order by primary_completion_date limit 6""")
    return ch, stories, soon


def build(ch, stories, soon):
    by = {}
    for c in ch:
        by.setdefault(c["kind"], []).append(c)
    papers = by.get("paper_result", [])
    posted = by.get("results_posted", [])
    new = by.get("new_trial", [])
    new_big = [c for c in new if any(p in (c.get("new_value") or "") for p in ("phase2", "phase3"))]
    hyp = by.get("hypothesis_status", [])
    reg = by.get("regulatory", []) + by.get("safety_letter", [])
    status = [c for c in by.get("trial_status", []) if c.get("new_value") in STATUS]

    if not (papers or posted or hyp or reg or stories or new_big):
        return None, None

    n_res = len(papers) + len(posted)
    bits = []
    if n_res:
        bits.append(f"{n_res} new result{'s' if n_res != 1 else ''}")
    if new:
        bits.append(f"{len(new)} new trial{'s' if len(new) != 1 else ''}")
    if reg:
        bits.append(f"{len(reg)} regulatory update{'s' if len(reg) != 1 else ''}")
    if not bits:
        bits.append(f"{len(stories)} stor{'ies' if len(stories) != 1 else 'y'}")
    today = date.today()
    subject = f"MSFrontier weekly, {today.day} {today:%B %Y}: {', '.join(bits)}"

    out = [f"This is what changed in MS research this week, collected from trial registries, regulators and published "
           f"papers. Every line links to its source on [MSFrontier]({SITE}).", ""]

    if papers or posted:
        out += ["## Results", ""]
        for c in papers:
            out.append(f"- {trial_link(c['msf_trial_id'], c['name'])} {READOUT.get(c['new_value'], 'reported a result')}, "
                       f"according to a published paper read by software. [Paper]({c['link']})")
        for c in posted:
            out.append(f"- {trial_link(c['msf_trial_id'], c['name'])} posted its results on its registry.")
        out.append("")

    if hyp:
        out += ["## Hypotheses that changed status", ""]
        for c in hyp[:8]:
            url = f"{SITE}/research/hypotheses/{quote(c['hypothesis_id'], safe='')}"
            out.append(f"- [{c['name']}]({url}): now **{OUTCOME.get(c['new_value'], c['new_value'])}** "
                       f"(was {OUTCOME.get(c['old_value'], c['old_value'])})")
        out.append("")

    if reg:
        out += ["## Regulators", ""]
        for c in reg[:8]:
            what = c.get("new_value") or ""
            where = f" ({c['old_value']})" if c.get("old_value") else ""
            link = f" [Source]({c['link']})" if c.get("link") else ""
            out.append(f"- **{c['name']}**{where}: {what}.{link}")
        out.append("")

    if stories:
        out += ["## In the news", ""]
        for s in stories:
            cat = CATEGORY.get(s.get("category") or "", "")
            lead = f"{cat} · " if cat else ""
            out.append(f"- {lead}**[{s['title']}]({s['link']})** ({s['source']})")
            if s.get("summary"):
                out.append(f"  {s['summary']}")
        out += ["", "_News summaries are written by software from each source's headline and teaser._", ""]

    if new_big or status:
        out += ["## Trials", ""]
        for c in new_big[:8]:
            ph = (c.get("new_value") or "").replace("phase", "phase ").replace("/", " and ")
            out.append(f"- New {ph} trial: {trial_link(c['msf_trial_id'], c['name'])}")
        if len(new) > len(new_big[:8]):
            k = len(new) - len(new_big[:8])
            out.append(f"- {k} other new trial{'s' if k != 1 else ''}. [All new trials]({SITE}/news?tab=changes)")
        for c in status[:8]:
            out.append(f"- {trial_link(c['msf_trial_id'], c['name'])} {STATUS[c['new_value']]}.")
        out.append("")

    if soon:
        out += ["## Expected in the next two months", ""]
        for s in soon:
            drugs = f" ({s['drugs']})" if s.get("drugs") else ""
            out.append(f"- {s['due']:%B %Y}: main results due for {trial_link(s['msf_trial_id'], s['name'])}{drugs}")
        out += ["", f"[Full calendar]({SITE}/news?tab=upcoming)", ""]

    out += ["---", "",
            f"MSFrontier is independent and free. It is assembled by software from public sources and is not medical "
            f"advice. Talk to your MS team about your own care. Spotted an error? [Tell us]({SITE}/contact)."]
    return subject, "\n".join(out)


def main():
    if MODE == "off":
        print("newsletter: NEWSLETTER_MODE is off, nothing sent")
        return
    if not DRY and not os.environ.get("BUTTONDOWN_API_KEY"):
        print("newsletter: BUTTONDOWN_API_KEY is not set yet, nothing sent")
        return
    with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn, conn.cursor() as cur:
        subject, body = build(*gather(cur))
    if not subject:
        print("newsletter: nothing new this week, nothing sent")
        return
    if DRY:
        print(subject, "\n\n", body)
        return
    status = "about_to_send" if MODE == "send" else "draft"
    headers = {"Authorization": f"Token {os.environ['BUTTONDOWN_API_KEY']}", "X-API-Version": "2026-04-01"}
    if status == "about_to_send":
        headers["X-Buttondown-Live-Dangerously"] = "true"   # needed for the first send with a new API key
    r = requests.post(API, json={"subject": subject, "body": body, "status": status}, headers=headers, timeout=60)
    if r.status_code >= 300:
        print(f"newsletter: Buttondown returned {r.status_code}: {r.text[:500]}")
        sys.exit(1)
    print(f"newsletter: {'sent' if status == 'about_to_send' else 'saved as a draft'}: {subject}")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a") as f:
        f.write(f"Newsletter {status}: {subject}\n")


if __name__ == "__main__":
    main()
