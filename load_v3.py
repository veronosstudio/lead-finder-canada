"""Email v3 (Kash, Nov 24): short, 1-to-1, "I made you a free homepage".

1) Every lead in both Veronos campaigns gets two custom variables:
     notice  "is pretty tough to use on a phone." / "could use a refresh." / ...
     coPoss  "Ben's Machining's" / "Jones Electrical Services'" / "your practice's"
2) The sequence in both campaigns becomes:
     Email 1  A subject "Website for {{companyName}}"  B subject "made this for {{companyName}}"  (same body)
     Email 2  day 3 bump      Email 3  day 7 last note
   Waits stay as they are.

  python load_v3.py            read-only: show current sequence + a sample of lead changes
  python load_v3.py apply=yes  make the changes
"""
import os, sys, time
import requests
import export_instantly as X

API = "https://api.instantly.ai/api/v2"
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}
FOOT = '<div><br></div><div>--</div><div>Veronos Studio, 3503 18 St SW, Calgary, AB</div><div>If you\'d rather not hear from me, just reply "no thanks".</div>'

def div(lines):
    return "".join("<div><br></div>" if l == "" else f"<div>{l}</div>" for l in lines) + FOOT

E1 = div(["{{greeting}}", "", "Noticed {{coPoss}} website {{notice}}", "",
          "I build websites for local businesses, so I made you a free homepage. On the house.", "",
          "Want to see it?", "", "Kash"])
E2 = div(["{{greeting}}", "", "Just bumping this in case it got buried. Your new homepage is ready whenever you want it.", "", "Kash"])
E3 = div(["{{greeting}}", "", "Last one from me. Happy to send that homepage over anytime.", "",
          "And if someone else handles your website, let me know who and I'll pass it along.", "", "Kash"])


def ik(method, path, **kw):
    for attempt in range(4):
        r = requests.request(method, API + path, headers=H, timeout=60, **kw)
        if r.status_code == 429:
            time.sleep(3 + attempt * 3); continue
        if not r.ok:
            raise RuntimeError(f"{method} {path} {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}
    raise RuntimeError(f"{method} {path} rate limited")


def main():
    apply = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a).get("apply") == "yes"
    for country, cid in X.CAMPAIGNS.items():
        c = ik("GET", f"/campaigns/{cid}")
        seqs = c["sequences"]
        steps = seqs[0]["steps"]
        print(f"[{country}] {c['name']} steps={len(steps)} delays={[s.get('delay') for s in steps]}")
        print("  current step1 variant keys:", list(steps[0]["variants"][0].keys()))
        a = dict(steps[0]["variants"][0]); b = dict(a)
        a.update({"subject": "Website for {{companyName}}", "body": E1})
        b.update({"subject": "made this for {{companyName}}", "body": E1})
        b.pop("id", None)
        steps[0]["variants"] = [a, b]
        for i, body in ((1, E2), (2, E3)):
            v = dict(steps[i]["variants"][0]); v.update({"subject": "", "body": body})
            steps[i]["variants"] = [v]
        if apply:
            ik("PATCH", f"/campaigns/{cid}", json={"sequences": seqs})
            after = ik("GET", f"/campaigns/{cid}")["sequences"][0]["steps"]
            print("  now:", [[v.get("subject") for v in s["variants"]] for s in after], "delays", [s.get("delay") for s in after])
            print("  email1 body starts:", after[0]["variants"][0]["body"][:160])
        # leads: add notice + coPoss
        n = 0; after_id = None
        while True:
            res = ik("POST", "/leads/list", json={"campaign": cid, "limit": 100, **({"starting_after": after_id} if after_id else {})})
            items = res.get("items") or []
            for l in items:
                p = dict(l.get("payload") or {})
                want = {"notice": X.notice_line(p.get("hook", "")), "coPoss": X.co_poss(l.get("company_name") or p.get("companyName", ""))}
                if p.get("notice") == want["notice"] and p.get("coPoss") == want["coPoss"]:
                    continue
                if n < 4: print(f"  {l.get('company_name')!r}: {want}")
                n += 1
                if apply:
                    p.update(want)
                    ik("PATCH", f"/leads/{l['id']}", json={"custom_variables": p})
                    time.sleep(0.15)
            after_id = res.get("next_starting_after")
            if not after_id or not items: break
        print(f"[{country}] leads updated: {n}{'' if apply else ' (dry run)'}")


if __name__ == "__main__":
    main()
