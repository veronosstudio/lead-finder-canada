"""Read-only: 30 random waiting leads per campaign, rendered exactly as email 1 will read."""
import os, random, time, requests
import export_instantly as X
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY'].strip()}", "Content-Type": "application/json"}
random.seed(11)
for country, cid in X.CAMPAIGNS.items():
    after, leads = None, []
    while True:
        r = requests.post("https://api.instantly.ai/api/v2/leads/list", headers=H, json={"campaign": cid, "limit": 100, **({"starting_after": after} if after else {})}, timeout=60).json()
        items = r.get("items") or []
        leads += [l for l in items if not l.get("timestamp_last_contact") and l.get("status") not in (-1, -2, -3, 3)]
        after = r.get("next_starting_after")
        if not after or not items: break
        time.sleep(0.4)
    print(f"##### {country}: {len(leads)} waiting")
    for i, l in enumerate(random.sample(leads, min(30, len(leads)))):
        p = l.get("payload") or {}
        if i % 2 == 0:
            subj, line = p.get("subjA", "?"), f"Noticed {p.get('coPoss','?')} website {p.get('notice','?')} {p.get('cost','')}"
        else:
            subj, line = f"quick idea for {l.get('company_name') or '?'}", f"Was looking at {p.get('coPoss','?')} website and noticed it {p.get('notice','?')} {p.get('cost','')}"
        print(f"[{p.get('emailType','?'):7}] {l['email']}\n   SUBJECT: {subj}\n   {p.get('greeting','?')} {line}\n   site: {l.get('website') or p.get('website','')}")
