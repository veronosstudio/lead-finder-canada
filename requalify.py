"""Kash (Nov 25): re-check every not-yet-emailed lead in the Veronos campaigns before relaunch.

  python requalify.py shard=0 shards=8 [apply=yes]

For each waiting lead:
  site     - does the website still load?  does it show signs of life (refine.looks_abandoned)?
  email    - Reacher: ok / catchall / unknown / bad
Decision:
  keep     - site up, not abandoned, email confirmed ("ok")
  hold     - email unconfirmed or catch-all: taken out now, sheet row back to "new"; the top-up adds it later
             only when the campaign runs low (same as info@ inboxes)
  remove   - email bad -> sheet "Bad email"; site down -> "Dead site"; site abandoned -> "Inactive"
Dry run by default: prints the counts and examples, changes nothing.
"""
import os, re, sys, json, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import requests
import email_check as EC, refine as R
import export_instantly as X

args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
SHARD, SHARDS, APPLY = int(args.get("shard", 0)), int(args.get("shards", 1)), args.get("apply") == "yes"
API = "https://api.instantly.ai/api/v2"
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def ik(method, path, **kw):
    hdr = H if method != "DELETE" else {"Authorization": H["Authorization"]}
    for attempt in range(6):
        r = requests.request(method, API + path, headers=hdr, timeout=60, **kw)
        if r.status_code == 429: time.sleep(3 + attempt * 3); continue
        if not r.ok: raise RuntimeError(f"{method} {path} {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else {}
    raise RuntimeError("rate limited")


def site_state(url):
    if not url: return "no site"
    url = url if url.startswith("http") else "https://" + url
    s = requests.Session()
    for u in (url.replace("http://", "https://", 1), url.replace("https://", "http://", 1)):
        try:
            r = s.get(u, timeout=20, headers={"User-Agent": UA}, allow_redirects=True)
        except Exception:
            continue
        if r.status_code >= 400: continue
        if R.looks_abandoned(r.text[:600000]): return "abandoned"
        return "up"
    return "down"


leads = []
for country, cid in X.CAMPAIGNS.items():
    after = None
    while True:
        res = ik("POST", "/leads/list", json={"campaign": cid, "limit": 100, **({"starting_after": after} if after else {})})
        items = res.get("items") or []
        for l in items:
            if l.get("timestamp_last_contact") or l.get("status") in (-1, -2, -3, 3): continue
            l["_country"] = country; leads.append(l)
        after = res.get("next_starting_after")
        if not after or not items: break
        time.sleep(0.4)
leads.sort(key=lambda l: l["email"])
mine = [l for i, l in enumerate(leads) if i % SHARDS == SHARD]
print(f"shard {SHARD}/{SHARDS}: {len(mine)} of {len(leads)} waiting leads")

with ThreadPoolExecutor(12) as ex:
    sites = list(ex.map(lambda l: site_state(l.get("website") or (l.get("payload") or {}).get("website") or ""), mine))
ver = EC.verify([l["email"].lower() for l in mine], workers=24)

out, ex_lines = Counter(), []
sheet_status = {}
for l, site in zip(mine, sites):
    e = l["email"].lower(); v = ver.get(e, "unknown")
    if v == "bad": d, st = "remove: bad email", "Bad email"
    elif site == "down": d, st = "remove: site down", "Dead site"
    elif site == "abandoned": d, st = "remove: site looks abandoned", "Inactive"
    elif v in ("unknown", "catchall"): d, st = f"hold: email {v}", "new"
    else: d, st = "keep", None
    out[f"{l['_country']} {d}"] += 1
    if d != "keep":
        if len(ex_lines) < 25: ex_lines.append(f"  {d:32} {e:42} {l.get('company_name') or ''}")
        sheet_status[e] = st
        if APPLY:
            ik("DELETE", f"/leads/{l['id']}"); time.sleep(0.2)

print("\n".join(ex_lines))
print("RESULT", json.dumps(dict(sorted(out.items()))), "" if APPLY else "(dry run, nothing changed)")

if APPLY and sheet_status:
    time.sleep(SHARD * 10)   # shards take turns writing to the sheet
    url, token = os.environ.get("SHEET_URL", "").strip().strip('"\''), os.environ.get("SHEET_TOKEN", "").strip().strip('"\'')
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    rows = requests.get(url, params={"token": token, "status": "Instantly", "limit": "30000"}, timeout=300).json().get("rows", [])
    ups = [{"osm_id": x["osm_id"], "status": sheet_status[(x.get("email") or "").strip().lower()]}
           for x in rows if (x.get("email") or "").strip().lower() in sheet_status]
    done = 0
    for i in range(0, len(ups), 300):
        done += requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json().get("updated", 0)
    print(f"sheet: {done} rows updated")
