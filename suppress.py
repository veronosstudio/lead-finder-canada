"""Never contact an address again: add it to the Instantly blocklist and mark its leads Not Interested.
Usage: python suppress.py email=someone@example.com
"""
import os, sys, json, requests
args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
email = args["email"].strip().lower()
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}", "Content-Type": "application/json"}
API = "https://api.instantly.ai/api/v2"
r = requests.post(f"{API}/block-lists-entries", headers=H, json={"bl_value": email}, timeout=30)
print("blocklist:", r.status_code, r.text[:200])
r = requests.post(f"{API}/leads/update-interest-status", headers=H, json={"lead_email": email, "interest_value": -1}, timeout=30)
print("interest -> not interested:", r.status_code, r.text[:200])
r = requests.post(f"{API}/leads/list", headers=H, json={"search": email, "limit": 10}, timeout=30)
for l in r.json().get("items", []):
    print("lead:", l.get("email"), "campaign:", l.get("campaign"), "interest:", l.get("lt_interest_status"), "status:", l.get("status"))
