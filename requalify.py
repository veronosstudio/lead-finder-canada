"""Kash (Nov 25): re-check every not-yet-emailed lead in the Veronos campaigns before relaunch.

  python requalify.py shard=0 shards=8 [apply=yes] [hold=unknown]

For each waiting lead:
  site   - loads? parked / for sale / coming soon? abandoned (old copyright, nothing current)?
  name   - does the business name appear on its own site? (sold, renamed or the wrong site if not)
  type   - nonprofit / government / school?
  email  - Reacher: ok / catchall / unknown / bad (unknowns get a second, slower try)
  need   - real phone-size browser test for "doesn't fit a phone"; old COVID / holiday notices; no online booking
Decision:
  remove - bad email, site down/parked/abandoned, name not on site, nonprofit   (sheet status says why)
  hold   - email in HOLD (default: unknown): out of the campaign, sheet row back to "new" (fills in later)
  keep   - the rest; if the best problem to mention changed, the email lines are rewritten
Dry run by default.
"""
import os, re, sys, json, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import requests
import email_check as EC, refine as R, email_vars as V
import sitecheck as SC
import export_instantly as X

args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
SHARD, SHARDS, APPLY = int(args.get("shard", 0)), int(args.get("shards", 1)), args.get("apply") == "yes"
HOLD = {x for x in args.get("hold", "unknown").split(",") if x}
WHO = args.get("who", "waiting")   # waiting = not yet emailed; contacted = got email 1, no reply yet (failures: follow-ups stopped)
API = "https://api.instantly.ai/api/v2"
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}


def ik(method, path, **kw):
    hdr = H if method != "DELETE" else {"Authorization": H["Authorization"]}
    for attempt in range(6):
        r = requests.request(method, API + path, headers=hdr, timeout=60, **kw)
        if r.status_code == 429: time.sleep(3 + attempt * 3); continue
        if not r.ok: raise RuntimeError(f"{method} {path} {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else {}
    raise RuntimeError("rate limited")


url, token = os.environ.get("SHEET_URL", "").strip().strip('"\''), os.environ.get("SHEET_TOKEN", "").strip().strip('"\'')
m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
sheet = {}
if url and token:
    for x in requests.get(url, params={"token": token, "status": "Instantly", "limit": "30000"}, timeout=300).json().get("rows", []):
        sheet[(x.get("email") or "").strip().lower()] = x

leads = []
for country, cid in X.CAMPAIGNS.items():
    after = None
    while True:
        res = ik("POST", "/leads/list", json={"campaign": cid, "limit": 100, **({"starting_after": after} if after else {})})
        items = res.get("items") or []
        for l in items:
            if l.get("status") in (-1, -2, -3, 3) or int(l.get("email_reply_count") or 0) > 0: continue
            if bool(l.get("timestamp_last_contact")) != (WHO == "contacted"): continue
            l["_country"] = country; leads.append(l)
        after = res.get("next_starting_after")
        if not after or not items: break
        time.sleep(0.4)
leads.sort(key=lambda l: l["email"])
mine = [l for i, l in enumerate(leads) if i % SHARDS == SHARD]
print(f"shard {SHARD}/{SHARDS}: {len(mine)} of {len(leads)} waiting leads; {len(sheet)} sheet rows")

site_of = lambda l: l.get("website") or (l.get("payload") or {}).get("website") or ""
with ThreadPoolExecutor(12) as ex:
    pages = list(ex.map(lambda l: SC.fetch(site_of(l)), mine))
# Kash (Nov 25): each address gets checked once. Checking the same mail servers again and again from GitHub's shared
# machines makes them start refusing, which looks like "bad" -- so this pass can skip the email check (verify=no).
VERIFY = args.get("verify", "yes") == "yes"
ver = EC.verify([l["email"].lower() for l in mine], workers=16) if VERIFY else {l["email"].lower(): "ok" for l in mine}
retry = [e for e, v in ver.items() if v == "unknown"] if VERIFY else []
if retry:
    time.sleep(45)
    ver.update({e: v for e, v in EC.verify(retry, workers=4).items() if v != "unknown"})
    print(f"retried {len(retry)} unknown: {sum(1 for e in retry if ver[e] != 'unknown')} now answered")
# any lead that could end up saying "doesn't fit a phone" gets the real phone test (not just the ones saying it now)
mobile = [site_of(l) for l, (st, _) in zip(mine, pages) if WHO == "waiting" and st == "up" and
          ((l.get("payload") or {}).get("issue") == "mobile" or "not built for phones" in (sheet.get(l["email"].lower(), {}).get("why_dated") or "").lower())]
fit = SC.phone_fit(mobile) if mobile else {}
print(f"phone test: {len(mobile)} sites opened, {sum(1 for v in fit.values() if v is True)} actually fit a phone")

out, ex_lines, sheet_status = Counter(), [], {}
for l, (site, html) in zip(mine, pages):
    e = l["email"].lower(); v = ver.get(e, "unknown"); row = sheet.get(e, {})
    raw = row.get("business") or l.get("company_name") or ""
    if v == "bad": d, st = "remove: bad email", "Bad email"
    elif site in ("down", "no site"): d, st = "remove: site down", "Dead site"
    elif site == "parked": d, st = "remove: parked / coming soon", "Dead site"
    elif site == "abandoned": d, st = "remove: site looks abandoned", "Inactive"
    elif R.nonprofit(raw, site_of(l)): d, st = "remove: nonprofit / gov / school", "Not a fit"
    elif not raw.startswith("your ") and not R.name_on_site(raw, html, site_of(l)): d, st = "remove: name not on their site", "Not a fit"
    elif v in HOLD and WHO == "waiting": d, st = f"hold: email {v}", "new"
    else: d, st = ("keep" if v == "ok" else f"keep: email {v}"), None
    out[f"{l['_country']} {d}"] += 1
    if st is not None:
        if len(ex_lines) < 30: ex_lines.append(f"  {d:34} {e:40} {raw[:40]}")
        sheet_status[e] = st
        if APPLY:
            ik("DELETE", f"/leads/{l['id']}"); time.sleep(0.2)
        continue
    if WHO == "contacted": continue     # email 1 already went out; nothing to reword
    # keep: is there a truer / better problem to mention now?
    p = dict(l.get("payload") or {})
    why = row.get("why_dated") or ""
    fits = fit.get(site_of(l)) is True
    if fits: why = re.sub(r"not built for phones;?\s*", "", why)
    stale = R.stale_signals(html)
    if stale: why += "; " + "; ".join(stale)
    if (p.get("service") or row.get("service")) in R.APPOINTMENT and not R.site_signals(html).get("booking") and "no online booking" not in why:
        why += "; no online booking"
    try: speed = float(p.get("speed")) if p.get("speed") else None
    except ValueError: speed = None
    nv = V.build(why, "" if fits else p.get("hook", ""), speed)
    if nv["issue"] != p.get("issue"):
        out[f"{l['_country']} keep: problem {p.get('issue')} -> {nv['issue']}"] += 1
        if APPLY:
            p.update({"notice": nv["notice"], "cost": nv["cost"], "tip": nv["tip"], "issue": nv["issue"]})
            ik("PATCH", f"/leads/{l['id']}", json={"custom_variables": p}); time.sleep(0.12)

print("\n".join(ex_lines))
print("RESULT", json.dumps(dict(sorted(out.items()))), "" if APPLY else "(dry run, nothing changed)")

if APPLY and sheet_status and url and token:
    time.sleep(SHARD * 10)   # shards take turns writing to the sheet
    ups = [{"osm_id": sheet[e]["osm_id"], "status": st} for e, st in sheet_status.items() if e in sheet and sheet[e].get("osm_id")]
    done = 0
    for i in range(0, len(ups), 300):
        done += requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json().get("updated", 0)
    print(f"sheet: {done} rows updated")
