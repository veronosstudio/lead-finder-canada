"""Recheck leads that only had a shared inbox (info@, office@...) with the deeper owner-email search.

Kash (Nov 24): owner emails first, shared inboxes are fine but not top priority.
For every lead in the sheet (US + CA) whose email_type is "general" or "named":
  - re-read the site: homepage + up to 10 people/contact pages, including hidden (Cloudflare / [at] [dot]) emails
  - pick the best contact again (owner > manager > named > best shared inbox)
  - if it's an upgrade (general -> owner/manager/named, or named -> owner/manager) with a different email, it's a swap.

Dry run by default: writes recheck.csv with every upgrade found.
  python recheck_emails.py                    dry run (all shards)
  python recheck_emails.py apply=yes          swap in Instantly (only leads not emailed yet) + update the sheet row
Sharding: SHARD / SHARDS env (same as the finder).
"""
import csv, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
import requests
import finder as F
import people as P
import export_instantly as X

RANK = {"owner": 0, "manager": 1, "named": 2, "general": 3}
API = "https://api.instantly.ai/api/v2"


def recheck(x):
    site = (x.get("website") or "").strip()
    if not site:
        return x, None
    s = requests.Session()
    try:
        try:
            r = F.get(site.replace("http://", "https://", 1), s)
        except Exception:
            r = F.get(site, s)
        if r.status_code >= 400:
            return x, None
        html = r.text[:600000]
        dom = F.domain(r.url) or X.dom(site)
        emails = F.emails_from(html, dom)
        texts = [P.plain(html)]
        pages = P.team_links(r.url, html, limit=8)
        base = r.url if r.url.endswith("/") else r.url + "/"
        pages += [urljoin(base, p) for p in F.DEEP_PAGES]
        for p in list(dict.fromkeys(pages))[:F.MAX_PAGES]:
            if F.domain(p) != F.domain(r.url):
                continue
            try:
                pr = F.get(p, s)
                if pr.status_code < 400:
                    ph = pr.text[:400000]
                    for e in F.emails_from(ph, dom):
                        if e not in emails:
                            emails.append(e)
                    texts.append(P.plain(ph))
            except Exception:
                pass
        if not emails:
            return x, None
        own = [e for e in emails if e.endswith(dom)]
        who = P.best_contact(own or emails, "\n".join(texts))
        if not who:
            return x, None
        old_t, new_t = (x.get("email_type") or "general").lower(), who["email_type"]
        if who["email"].lower() == (x.get("email") or "").lower() or RANK.get(new_t, 3) >= RANK.get(old_t, 3):
            return x, None
        return x, who
    except Exception:
        return x, None


def ik(method, path, key, **kw):
    r = requests.request(method, API + path, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=60, **kw)
    if not r.ok:
        raise RuntimeError(f"{path} {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


def swap(x, who, key, url, token):
    """Replace the lead in Instantly if they haven't been emailed yet, then update the sheet row."""
    country = (x.get("country") or "CA").upper()
    camp = X.CAMPAIGNS[country]
    found = ik("POST", "/leads/list", key, json={"campaign": camp, "search": x["email"], "limit": 5}).get("items", [])
    old = next((l for l in found if (l.get("email") or "").lower() == x["email"].lower()), None)
    if not old:
        return "old lead not in campaign"
    if old.get("timestamp_last_contact") or int(old.get("email_reply_count") or 0) or int(old.get("status") or 1) not in (1,):
        return "already emailed, left as is"
    fn = who["first_name"]
    p = dict(old.get("payload") or {})
    p.update({"greeting": X.hey(fn), "emailType": who["email_type"]})
    new = {"email": who["email"], "first_name": fn or None, "company_name": old.get("company_name"), "website": old.get("website"),
           "phone": old.get("phone"), "custom_variables": {k: v for k, v in p.items() if v not in (None, "")}}
    ik("POST", "/leads/add", key, json={"campaign_id": camp, "skip_if_in_workspace": True, "leads": [new]})
    ik("DELETE", f"/leads/{old['id']}", key)
    requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": [{
        "osm_id": x["osm_id"], "email": who["email"], "email_type": who["email_type"], "first_name": fn,
        "contact_role": who["contact_role"]}]}), headers={"Content-Type": "application/json"}, timeout=120)
    return "swapped"


def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    apply = args.get("apply") == "yes"
    url = os.environ["SHEET_URL"].strip().strip('"\'')
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    if m:
        url = f"https://script.google.com/macros/s/{m.group(1)}/exec"
    token = os.environ["SHEET_TOKEN"].strip().strip('"\'')
    rows = requests.get(url, params={"token": token, "limit": "20000"}, timeout=180).json().get("rows", [])
    rows = [x for x in rows if x.get("email") and (x.get("status") or "").lower() in ("new", "instantly")
            and (x.get("email_type") or "general").lower() in ("general", "named")]
    shard, shards = int(os.environ.get("SHARD", 0)), int(os.environ.get("SHARDS", 1))
    rows = [x for i, x in enumerate(rows) if i % shards == shard]
    print(f"rechecking {len(rows)} leads (shard {shard}/{shards})")
    t0, ups = time.time(), []
    with ThreadPoolExecutor(12) as ex:
        for x, who in ex.map(recheck, rows):
            if who:
                ups.append((x, who))
    print(f"found {len(ups)} better contacts in {int(time.time() - t0)}s")
    key = os.environ.get("INSTANTLY_API_KEY", "").strip()
    with open("recheck.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country", "business", "old_email", "old_type", "new_email", "new_type", "greet", "result"])
        for x, who in ups:
            res = "dry run"
            if apply and key:
                try:
                    res = swap(x, who, key, url, token)
                    time.sleep(0.4)
                except Exception as e:
                    res = "error: " + str(e)[:120]
            w.writerow([x.get("country"), x.get("business"), x.get("email"), x.get("email_type"), who["email"], who["email_type"], who["first_name"], res])
    print("done: see recheck.csv")


if __name__ == "__main__":
    main()
