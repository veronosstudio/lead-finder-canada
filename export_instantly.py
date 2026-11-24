"""Export the next batch from Master Contacts as an Instantly CSV, and mark those rows "Instantly" so nobody is sent twice.

Usage:  SHEET_URL=... SHEET_TOKEN=... python export_instantly.py [country=CA|US] [tiers=A,B] [limit=500] [mark=yes] [out=instantly.csv]
Columns (Instantly variables): email, greeting, firstName, companyName, city, province, service, since, hook, tier, score, website
  {{greeting}}  "Hi Dave," or "Hi there,"      {{hook}}  your sheet's hook if you edited it, else the automatic one
  {{service}}   e.g. "plumbing" (blank if unknown)   {{since}}  licence year (blank if unknown)
Rules: status=new only, one contact per business (website domain), best score first.
"""
import csv, json, os, re, sys
import requests
import hooks as H
import refine as R

COLS = ["email", "greeting", "firstName", "companyName", "city", "province", "service", "nicheLine", "since", "hook", "tier", "score", "website", "emailType", "contactRole", "phone"]
# "I make websites for {{nicheLine}} around {{city}}"
NICHE_LINE = {"dentist": "dental practices", "orthodontist": "orthodontic practices", "plumber": "plumbing companies",
    "electrician": "electrical contractors", "hvac": "heating and cooling companies", "roofer": "roofing companies",
    "lawyer": "law firms", "chiropractor": "chiropractic clinics", "physio": "physio clinics", "optometrist": "optometry clinics",
    "medical": "clinics", "vet": "vet clinics", "accountant": "accounting firms", "financial": "financial advisors",
    "insurance": "insurance agencies", "renovation": "renovation companies", "windows": "window and door companies",
    "landscaper": "landscaping companies", "pool": "pool companies", "solar": "solar companies", "fencing": "fencing companies",
    "garage_doors": "garage door companies", "funeral": "funeral homes", "auto_body": "auto body shops"}

def dom(u):
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", (u or "").strip().lower())).split("/")[0]

def clean_company(n):
    """How a person would write the name in an email: Ben's Machining, not Ben'S Machining Ltd."""
    n = re.sub(r"(['’])S\b", r"\1s", (n or "").strip())
    n = re.sub(r",?\s+(ltd|inc|corp|corporation|limited|incorporated|ulc|llp)\.?$", "", n, flags=re.I).strip()
    return n

ASK = {"dentist": "book an appointment", "orthodontist": "book a consultation", "chiropractor": "book an appointment",
       "physio": "book an appointment", "optometrist": "book an appointment", "medical": "book an appointment", "vet": "book an appointment",
       "lawyer": "request a consultation", "accountant": "get in touch", "financial": "book a consultation"}

# Kash (Nov 24): hooks read as one casual sentence after "noticed a couple things." Old-year footers aren't
# worth mentioning, so they get the refresh line too.
def hook_sentence(hook):
    h = (hook or "").strip()
    low = h.lower()
    if "hard to use on a phone" in low:
        return "Pulled it up on my phone and it was pretty tough to get around."
    if "not secure" in low:
        return "Chrome shows a \"Not secure\" warning when it loads, which can scare people off."
    m = re.search(r"easy way for people to (.+)$", h)
    if m:
        what = m.group(1).rstrip(".")
        what = "book online" if what == "book an appointment" else what
        return f"Couldn't find an easy way to {what}."
    return "Looks like it could use a refresh."

def hey(fname):
    """Hey Dave, / Hi Dr. Lee, / Hey there,"""
    if not fname: return "Hey there,"
    return f"Hi {fname}," if re.match(r"Dr\.?\s", fname) else f"Hey {fname},"

def niche_hook(hook, service):
    """Same finding, worded for the niche: dentists don't take quote requests."""
    return hook.replace("ask for a quote", ASK.get(service, "ask for a quote"))

def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    url = os.environ["SHEET_URL"].strip().strip('"\'')
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    token = os.environ["SHEET_TOKEN"].strip().strip('"\'')
    rows = requests.get(url, params={"token": token, "status": "new", "limit": "10000"}, timeout=120).json().get("rows", [])
    tiers = [t.strip().upper() for t in args.get("tiers", "A,B").split(",")]
    rows = [x for x in rows if (x.get("tier") or "").upper() in tiers and x.get("email")
            and not re.match(r"(webmaster|postmaster|hostmaster|noreply|no-reply|abuse|privacy)@", x["email"].strip().lower())]
    svcs = [x.strip() for x in args.get("services", "").split(",") if x.strip()]
    if svcs: rows = [x for x in rows if (x.get("service") or "") in svcs]
    want = args.get("country", "").upper()
    if want: rows = [x for x in rows if (x.get("country") or "CA").upper() == want]   # rows from before the US launch are Canada
    rows.sort(key=lambda x: -int(x.get("score") or 0))
    limit = int(args.get("limit", "500"))
    out, seen_e, seen_d, picked = args.get("out", "instantly.csv"), set(), set(), []
    for x in rows:
        e, d = x["email"].strip().lower(), dom(x.get("website"))
        if e in seen_e or (d and d in seen_d): continue
        seen_e.add(e); seen_d.add(d); picked.append(x)
        if len(picked) >= limit: break
    simple = ["email", "firstName", "companyName", "website", "greeting", "city", "nicheLine", "hook", "service", "tier", "score", "emailType", "phone"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(simple)
        for x in picked:
            fn = (x.get("first_name") or "").strip()
            row = dict(zip(COLS, [x["email"].strip().lower(), hey(fn), fn, clean_company(x.get("business", "")), x.get("town", ""), x.get("province", ""),
                        H.service_word(x.get("service", "")), NICHE_LINE.get(x.get("service", ""), "local businesses"), x.get("since") or H.since_year(x.get("why_dated", "")),
                        hook_sentence(niche_hook((x.get("hook") or "").strip() or H.hook(x.get("why_dated", "")), x.get("service", ""))), x.get("tier", ""), x.get("score", ""), x.get("website", ""),
                        x.get("email_type") or ("named" if fn else "general"), x.get("contact_role", ""), (x.get("phone") or "").strip()]))
            w.writerow([row[c] for c in simple])
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
