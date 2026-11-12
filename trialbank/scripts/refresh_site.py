"""Refreshes the stored views the site reads, after a load.

Many pages of the site read materialised views in schema "bank" (trial_index, goal_landing, the approach statistics
and others, made by the migrations from 029 on). A materialised view holds the bank as it was when it was last
refreshed, so without this step the pages keep showing the previous load. The work is done in the database by
bank.refresh_site() (migration 036), which refreshes every materialised view of the schema in dependency order,
so a view added by a later migration needs no change here.

Runs in its own transaction after load_supabase.py has committed: a failure here never undoes a load.
Before migration 036 it prints a note and exits without an error.

Usage:
  SUPABASE_DB_URL=postgresql://... python refresh_site.py
"""
import os
import sys

import psycopg


def main():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("Set SUPABASE_DB_URL (Supabase → Connect → Session pooler connection string).")
    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("select to_regprocedure('bank.refresh_site()') is not null")
        if not cur.fetchone()[0]:
            print("migration 036 not applied: the site's stored views were not refreshed")
            return 0
        cur.execute("set statement_timeout = '30min'")   # the views together take seconds; never cut one short
        cur.execute("select bank.refresh_site()")
        done = cur.fetchone()[0] or []
    failed = [d for d in done if d.get("error")]
    for d in done:
        print(f"  {d['view']}: " + (f"FAILED: {d['error']}" if d.get("error") else f"{d['seconds']} s, {d['how']}"))
    print(f"stored views: {len(done) - len(failed)} refreshed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
