"""Export the next batch from Master Contacts as an Instantly CSV, and mark those rows "Instantly" so nobody is sent twice.

Usage:  SHEET_URL=... SHEET_TOKEN=... python export_instantly.py [tiers=A,B] [limit=500] [mark=yes] [out=instantly.csv]
Columns (Instantly variables): email, greeting, firstName, companyName, city, province, service, since, hook, tier, score, website
  {{greeting}}  "Hi Dave," or "Hi there,"      {{hook}}  your sheet's hook if you edited it, else the automatic one
  {{service}}   e.g. "plumbing" (blank if unknown)   {{since}}  licence year (blank if unknown)
Rules: status=new only, one contact per business (website domain), best score first.
"""
import csv, json, os, re, sys
import requests
import hooks as H
import refine as R

COLS = ["email", "greeting", "firstName", "companyName", "city", "province", "service", "since", "hook", "tier", "score", "website"]

def dom(u):
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", (u or "").strip().lower())).split("/")[0]

def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    url = os.environ["SHEET_URL"].strip().strip('"\'')
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    token = os.environ["SHEET_TOKEN"].strip().strip('"\'')
    rows = requests.get(url, params={"token": token, "status": "new", "limit": "10000"}, timeout=120).json().get("rows", [])
    tiers = [t.strip().upper() for t in args.get("tiers", "A,B").split(",")]
    rows = [x for x in rows if (x.get("tier") or "").upper() in tiers and x.get("email")]
    rows.sort(key=lambda x: -int(x.get("score") or 0))
    limit = int(args.get("limit", "500"))
    out, seen_e, seen_d, picked = args.get("out", "instantly.csv"), set(), set(), []
    for x in rows:
        e, d = x["email"].strip().lower(), dom(x.get("website"))
        if e in seen_e or (d and d in seen_d): continue
        seen_e.add(e); seen_d.add(d); picked.append(x)
        if len(picked) >= limit: break
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(COLS)
        for x in picked:
            fn = (x.get("first_name") or "").strip()
            w.writerow([x["email"].strip().lower(), R.greeting(fn), fn, x.get("business", ""), x.get("town", ""), x.get("province", ""),
                        H.service_word(x.get("service", "")), x.get("since") or H.since_year(x.get("why_dated", "")),
                        (x.get("hook") or "").strip() or H.hook(x.get("why_dated", "")), x.get("tier", ""), x.get("score", ""), x.get("website", "")])
    print(f"wrote {len(picked)} contacts to {out}")
    if args.get("mark", "no") == "yes" and picked:
        ups = [{"osm_id": x["osm_id"], "status": "Instantly"} for x in picked]
        done = 0
        for i in range(0, len(ups), 300):
            j = requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json()
            done += j.get("updated", 0)
        print(f"marked {done} rows as Instantly")

if __name__ == "__main__":
    main()
