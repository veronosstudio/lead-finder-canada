"""Export contacts from the Master Contacts sheet as Instantly-ready CSVs.

Usage:  SHEET_URL=... SHEET_TOKEN=... python export_instantly.py [status=new] [tiers=A+,A] [limit=2000] [out=instantly]
Writes two files, best score first:
  <out>-competitor.csv   contacts with a verified competitor  -> the "{{competitor}}" email (#1)
  <out>-standard.csv     everyone else                        -> the "yes or no" email (#10)
Columns: email, greeting, firstName, companyName, city, province, category, service, competitor, competitor_site,
         hook, tier, score, website
Variables in Instantly: {{greeting}} (always safe: "Hi Dave," or "Hi there,"), {{competitor}}, {{hook}}, {{companyName}}, {{city}}.
"""
import csv, os, sys
import requests
from hooks import hook, tier as old_tier
import refine as R

COLS = ["email", "greeting", "firstName", "companyName", "city", "province", "category", "service", "competitor",
        "competitor_site", "hook", "tier", "score", "website"]

def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    url = os.environ["SHEET_URL"].strip().strip('"\'')
    token = os.environ["SHEET_TOKEN"].strip().strip('"\'')
    r = requests.get(url, params={"token": token, "status": args.get("status", "new"), "limit": args.get("limit", "5000")}, timeout=120)
    r.raise_for_status()
    rows = r.json().get("rows", [])
    tiers = [t.strip().upper() for t in args.get("tiers", "A+,A").split(",")]
    rows = [x for x in rows if (x.get("tier") or old_tier(x.get("why_dated", ""))).upper() in tiers]
    rows.sort(key=lambda x: -int(x.get("score") or 0))
    out = args.get("out", "instantly")
    seen, files = set(), {"competitor": [], "standard": []}
    for x in rows:
        e = (x.get("email") or "").strip().lower()
        if not e or e in seen: continue
        seen.add(e)
        fn = (x.get("first_name") or "").strip()
        rec = [e, R.greeting(fn), fn, x.get("business", ""), x.get("town", ""), x.get("province", ""), x.get("category", ""),
               x.get("service", ""), x.get("competitor", ""), x.get("competitor_site", ""), hook(x.get("why_dated", "")),
               x.get("tier", ""), x.get("score", ""), x.get("website", "")]
        files["competitor" if x.get("competitor") else "standard"].append(rec)
    for name, recs in files.items():
        with open(f"{out}-{name}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(COLS); w.writerows(recs)
        print(f"wrote {len(recs)} contacts to {out}-{name}.csv")

if __name__ == "__main__":
    main()
