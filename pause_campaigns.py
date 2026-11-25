"""Pause or resume both Veronos campaigns.  python pause_campaigns.py pause|resume"""
import os, sys, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}"}
act = "pause" if (sys.argv[1:] or ["pause"])[0] == "pause" else "activate"
for name, cid in {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}.items():
    r = requests.post(f"https://api.instantly.ai/api/v2/campaigns/{cid}/{act}", headers=H, timeout=60)
    c = requests.get(f"https://api.instantly.ai/api/v2/campaigns/{cid}", headers=H, timeout=60).json()
    print(name, act, r.status_code, "-> status", c.get("status"), "| schedule", c.get("campaign_schedule"), "| daily", c.get("daily_limit"))
