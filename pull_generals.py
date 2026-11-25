"""Kash (Nov 24): take not-yet-emailed shared inboxes (info@, office@...) out of the Veronos campaigns so
owners and named people go first. Their sheet rows go back to "new" so the top-up can add them later.
Usage: python pull_generals.py apply=yes"""
import os, sys, re, json, time, requests
import export_instantly as X
APPLY = "apply=yes" in sys.argv
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}
API = "https://api.instantly.ai/api/v2"
PEOPLE = {"owner", "manager", "named"}
pulled = []
for country, cid in X.CAMPAIGNS.items():
    after, n_keep, n_pull = None, 0, 0
    while True:
        r = requests.post(f"{API}/leads/list", headers=H, json={"campaign": cid, "limit": 100, **({"starting_after": after} if after else {})}, timeout=60)
        if r.status_code == 429: time.sleep(5); continue
        j = r.json(); items = j.get("items") or []
        for l in items:
            p = l.get("payload") or {}
            contacted = bool(l.get("timestamp_last_contact")) or int(l.get("email_reply_count") or 0) > 0
            if contacted or l.get("status") in (-1, -2, -3): continue
            if (p.get("emailType") or "").lower() in PEOPLE: n_keep += 1; continue
            n_pull += 1; pulled.append(l["email"].lower())
            if APPLY:
                for i in range(4):
                    d = requests.delete(f"{API}/leads/{l['id']}", headers={"Authorization": H["Authorization"]}, timeout=30)
                    if d.status_code == 429: time.sleep(4); continue
                    break
                time.sleep(0.3)
        after = j.get("next_starting_after")
        if not after or not items: break
        time.sleep(0.5)
    print(f"[{country}] keeping {n_keep} owner/manager/named waiting, pulled {n_pull} shared inboxes{'' if APPLY else ' (dry run)'}")
url, token = os.environ.get("SHEET_URL", "").strip().strip('"\''), os.environ.get("SHEET_TOKEN", "").strip().strip('"\'')
m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
if APPLY and url and token and pulled:
    want = set(pulled)
    rows = requests.get(url, params={"token": token, "status": "Instantly", "limit": "30000"}, timeout=300).json().get("rows", [])
    ups = [{"osm_id": x["osm_id"], "status": "new"} for x in rows if (x.get("email") or "").strip().lower() in want]
    done = 0
    for i in range(0, len(ups), 300):
        done += requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json().get("updated", 0)
    print(f"sheet: {done} rows set back to new (held for later)")
