"""One-off campaign fixes through the Instantly API (Kash, Nov 24).

1) Email 1 subject: keep only variant A ("Website for {{companyName}}"), drop variant B.
2) Leads whose business name is just a person's name (e.g. "Martin D Glazer"): companyName becomes
   "your firm" / "your practice" / "your business", only for leads not emailed yet.

  python fix_campaigns.py            read-only: print what would change
  python fix_campaigns.py apply=yes  make the changes
"""
import json, os, re, sys, time
import requests
import refine as R
import export_instantly as X

API = "https://api.instantly.ai/api/v2"
KEY = os.environ["INSTANTLY_API_KEY"].strip()
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def ik(method, path, **kw):
    r = requests.request(method, API + path, headers=H, timeout=60, **kw)
    if not r.ok:
        raise RuntimeError(f"{method} {path} {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def main():
    apply = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a).get("apply") == "yes"
    for country, cid in X.CAMPAIGNS.items():
        c = ik("GET", f"/campaigns/{cid}")
        seqs = c.get("sequences") or []
        step0 = seqs[0]["steps"][0]
        subs = [v.get("subject") for v in step0.get("variants", [])]
        print(f"[{country}] {c.get('name')} status={c.get('status')} email-1 subjects={subs}")
        if len(step0.get("variants", [])) > 1:
            step0["variants"] = step0["variants"][:1]
            if apply:
                ik("PATCH", f"/campaigns/{cid}", json={"sequences": seqs})
                after = ik("GET", f"/campaigns/{cid}")["sequences"][0]["steps"][0]["variants"]
                print(f"  -> now {[v.get('subject') for v in after]}")
            else:
                print("  -> would keep only:", subs[0])
        # Person-named businesses
        fixed = seen = 0
        after_id = None
        while True:
            res = ik("POST", "/leads/list", json={"campaign": cid, "limit": 100, **({"starting_after": after_id} if after_id else {})})
            items = res.get("items") or []
            for l in items:
                seen += 1
                name = l.get("company_name") or ""
                if not X.person_named(name) or l.get("timestamp_last_contact"):
                    continue
                svc = (l.get("payload") or {}).get("service", "")
                new = X.generic_company(svc)
                print(f"  {name!r} -> {new!r} ({l.get('email')})")
                if apply:
                    ik("PATCH", f"/leads/{l['id']}", json={"company_name": new})
                    time.sleep(0.3)
                fixed += 1
            after_id = res.get("next_starting_after")
            if not after_id or not items:
                break
        print(f"[{country}] leads scanned {seen}, person-named not yet emailed: {fixed}{' (fixed)' if apply else ''}")


if __name__ == "__main__":
    main()
