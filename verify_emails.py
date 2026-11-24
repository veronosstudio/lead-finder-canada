"""Check every not-yet-bounced lead in the Veronos campaigns with Reacher (check-if-email-exists).
Writes verify_<shard>.csv. With apply=yes, deletes leads Reacher says are INVALID from their campaign.
Usage: python verify_emails.py shard=0 shards=8 apply=no
"""
import os, sys, csv, json, subprocess, time, requests
from concurrent.futures import ThreadPoolExecutor
args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
SHARD, SHARDS, APPLY = int(args.get("shard", 0)), int(args.get("shards", 1)), args.get("apply") == "yes"
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}", "Content-Type": "application/json"}
API = "https://api.instantly.ai/api/v2"
CAMPS = {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}
BIN = os.environ.get("REACHER_BIN", "./check_if_email_exists")

def leads(cid):
    out, after = [], None
    while True:
        body = {"campaign": cid, "limit": 100}
        if after: body["starting_after"] = after
        for i in range(5):
            r = requests.post(f"{API}/leads/list", headers=H, json=body, timeout=60)
            if r.status_code == 429: time.sleep(5); continue
            r.raise_for_status(); break
        j = r.json(); out += j.get("items", [])
        after = j.get("next_starting_after")
        if not after or not j.get("items"): return out
        time.sleep(0.6)

def check(email):
    try:
        p = subprocess.run([BIN, "--from-email", "hello@veronosstudio.com", "--hello-name", "veronosstudio.com", email],
                           capture_output=True, text=True, timeout=90)
        j = json.loads(p.stdout)
        smtp = j.get("smtp") or {}
        return {"result": j.get("is_reachable", "unknown"),
                "catch_all": smtp.get("is_catch_all") if isinstance(smtp, dict) else "",
                "deliverable": smtp.get("is_deliverable") if isinstance(smtp, dict) else "",
                "mx": bool((j.get("mx") or {}).get("accepts_mail")) if isinstance(j.get("mx"), dict) else "",
                "err": "" if p.returncode == 0 else p.stderr[-200:]}
    except Exception as e:
        return {"result": "unknown", "catch_all": "", "deliverable": "", "mx": "", "err": str(e)[:200]}

rows = []
for name, cid in CAMPS.items():
    for l in leads(cid):
        if l.get("status") in (-1, -2, -3): continue          # already bounced / unsubscribed / skipped
        rows.append({"country": name, "id": l["id"], "email": l["email"].lower(), "contacted": bool(l.get("email_open_count") is not None and l.get("timestamp_last_contact"))})
rows.sort(key=lambda r: r["email"])
mine = [r for i, r in enumerate(rows) if i % SHARDS == SHARD]
print(f"shard {SHARD}/{SHARDS}: {len(mine)} of {len(rows)} leads")
with ThreadPoolExecutor(24) as ex:
    for r, res in zip(mine, ex.map(lambda r: check(r["email"]), mine)): r.update(res)
from collections import Counter
print("results:", Counter(r["result"] for r in mine))
deleted = 0
if APPLY:
    for r in mine:
        if r["result"] == "invalid":
            d = requests.delete(f"{API}/leads/{r['id']}", headers=H, timeout=30)
            r["deleted"] = d.status_code; deleted += d.ok; time.sleep(0.4)
    print("deleted invalid:", deleted)
with open(f"verify_{SHARD}.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["country", "email", "result", "catch_all", "deliverable", "mx", "contacted", "id", "deleted", "err"], extrasaction="ignore")
    w.writeheader(); w.writerows(mine)
