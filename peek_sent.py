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
print("subjects:", Counter(("made this" if "made this" in (e.get("subject") or "") else "Website for" if "Website for" in (e.get("subject") or "") else e.get("subject")) for e in items))
print("footer present:", Counter("3503 18 St" in e["_b"] for e in items), "| opt-out line:", Counter("no thanks" in e["_b"].lower() for e in items))
raw = items[0].get("body") or {}
print("RAW HTML of newest:", (raw.get("html") or "")[:1500])
for name, cid in {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}.items():
    c = requests.get(f"https://api.instantly.ai/api/v2/campaigns/{cid}", headers=H, timeout=30).json()
    st = c["sequences"][0]["steps"][0]
    for v in st["variants"]: print("LIVE", name, repr(v.get("subject")), repr(v.get("body", "")[:900]))
notices = Counter()
for e in items:
    m = re.search(r"website (.{0,80})", e["_b"]); notices[(m.group(1)[:45] if m else "NONE")] += 1
print("notice openings:", notices.most_common(12))
print("greetings:", Counter(e["_b"].split("\n")[0][:25] for e in items).most_common(10))
print("html has img/pixel:", Counter(bool(re.search(r"<img|track|pixel", (e.get("body") or {}).get("html", ""), re.I)) for e in items))
print("links in body:", Counter(bool(re.search(r"https?://", e["_b"])) for e in items))
for name, cid in {"US": "57499a6b-49f7-4980-8b5f-41dd5d3425aa", "CA": "93613104-97b7-48a7-8c5b-94a221afc620"}.items():
    c = requests.get(f"https://api.instantly.ai/api/v2/campaigns/{cid}", headers=H, timeout=30).json()
    print("SETTINGS", name, {k: c.get(k) for k in ("open_tracking", "link_tracking", "text_only", "first_email_text_only", "stop_on_reply", "stop_on_auto_reply", "insert_unsubscribe_header", "prioritize_new_leads", "match_lead_esp", "email_gap", "random_wait_max", "daily_limit", "daily_max_leads", "email_list")})
for e in items[:25]:
    print("=" * 70)
    print("TO:", e.get("to_address_email_list"), "| FROM:", e.get("eaccount"), "| at", e.get("timestamp_email"))
    print("SUBJECT:", e.get("subject"))
    print(e["_b"][:700])
