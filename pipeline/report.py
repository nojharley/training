"""Stage 4 (closing the loop): read completions back from the KnowBe4 Reporting API.

The Reporting API is read-only and needs an Account Admin to create the key
(Account Settings > API). Set KNOWBE4_API_KEY and KNOWBE4_REGION (us, eu, ca, uk, de).
Without a key it runs on built-in sample data so you can see the output.
"""
import argparse
import csv
from collections import Counter, defaultdict

import requests

from common import OUTPUT, env, log

SAMPLE = [
    {"user": {"email": "a.demo@example.com"}, "module_name": "Submitting an expense claim v1.0.1", "status": "Passed"},
    {"user": {"email": "b.demo@example.com"}, "module_name": "Submitting an expense claim v1.0.1", "status": "In Progress"},
    {"user": {"email": "c.demo@example.com"}, "module_name": "Submitting an expense claim v1.0.2", "status": "Passed"},
    {"user": {"email": "d.demo@example.com"}, "module_name": "Submitting an expense claim v1.0.2", "status": "Not Started"},
    {"user": {"email": "e.demo@example.com"}, "module_name": "Submitting an expense claim v1.0.2", "status": "Failed"},
]


def fetch_enrollments(api_key, region):
    base = f"https://{region}.api.knowbe4.com/v1/training/enrollments"
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {api_key}"
    page, out = 1, []
    while True:
        r = s.get(base, params={"page": page, "per_page": 500}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            return out
        out.extend(batch)
        page += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="expense claim", help="text to match in the module name")
    ap.add_argument("--current", default=None, help="current version string, e.g. v1.0.2, to flag outdated completions")
    a = ap.parse_args()

    key = env("KNOWBE4_API_KEY")
    rows = fetch_enrollments(key, env("KNOWBE4_REGION", "eu")) if key else SAMPLE
    log("Source: KnowBe4 Reporting API" if key else "Source: sample data (set KNOWBE4_API_KEY for live data)")
    rows = [r for r in rows if a.match.lower() in (r.get("module_name") or r.get("content_name") or "").lower()]

    by_module = defaultdict(Counter)
    for r in rows:
        by_module[r.get("module_name") or r.get("content_name")][r.get("status", "Unknown")] += 1
    for name, counts in sorted(by_module.items()):
        total = sum(counts.values())
        done = counts.get("Passed", 0) + counts.get("Completed", 0)
        log(f"{name}: {done}/{total} complete ({done / total:.0%}) {dict(counts)}")

    if a.current:
        old = [r for r in rows if a.current not in (r.get("module_name") or "")
               and r.get("status") in ("Passed", "Completed")]
        log(f"{len(old)} learner(s) completed an older version than {a.current}")

    out = OUTPUT / "knowbe4_enrollments.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["email", "module", "status"])
        for r in rows:
            w.writerow([(r.get("user") or {}).get("email", ""), r.get("module_name", ""), r.get("status", "")])
    log(f"Wrote {out}")


if __name__ == "__main__":
    main()
