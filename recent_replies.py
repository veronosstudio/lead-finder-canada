"""Read-only: every reply to a Veronos inbox in the last 4 days, with Instantly's label."""
import os, re, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}"}
r = requests.get("https://api.instantly.ai/api/v2/emails", headers=H, params={"email_type": "received", "limit": 100, "sort_order": "desc"}, timeout=60).json()
for e in r.get("items", []):
    if "veronos" not in str(e.get("eaccount", "")): continue
    body = ((e.get("body") or {}).get("text") or e.get("content_preview") or "").strip().replace("\n", " ")
    print(e.get("timestamp_email", "")[:16], "| label", e.get("i_status"), "|", e.get("from_address_email"), "|", body[:160])
