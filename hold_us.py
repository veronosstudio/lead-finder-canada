"""Kash (Nov 26): US campaign doesn't send until a given date (Thanksgiving); Canada keeps going.
python hold_us.py 2026-11-30"""
import os, sys, json, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}
API = "https://api.instantly.ai/api/v2"; US = "57499a6b-49f7-4980-8b5f-41dd5d3425aa"
day = sys.argv[1]
c = requests.get(f"{API}/campaigns/{US}", headers=H, timeout=60).json()
sch = c["campaign_schedule"]; sch["start_date"] = day
r = requests.patch(f"{API}/campaigns/{US}", headers=H, json={"campaign_schedule": sch}, timeout=60)
print("patch", r.status_code, r.text[:200])
c = requests.get(f"{API}/campaigns/{US}", headers=H, timeout=60).json()
print("US status", c.get("status"), "| schedule", json.dumps(c.get("campaign_schedule")))
