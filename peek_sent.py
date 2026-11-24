"""Show the most recent emails actually sent from the Veronos inboxes, as the recipient sees them."""
import os, re, requests
from collections import Counter
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}"}
r = requests.get("https://api.instantly.ai/api/v2/emails", headers=H, params={"email_type": "sent", "limit": 100, "sort_order": "desc"}, timeout=60).json()
items = [e for e in r.get("items", []) if "veronos" in str(e.get("eaccount", ""))]
print("recent Veronos sends:", len(items))
issues = Counter()
for e in items:
    body = (e.get("body") or {}).get("text") or re.sub(r"<[^>]+>", "\n", (e.get("body") or {}).get("html", ""))
    body = re.sub(r"\n\s*\n+", "\n", body).strip()
    subj = e.get("subject", "")
    for k, rx in {"leftover {{var}}": r"\{\{", "blank greeting": r"^\s*,", "double space": r"  \w", "website  (empty notice)": r"website\s*\n|website\s*$|website \.", "empty company": r"for\s*$|for \{"}.items():
        if re.search(rx, subj + "\n" + body, re.M): issues[k] += 1
    e["_b"] = body
print("issues:", dict(issues) or "none")
for e in items[:12]:
    print("=" * 70)
    print("TO:", e.get("to_address_email_list"), "| FROM:", e.get("eaccount"), "| at", e.get("timestamp_email"))
    print("SUBJECT:", e.get("subject"))
    print(e["_b"][:700])
