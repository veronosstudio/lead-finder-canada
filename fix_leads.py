"""Kash (Nov 25): fix leads already waiting in the Veronos campaigns, before they get email 1.

  python fix_leads.py            dry run: shows what would change
  python fix_leads.py apply=yes  applies it

For every not-yet-emailed lead in the US and Canada campaigns:
  - company name rewritten the way a person would write it (names.py); falls back to "your firm/practice/business"
  - coPoss rewritten to match ("Kastorf Law's" / "your")
  - speed lines reworded ("...in Google's speed test", "...longer than 3 seconds")
  - web/marketing/IT shops and big multi-partner firms are removed from the campaign (not yet emailed only)
Leads already emailed are left alone (their follow-ups are replies in the same thread).
"""
import os, re, sys, time
from collections import Counter
import requests
import names as NM, refine as R, email_vars as V, hooks as HK
import export_instantly as X

args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
APPLY = args.get("apply") == "yes"
API = "https://api.instantly.ai/api/v2"
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}


def ik(method, path, **kw):
    hdr = H if method != "DELETE" else {"Authorization": H["Authorization"]}
    for attempt in range(6):
        r = requests.request(method, API + path, headers=hdr, timeout=60, **kw)
        if r.status_code == 429: time.sleep(3 + attempt * 3); continue
        if not r.ok: raise RuntimeError(f"{method} {path} {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}
    raise RuntimeError("rate limited")


stats, samples, removed = Counter(), [], []
for country, cid in X.CAMPAIGNS.items():
    after, leads = None, []
    while True:
        res = ik("POST", "/leads/list", json={"campaign": cid, "limit": 100, **({"starting_after": after} if after else {})})
        items = res.get("items") or []
        leads += items
        after = res.get("next_starting_after")
        if not after or not items: break
        time.sleep(0.4)
    waiting = [l for l in leads if not l.get("timestamp_last_contact") and l.get("status") not in (-1, -2, -3, 3)]
    print(f"{country}: {len(leads)} leads, {len(waiting)} not yet emailed")
    for l in waiting:
        p = dict(l.get("payload") or {})
        raw = l.get("company_name") or p.get("companyName") or ""
        fn = l.get("first_name") or p.get("firstName") or ""
        site = l.get("website") or p.get("website") or ""
        why = NM.bad_fit(raw, site, l["email"])
        if why:
            stats["removed: " + why] += 1
            removed.append(f"{country} {l['email']} | {raw} | {why}")
            if APPLY:
                ik("DELETE", f"/leads/{l['id']}"); time.sleep(0.15)
            continue
        gen = X.generic_company(p.get("service", ""))
        co, poss = NM.natural(raw, fn, gen, R.FIRST_NAMES)
        want = {"coPoss": poss, "subjA": NM.subject_a(co)}
        if p.get("issue") == "speed" and p.get("speed"):
            try:
                n, c, t = V.lines("speed", float(p["speed"]))
                want.update({"notice": n, "cost": c})
            except ValueError:
                pass
        changed_vars = {k: v for k, v in want.items() if p.get(k) != v}
        name_changed = co != raw
        if not changed_vars and not name_changed:
            stats["already fine"] += 1; continue
        stats["fixed"] += 1
        if name_changed: stats["name rewritten"] += 1
        if co.startswith("your "): stats['name -> "your ..."'] += 1
        if len(samples) < 40 and name_changed: samples.append(f"{raw!r} -> {co!r} / body: {poss!r} website")
        if APPLY:
            p.update(changed_vars)
            body = {"custom_variables": p}
            if name_changed: body["company_name"] = co
            ik("PATCH", f"/leads/{l['id']}", json=body); time.sleep(0.12)

print("\n".join(samples))
print("\nREMOVED (not a fit):"); print("\n".join(removed[:80]))
print("\nTOTALS:", dict(stats), "" if APPLY else "(dry run, nothing changed)")
