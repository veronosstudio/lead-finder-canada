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

# Kash (Nov 24): businesses listed under just a person's name ("Martin D Glazer") read wrong in
# "Website for {{companyName}}", so they become "your firm" / "your practice" / "your business".
BIZ_WORD = re.compile(r"\b(law|legal|lawyer|avocat|notary|dental|dentist|dentistry|clinic|group|services?|inc|ltd|llc|llp|pc|pllc|"
    r"plumbing|electric|roofing|heating|hvac|construction|company|co|associates|centre|center|studio|shop|auto|homes?|realty|"
    r"insurance|financial|accounting|cpa|dds|dmd|orthodontics|family|architects?|design|gallery|school|church|physio|sport|"
    r"professional|adr|consulting|massage|chiropractic|salon|spa|landscaping|painting|flooring)\b|&|\band\b|,", re.I)

EXTRA_BIZ = {"physiotherapy", "orthodontist", "florist", "lottery", "studios", "entreprises", "convenience", "communities",
             "optical", "vision", "smiles", "associes", "avocats", "counselling", "counseling", "rmt", "nitro", "photography",
             "productions", "media", "fitness", "motors", "farms", "ranch", "jewellers", "jewelers", "bakery", "catering"}

def person_named(n):
    """Only "First Last" or "First D Last" / "First Last E" style names count."""
    w = (n or "").replace(",", " ").split()
    if not 2 <= len(w) <= 3 or BIZ_WORD.search(n or "") or any(x.lower().strip(".") in EXTRA_BIZ for x in w):
        return False
    if not all(re.fullmatch(r"[A-Z][a-zA-Z'\-]*\.?", x) for x in w) or w[0].lower() not in R.FIRST_NAMES:
        return False
    if len(w) == 3:  # a middle or trailing initial is required for three words
        return bool(re.fullmatch(r"[A-Z]\.?", w[1]) or re.fullmatch(r"[A-Z]\.?", w[2]))
    return True

def generic_company(service):
    s = (service or "").lower()
    if re.search(r"legal|law", s): return "your firm"
    if re.search(r"dental|chiro|physio|eye|medical|massage|clinic|care|health|optom|vet", s): return "your practice"
    return "your business"

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

# Kash (Nov 24, email v3): "Noticed {{coPoss}} website {{notice}}"
def notice_line(hook_sentence_or_hook):
    h = (hook_sentence_or_hook or "").lower()
    if "phone" in h: return "is pretty tough to use on a phone."
    if "not secure" in h: return 'shows a "Not secure" warning when it loads.'
    m = re.search(r"easy way (?:for people )?to (.+?)\.?$", hook_sentence_or_hook or "")
    if m:
        what = m.group(1).rstrip(".")
        return f"doesn't have an easy way to {'book online' if what == 'book an appointment' else what}."
    return "could use a refresh."

def co_poss(name):
    n = (name or "").strip()
    if not n: return "your"
    return n + ("'" if n.lower().endswith("s") else "'s")

def hey(fname):
    """Hey Dave, / Hi Dr. Lee, / Hey there,"""
    if not fname: return "Hey there,"
    return f"Hi {fname}," if re.match(r"Dr\.?\s", fname) else f"Hey {fname},"

def niche_hook(hook, service):
    """Same finding, worded for the niche: dentists don't take quote requests."""
    return hook.replace("ask for a quote", ASK.get(service, "ask for a quote"))

# Daily top-up (Kash, Nov 24): new leads go straight into the matching Veronos campaign.
CAMPAIGNS = {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}
STANDARD = {"email", "firstName", "companyName", "website", "phone"}


# Kash (Nov 24): bounces. Shared cleaning + Reacher check live in email_check.py (the scraper uses them too).
import email_check as EC

def push_instantly(rows, country):
    key = os.environ.get("INSTANTLY_API_KEY", "").strip()
    camp = CAMPAIGNS.get(country)
    if not key or not camp:
        print("push skipped: INSTANTLY_API_KEY secret missing or no country"); return False
    H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    leads = [{"email": r["email"], "first_name": r["firstName"] or None, "company_name": r["companyName"] or None,
              "website": r["website"] or None, "phone": r.get("phone") or None,
              "custom_variables": {k: v for k, v in r.items() if k not in STANDARD and v not in (None, "")}} for r in rows]
    added = 0
    for i in range(0, len(leads), 500):
        chunk = leads[i:i + 500]
        res = requests.post("https://api.instantly.ai/api/v2/leads/add", headers=H, timeout=120,
                            json={"campaign_id": camp, "skip_if_in_workspace": True, "leads": chunk})
        if res.status_code == 404:  # older API: one lead at a time
            for l in chunk:
                r1 = requests.post("https://api.instantly.ai/api/v2/leads", headers=H, timeout=60,
                                   json={"campaign": camp, "skip_if_in_workspace": True, **l})
                if r1.ok: added += 1
            continue
        if not res.ok:
            print(f"push failed {res.status_code}: {res.text[:300]}"); return False
        j = res.json() if res.text else {}
        added += int(j.get("leads_uploaded", j.get("total_uploaded", len(chunk))) or 0)
    print(f"pushed {added} new leads to Instantly campaign {country}")
    return True

def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    url = os.environ["SHEET_URL"].strip().strip('"\'')
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    token = os.environ["SHEET_TOKEN"].strip().strip('"\'')
    rows = requests.get(url, params={"token": token, "status": "new", "limit": "10000"}, timeout=120).json().get("rows", [])
    tiers = [t.strip().upper() for t in args.get("tiers", "A,B").split(",")]
    for x in rows: x["email"] = EC.clean_email(x.get("email"))
    rows = [x for x in rows if (x.get("tier") or "").upper() in tiers and x.get("email") and not EC.junk_email(x["email"])
            and not re.match(r"(webmaster|postmaster|hostmaster|noreply|no-reply|abuse|privacy)@", x["email"].strip().lower())]
    svcs = [x.strip() for x in args.get("services", "").split(",") if x.strip()]
    if svcs: rows = [x for x in rows if (x.get("service") or "") in svcs]
    want = args.get("country", "").upper()
    if want: rows = [x for x in rows if (x.get("country") or "CA").upper() == want]   # rows from before the US launch are Canada
    # Kash (Nov 24): owner/manager emails first, then named people, then shared inboxes; best score within each.
    TYPE_RANK = {"owner": 0, "manager": 1, "named": 2}
    rows.sort(key=lambda x: (TYPE_RANK.get((x.get("email_type") or "").lower(), 3), -int(x.get("score") or 0)))
    bad_ids = []
    if args.get("verify", "no") == "yes" and rows:
        res = EC.verify(sorted({x["email"] for x in rows}))
        bad = {e for e, v in res.items() if v == "bad"}
        bad_ids = [x["osm_id"] for x in rows if x["email"] in bad]
        rows = [x for x in rows if x["email"] not in bad]
        from collections import Counter
        print("verify:", dict(Counter(res.values())), f"-> skipped {len(bad)} bad emails")
    limit = int(args.get("limit", "500"))
    out, seen_e, seen_d, picked = args.get("out", "instantly.csv"), set(), set(), []
    for x in rows:
        e, d = x["email"].strip().lower(), dom(x.get("website"))
        if e in seen_e or (d and d in seen_d): continue
        seen_e.add(e); seen_d.add(d); picked.append(x)
        if len(picked) >= limit: break
    simple = ["email", "firstName", "companyName", "website", "greeting", "city", "nicheLine", "hook", "service", "tier", "score", "emailType", "phone", "notice", "coPoss"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(simple)
        out_rows = []
        for x in picked:
            fn = (x.get("first_name") or "").strip()
            row = dict(zip(COLS, [x["email"].strip().lower(), hey(fn), fn, (generic_company(H.service_word(x.get("service", ""))) if person_named(clean_company(x.get("business", ""))) else clean_company(x.get("business", ""))), x.get("town", ""), x.get("province", ""),
                        H.service_word(x.get("service", "")), NICHE_LINE.get(x.get("service", ""), "local businesses"), x.get("since") or H.since_year(x.get("why_dated", "")),
                        hook_sentence(niche_hook((x.get("hook") or "").strip() or H.hook(x.get("why_dated", "")), x.get("service", ""))), x.get("tier", ""), x.get("score", ""), x.get("website", ""),
                        x.get("email_type") or ("named" if fn else "general"), x.get("contact_role", ""), (x.get("phone") or "").strip()]))
            row["notice"] = notice_line(row["hook"]); row["coPoss"] = co_poss(row["companyName"])
            w.writerow([row[c] for c in simple]); out_rows.append({c: row[c] for c in simple})
    print(f"wrote {len(picked)} contacts to {out}")
    if args.get("push", "no") == "yes" and picked:
        if not push_instantly(out_rows, want):
            sys.exit("push to Instantly failed; rows NOT marked")
    if args.get("mark", "no") == "yes" and bad_ids:
        ups = [{"osm_id": i, "status": "Bad email"} for i in bad_ids]
        for i in range(0, len(ups), 300):
            requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                          headers={"Content-Type": "application/json"}, timeout=300)
        print(f"marked {len(bad_ids)} rows as Bad email")
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
