"""Set daily caps and (re)start the Veronos campaigns. Usage: python set_campaigns.py US=150 CA=300"""
import os, sys, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}", "Content-Type": "application/json"}
API = "https://api.instantly.ai/api/v2"
CAMPS = {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}
want = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
for name, n in want.items():
    cid, n = CAMPS[name], int(n)
    r = requests.patch(f"{API}/campaigns/{cid}", headers=H, json={"daily_limit": n, "daily_max_leads": n}, timeout=30)
    print(name, "caps ->", n, r.status_code, r.text[:150] if not r.ok else "")
    c = requests.get(f"{API}/campaigns/{cid}", headers={"Authorization": H["Authorization"]}, timeout=30).json()
    if c.get("status") != 1:
        a = requests.post(f"{API}/campaigns/{cid}/activate", headers={"Authorization": H["Authorization"]}, timeout=30)
        print(name, "activate:", a.status_code, a.text[:150])
    c = requests.get(f"{API}/campaigns/{cid}", headers={"Authorization": H["Authorization"]}, timeout=30).json()
    print(name, "now: status", c.get("status"), "daily_limit", c.get("daily_limit"), "daily_max_leads", c.get("daily_max_leads"))
