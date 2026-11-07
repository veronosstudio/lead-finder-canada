"""Export contacts from the Master Contacts sheet as an Instantly-ready CSV, with a {{hook}} column.

Usage:  SHEET_URL=... SHEET_TOKEN=... python export_instantly.py [status=new] [tier=A|B] [limit=2000] [out=instantly.csv]
Columns: email, companyName, website, city, province, category, tier (A first), hook, why_dated
In Instantly, map hook as a custom variable and use: "Noticed your site {{hook}}."
"""
import csv, os, sys
import requests
from hooks import hook, tier

def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    url = os.environ["SHEET_URL"].strip().strip('"\'')
    token = os.environ["SHEET_TOKEN"].strip().strip('"\'')
    r = requests.get(url, params={"token": token, "status": args.get("status", "new"), "limit": args.get("limit", "2000")}, timeout=120)
    r.raise_for_status()
    data = r.json()
    rows = data.get("rows", data) if isinstance(data, dict) else data
    out = args.get("out", "instantly.csv")
    seen = set()
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["email", "companyName", "website", "city", "province", "category", "tier", "hook", "why_dated"])
        if args.get("tier"): rows = [x for x in rows if tier(x.get("why_dated", "")) == args["tier"].upper()]
        rows = sorted(rows, key=lambda x: tier(x.get("why_dated", "")))  # A first
        for x in rows:
            e = (x.get("email") or "").strip().lower()
            if not e or e in seen: continue
            seen.add(e)
            w.writerow([e, x.get("business", ""), x.get("website", ""), x.get("town", ""), x.get("province", ""),
                        x.get("category", ""), tier(x.get("why_dated", "")), hook(x.get("why_dated", "")), x.get("why_dated", "")])
    print(f"wrote {len(seen)} contacts to {out}")

if __name__ == "__main__":
    main()
