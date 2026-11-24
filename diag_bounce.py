"""Bounce diagnostics: campaign stats + a sample of bounced leads, and whether this runner can reach port 25."""
import os, json, socket, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}", "Content-Type": "application/json"}
API = "https://api.instantly.ai/api/v2"
CAMPS = {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}
for name, cid in CAMPS.items():
    r = requests.get(f"{API}/campaigns/analytics", headers=H, params={"id": cid}, timeout=30)
    try:
        a = r.json(); a = a[0] if isinstance(a, list) and a else a
        print(name, {k: a.get(k) for k in ["leads_count", "contacted_count", "emails_sent_count", "bounced_count", "reply_count", "unsubscribed_count", "open_count"]})
    except Exception as e:
        print(name, r.status_code, r.text[:300])
# bounced leads sample (status -1 = bounced in Instantly lead status)
bounced, after = [], None
for _ in range(30):
    body = {"limit": 100, "filter": "FILTER_VAL_BOUNCED"}
    if after: body["starting_after"] = after
    r = requests.post(f"{API}/leads/list", headers=H, json=body, timeout=30)
    if r.status_code != 200: print("list", r.status_code, r.text[:200]); break
    j = r.json(); bounced += j.get("items", [])
    after = j.get("next_starting_after")
    if not after or not j.get("items"): break
print("bounced leads:", len(bounced))
from collections import Counter
dom = Counter(l["email"].split("@")[1] for l in bounced)
loc = Counter(l["email"].split("@")[0] for l in bounced)
print("top domains:", dom.most_common(10))
print("top local parts:", loc.most_common(10))
print("campaign split:", Counter(str(l.get("campaign")) for l in bounced))
for l in bounced[:15]: print(" ", l["email"], l.get("status"), (l.get("payload") or {}).get("emailType"))
json.dump([l["email"] for l in bounced], open("bounced.json", "w"))
for host in ["gmail-smtp-in.l.google.com", "mx1.hotmail.com"]:
    s = socket.socket(); s.settimeout(8)
    try:
        s.connect((host, 25)); print("port25", host, "OPEN:", s.recv(100)[:60])
    except Exception as e:
        print("port25", host, "BLOCKED:", e)
    finally: s.close()
