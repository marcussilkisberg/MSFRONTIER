"""Emails Marcus a short report after each weekly run, and an alert when a run fails.

Sent through Resend. Until msfrontier.org is verified in Resend, leave ALERT_FROM unset: Resend's test sender
onboarding@resend.dev can send to the address the Resend account was created with, which is all an alert needs.

Environment
  RESEND_API_KEY   Resend API key (GitHub secret)
  ALERT_EMAIL      where alerts go (GitHub secret)
  ALERT_FROM       sender, e.g. "MSFrontier bot <alerts@msfrontier.org>" (optional)
  SUPABASE_DB_URL  for the weekly figures (optional for --failure)
  STEPS_JSON       the workflow's steps context as JSON (from toJSON(steps))
  RUN_URL          link to the workflow run

Usage
  python alerts.py --weekly              weekly report after the refresh
  python alerts.py --failure "News refresh"
"""
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RUN_URL = os.environ.get("RUN_URL", "")
FROM = os.environ.get("ALERT_FROM") or "MSFrontier bot <onboarding@resend.dev>"

STEP_NAMES = {"harvest": "Harvest, tag and build", "genetics": "Genetic leads", "readouts": "Read results from papers",
              "hypotheses": "Build hypothesis ledger", "results_watch": "Results watch", "literature": "Reviews and guidelines",
              "save_readouts": "Save paper results to the repository", "load": "Load into Supabase",
              "exports": "Build the open data exports", "release": "Publish the open data release",
              "newsletter": "Send the newsletter"}


def send(subject, lines):
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("ALERT_EMAIL")
    if not key or not to:
        print("alerts: RESEND_API_KEY or ALERT_EMAIL not set, nothing sent")
        return
    html = "".join(f"<p>{l}</p>" if not l.startswith("<") else l for l in lines)
    r = requests.post("https://api.resend.com/emails", timeout=30,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"from": FROM, "to": [to], "subject": subject, "html": html})
    print(f"alerts: Resend {r.status_code} {r.text[:200]}")


def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""


def failed_steps():
    try:
        steps = json.loads(os.environ.get("STEPS_JSON") or "{}")
    except json.JSONDecodeError:
        return []
    return [STEP_NAMES.get(k, k) for k, v in steps.items() if v.get("outcome") == "failure"]


def landmark_misses():
    p = ROOT / "data" / "validate.log"
    if not p.exists():
        return []
    return re.findall(r"^## (.+?): 0 match", p.read_text(), flags=re.M)


def weekly_figures():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        return {}
    import psycopg
    out = {}
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("""select id, finished_at, n_trials, n_new, n_changed, n_dropped, error
                       from bank.load_runs order by id desc limit 2""")
        runs = cur.fetchall()
        out["runs"] = runs
        cur.execute("""select kind, count(*) from bank.weekly_changes
                       where changed_at >= now() - interval '8 days' group by kind""")
        out["changes"] = dict(cur.fetchall())
        cur.execute("""select name, old_value, new_value from bank.weekly_changes
                       where changed_at >= now() - interval '8 days' and kind = 'hypothesis_status'
                         and new_value in ('confirmed', 'disproven', 'failed_early')""")
        out["big_hyp"] = cur.fetchall()
        cur.execute("""select name, new_value from bank.weekly_changes
                       where changed_at >= now() - interval '8 days' and kind in ('regulatory', 'safety_letter')""")
        out["regulatory"] = cur.fetchall()
        cur.execute("select to_regclass('bank.inbox') is not null")
        if cur.fetchone()[0]:
            cur.execute("select count(*) from bank.inbox where status = 'new'")
            out["inbox_new"] = cur.fetchone()[0]
    return out


def weekly():
    fails, misses = failed_steps(), landmark_misses()
    try:
        f = weekly_figures()
    except Exception as e:   # the report must still go out if the database is unreachable
        f, fails = {}, fails + [f"Reading the bank for this report ({type(e).__name__})"]
    flags = []
    if fails:
        flags.append("Steps that failed: " + ", ".join(fails) + ".")
    if misses:
        flags.append("Landmark trials not found in the build: " + ", ".join(misses) + ".")
    runs = f.get("runs") or []
    if runs and runs[0][6]:
        flags.append(f"The last load recorded an error: {runs[0][6][:200]}")
    if len(runs) == 2 and runs[1][2]:
        delta = (runs[0][2] or 0) - runs[1][2]
        if abs(delta) > 0.05 * runs[1][2]:
            flags.append(f"The number of trials changed by {delta:+,} since the previous load. Check for a "
                         f"harvest problem.")
    if runs and (runs[0][5] or 0) > 50:
        flags.append(f"{runs[0][5]:,} trials dropped out of the build this week.")
    for name, old, new in f.get("big_hyp", []):
        flags.append(f"Hypothesis now <b>{new.replace('_', ' ')}</b> (was {old.replace('_', ' ')}): {name}")
    for name, what in f.get("regulatory", []):
        flags.append(f"Regulatory: {name}: {what}")
    if f.get("inbox_new"):
        flags.append(f"{f['inbox_new']} contact message(s) still marked new in bank.inbox.")

    lines = []
    lines.append("<h3>Needs your attention</h3>" + (ul(flags) if flags else "<p>Nothing. The run looks normal.</p>"))
    if runs:
        r = runs[0]
        lines.append(f"<h3>This week</h3>" + ul([
            f"Trials in the bank: {r[2]:,} ({r[3] or 0:,} new, {r[4] or 0:,} changed)",
            *[f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in sorted((f.get('changes') or {}).items())]]))
    if RUN_URL:
        lines.append(f'<p><a href="{RUN_URL}">Open the run on GitHub</a></p>')
    subject = ("⚠ " if flags and (fails or misses) else "") + "MSFrontier weekly run: " + \
              (f"{len(flags)} thing(s) to check" if flags else "all normal")
    send(subject, lines)


def failure(name):
    send(f"⚠ MSFrontier: {name} failed",
         [f"The workflow <b>{name}</b> failed.", f'<a href="{RUN_URL}">Open the run on GitHub</a>' if RUN_URL else ""])


if __name__ == "__main__":
    if "--failure" in sys.argv:
        failure(sys.argv[sys.argv.index("--failure") + 1] if len(sys.argv) > sys.argv.index("--failure") + 1
                else "A workflow")
    else:
        weekly()
