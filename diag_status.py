"""Campaign + inbox health snapshot."""
import os, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}"}
API = "https://api.instantly.ai/api/v2"
for name, cid in {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}.items():
    c = requests.get(f"{API}/campaigns/{cid}", headers=H, timeout=30).json()
    a = requests.get(f"{API}/campaigns/analytics", headers=H, params={"id": cid}, timeout=30).json()
    a = a[0] if isinstance(a, list) and a else a
    print(name, "status:", c.get("status"), "| leads", a.get("leads_count"), "contacted", a.get("contacted_count"), "sent", a.get("emails_sent_count"), "bounced", a.get("bounced_count"), "replies", a.get("reply_count"))
r = requests.get(f"{API}/accounts", headers=H, params={"limit": 100}, timeout=30).json()
for acc in r.get("items", []):
    if "veronos" not in acc.get("email", ""): continue
    print(" ", acc.get("email"), "status", acc.get("status"), "warmup", acc.get("warmup_status"), "score", acc.get("stat_warmup_score"), "limit", acc.get("daily_limit"))
try:
    w = requests.post(f"{API}/accounts/warmup-analytics", headers={**H, "Content-Type": "application/json"},
                      json={"emails": [a["email"] for a in r.get("items", []) if "veronos" in a.get("email", "")]}, timeout=30).json()
    for e, v in (w.get("aggregate_data") or {}).items():
        print("  warm", e, {k: v.get(k) for k in ("health_score", "sent", "landed_inbox", "landed_spam", "received")})
except Exception as e:
    print("warmup analytics n/a", e)

import re as _re
for name, cid in {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}.items():
    c = requests.get(f"{API}/campaigns/{cid}", headers=H, timeout=30).json()
    for seq in c.get("sequences", []):
        for i, st in enumerate(seq.get("steps", []), 1):
            for v in st.get("variants", []):
                body = _re.sub(r"<[^>]+>", "\n", v.get("body", "")); body = _re.sub(r"\n\s*\n+", " / ", body).strip()
                print(f"SEQ {name} step{i} delay={st.get('delay')} disabled={v.get('v_disabled')} subj={v.get('subject')!r} body={body[:260]!r}")
