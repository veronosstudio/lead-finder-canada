"""Delete the leads listed in bad_leads.json (Reacher said invalid / mailbox refuses mail) from Instantly,
and mark them "Bad email" in the Master Contacts sheet so they're never pushed again."""
import os, json, time, re, requests
H = {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}", "Content-Type": "application/json"}
bad = json.load(open("bad_leads.json"))
ok = fail = 0
for b in bad:
    for i in range(4):
        r = requests.delete(f"https://api.instantly.ai/api/v2/leads/{b['id']}", headers={"Authorization": H["Authorization"]}, timeout=30)
        if r.status_code == 429: time.sleep(4); continue
        break
    if r.ok or r.status_code == 404: ok += 1
    else: fail += 1; print("fail", b["email"], r.status_code, r.text[:120])
    time.sleep(0.35)
print(f"deleted {ok} of {len(bad)} ({fail} failed)")
url, token = os.environ.get("SHEET_URL", "").strip().strip('"\''), os.environ.get("SHEET_TOKEN", "").strip().strip('"\'')
if url and token:
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m: url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    emails = {b["email"] for b in bad}
    rows = []
    for st in ("Instantly", "new"):
        rows += requests.get(url, params={"token": token, "status": st, "limit": "20000"}, timeout=180).json().get("rows", [])
    ups = [{"osm_id": x["osm_id"], "status": "Bad email"} for x in rows if (x.get("email") or "").strip().lower() in emails]
    done = 0
    for i in range(0, len(ups), 300):
        done += requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": ups[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json().get("updated", 0)
    print(f"marked {done} sheet rows as Bad email")
