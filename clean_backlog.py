"""Kash (Nov 25): run the list-cleaning checks on every sheet row waiting to be loaded (status "new").
  python clean_backlog.py shard=0 shards=8 [apply=yes]
Fails -> sheet status: "Dead site" (down / parked), "Inactive" (abandoned), "Not a fit" (nonprofit, name not on site, web/IT shop, big firm).
No email re-checks (each address is checked once, at load time)."""
import os, re, sys, json, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import requests
import refine as R, names as NM, sitecheck as SC

args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
SHARD, SHARDS, APPLY = int(args.get("shard", 0)), int(args.get("shards", 1)), args.get("apply") == "yes"
url, token = os.environ["SHEET_URL"].strip().strip('"\''), os.environ["SHEET_TOKEN"].strip().strip('"\'')
m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
rows = requests.get(url, params={"token": token, "status": "new", "limit": "30000"}, timeout=300).json().get("rows", [])
rows.sort(key=lambda x: str(x.get("osm_id")))
mine = [x for i, x in enumerate(rows) if i % SHARDS == SHARD]
print(f"shard {SHARD}/{SHARDS}: {len(mine)} of {len(rows)} waiting rows")
with ThreadPoolExecutor(16) as ex:
    pages = list(ex.map(lambda x: SC.fetch(x.get("website", "")), mine))
out, ups, exl = Counter(), [], []
for x, (site, html) in zip(mine, pages):
    name, web = x.get("business", ""), x.get("website", "")
    if site in ("down", "no site", "parked"): d, st = f"site {site}", "Dead site"
    elif site == "abandoned": d, st = "site abandoned", "Inactive"
    elif R.nonprofit(name, web): d, st = "nonprofit / gov / school", "Not a fit"
    elif NM.bad_fit(name, web, x.get("email", "")): d, st = "web/IT shop or big firm", "Not a fit"
    elif not R.name_on_site(name, html, web): d, st = "name not on site", "Not a fit"
    else: d, st = "keep", None
    out[f"{(x.get('country') or 'CA').upper()} {d}"] += 1
    if st:
        ups.append({"osm_id": x["osm_id"], "status": st})
        if len(exl) < 15: exl.append(f"  {d:28} {x.get('email','')[:40]:40} {name[:40]}")
print("\n".join(exl))
print("RESULT", json.dumps(dict(sorted(out.items()))), "" if APPLY else "(dry run)")
if APPLY and ups:
    time.sleep(SHARD * 10)
    done = 0
    for i in range(0, len(ups), 300):
        done += requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json().get("updated", 0)
    print(f"sheet: {done} rows marked")
