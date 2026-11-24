"""Email v4 (Kash, Nov 24): measurable business cost, 4 emails, signature.

  python load_v4.py mode=vars shard=0 shards=8 apply=yes   fill notice/cost/tip (Google speed test + site checks) on every active lead
  python load_v4.py mode=seq apply=yes                     put the new 4-email sequence into both campaigns
"""
import os, sys, re, time, json, requests
from concurrent.futures import ThreadPoolExecutor
import export_instantly as X
import email_vars as V
import speed as SP

args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
APPLY = args.get("apply") == "yes"
API = "https://api.instantly.ai/api/v2"
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}

SIG = ['<div><br></div>', '<div>Kash Angell</div>', '<div>Veronos Studio · Calgary, AB</div>', '<div><br></div>',
       '<div><span style="font-size:12px;color:#888888">3503 18 St SW, Calgary, AB · Not a fit? Reply "no" and I won\'t follow up.</span></div>']
def body(lines):
    return "".join("<div><br></div>" if l == "" else f"<div>{l}</div>" for l in lines) + "".join(SIG)

E1A = body(["{{greeting}}", "", "Noticed {{coPoss}} website {{notice}} {{cost}}", "",
            "I build websites for local businesses, so I made you a new homepage that fixes it. On the house.", "", "Want to see it?"])
E1B = body(["{{greeting}}", "", "Was looking at {{coPoss}} website and noticed it {{notice}} {{cost}}", "",
            "Easy fix. I already made you a new homepage that solves it, no cost and no catch.", "", "Mind if I send it over?"])
E2 = body(["{{greeting}}", "", "One easy win, even if you never use me: {{tip}}", "", "The homepage I made you is ready whenever you want it."])
E3 = body(["{{greeting}}", "", "Happy to send that homepage over anytime.", "",
           "And if someone else handles your website, let me know who and I'll pass it along."])
E4 = body(["{{greeting}}", "", "Haven't heard back, so I'll close this out. If the website ever moves up the list, just reply here and I'll send the homepage over."])

def ik(method, path, **kw):
    for attempt in range(5):
        r = requests.request(method, API + path, headers=H, timeout=60, **kw)
        if r.status_code == 429: time.sleep(3 + attempt * 3); continue
        if not r.ok: raise RuntimeError(f"{method} {path} {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}
    raise RuntimeError("rate limited")

def sheet_why():
    url, token = os.environ.get("SHEET_URL", "").strip().strip('"\''), os.environ.get("SHEET_TOKEN", "").strip().strip('"\'')
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    out = {}
    if not (url and token): return out
    for st in ("Instantly", "new"):
        try:
            for x in requests.get(url, params={"token": token, "status": st, "limit": "20000"}, timeout=240).json().get("rows", []):
                e = (x.get("email") or "").strip().lower()
                if e: out[e] = x.get("why_dated") or ""
        except Exception as e:
            print("sheet read failed", st, e)
    return out

def mode_vars():
    shard, shards = int(args.get("shard", 0)), int(args.get("shards", 1))
    why = sheet_why(); print("sheet rows with reasons:", len(why))
    leads = []
    for country, cid in X.CAMPAIGNS.items():
        after = None
        while True:
            res = ik("POST", "/leads/list", json={"campaign": cid, "limit": 100, **({"starting_after": after} if after else {})})
            items = res.get("items") or []
            leads += [l for l in items if l.get("status") not in (-1, -2, -3)]
            after = res.get("next_starting_after")
            if not after or not items: break
            time.sleep(0.5)
    leads.sort(key=lambda l: l["email"])
    mine = [l for i, l in enumerate(leads) if i % shards == shard]
    print(f"shard {shard}/{shards}: {len(mine)} of {len(leads)} active leads")
    def site(l):
        w = l.get("website") or (l.get("payload") or {}).get("website") or ""
        return w if w.startswith("http") else ("https://" + w if w else "")
    sites = sorted({site(l) for l in mine if site(l)})
    with ThreadPoolExecutor(8) as ex:
        speeds = dict(zip(sites, ex.map(SP.mobile_load, sites)))
    print("speed measured:", sum(1 for v in speeds.values() if v), "of", len(sites))
    from collections import Counter
    kinds, n = Counter(), 0
    for l in mine:
        p = dict(l.get("payload") or {})
        v = V.build(why.get(l["email"].lower(), ""), p.get("hook", ""), speeds.get(site(l)))
        kinds[v["issue"]] += 1
        want = {"notice": v["notice"], "cost": v["cost"], "tip": v["tip"], "issue": v["issue"], "speed": str(v["speed"])}
        if all(p.get(k) == w for k, w in want.items()): continue
        if n < 3: print(" ", l.get("company_name"), want["notice"], "|", want["cost"])
        n += 1
        if APPLY:
            p.update(want)
            ik("PATCH", f"/leads/{l['id']}", json={"custom_variables": p}); time.sleep(0.12)
    print("issues:", dict(kinds), f"| updated {n}{'' if APPLY else ' (dry run)'}")

def mode_seq():
    for country, cid in X.CAMPAIGNS.items():
        c = ik("GET", f"/campaigns/{cid}")
        seqs = c["sequences"]; steps = seqs[0]["steps"]
        print(f"[{country}] before: steps={len(steps)} delays={[s.get('delay') for s in steps]}")
        a = dict(steps[0]["variants"][0]); b = dict(a); b.pop("id", None)
        a.update({"subject": "{{companyName}} website", "body": E1A, "v_disabled": False})
        b.update({"subject": "quick idea for {{companyName}}", "body": E1B, "v_disabled": False})
        steps[0]["variants"] = [a, b]
        tmpl = steps[-1]
        while len(steps) < 4:
            s = json.loads(json.dumps(tmpl)); s.pop("id", None)
            for v in s.get("variants", []): v.pop("id", None)
            steps.append(s)
        for i, bd in ((1, E2), (2, E3), (3, E4)):
            v = dict(steps[i]["variants"][0]); v.update({"subject": "", "body": bd, "v_disabled": False})
            steps[i]["variants"] = [v]
        for s, d in zip(steps, (3, 4, 6, 1)): s["delay"] = d
        if APPLY:
            ik("PATCH", f"/campaigns/{cid}", json={"sequences": seqs})
            after = ik("GET", f"/campaigns/{cid}")["sequences"][0]["steps"]
            print(f"[{country}] now: steps={len(after)} delays={[s.get('delay') for s in after]} subjects={[[v.get('subject') for v in s['variants']] for s in after]}")
        else:
            print(f"[{country}] would set 4 steps, delays 3/4/6")

if __name__ == "__main__":
    {"vars": mode_vars, "seq": mode_seq}[args.get("mode", "vars")]()
