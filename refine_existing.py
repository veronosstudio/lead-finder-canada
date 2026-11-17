"""One-off (re-runnable) upgrade of contacts already in Master Contacts (status=new):
re-check each site, then set service, first_name, score, score_parts, tier (A+/A/B/skip), and find competitors.
Sites that died, got redesigned, or turn out to be chains/franchises become tier "skip" (never deleted)."""
import os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import finder as F
import refine as R

def recheck(r):
    try:
        s = requests.Session()
        url = r["website"]
        try:
            resp = F.get(url.replace("http://", "https://", 1), s); https_ok = resp.url.startswith("https://")
        except requests.exceptions.SSLError:
            resp = F.get(url.replace("https://", "http://", 1), s); https_ok = False
        if resp.status_code >= 400:
            return r, {"tier": "skip", "score": 0, "score_parts": "site down"}
        html = resp.text[:600000]
        if R.is_chain(r["business"], html):
            return r, {"tier": "skip", "score": 0, "score_parts": "chain/franchise"}
        pts, why = F.score(html, resp.url, https_ok)
        since = (re.search(r"licensed since (\d{4})", r.get("why_dated", "")) or [None, ""])[1]
        why_s = "; ".join(why) + (f"; licensed since {since}" if since else "")
        if pts < F.CFG["min_dated_score"]:
            return r, {"tier": "skip", "score": 0, "score_parts": f"site now modern ({pts})"}
        title = (re.search(r"<title[^>]*>([^<]{0,200})", html, re.I) or [None, ""])[1]
        plain = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html))
        svc = R.service_of(r.get("category", ""), r["business"], title)
        fname = R.first_name(r["email"], plain)
        total, parts = R.score(why_s, svc, since, R.site_signals(html), "", r["email"], fname, r.get("phone", ""), r.get("category", ""))
        return r, {"service": svc, "first_name": fname, "score": total, "tier": R.tier_of(total, parts["need"]),
                   "score_parts": " ".join(f"{k}={v}" for k, v in parts.items())}
    except Exception as e:
        return r, None   # network hiccup: leave the row as it is

def retier():
    """Re-label existing contacts with the yay/nay rule, from their stored score (no site re-checks)."""
    ups = []
    for r in F.sheet_get("new", 10000):
        sp = r.get("score_parts") or ""
        if not sp.startswith("need"): continue          # hard skips (site down / chain / redesigned) stay skipped
        parts = F.parse_parts(sp)
        t = R.tier_of(sum(parts.values()), parts.get("need", 0))
        if t != r.get("tier"): ups.append({"osm_id": r["osm_id"], "tier": t})
    from collections import Counter
    F.log("retier:", len(ups), "changed", dict(Counter(u["tier"] for u in ups)))
    F.log("retier: sheet updated", F.sheet_update(ups))

def main():
    if "retier" in sys.argv:
        return retier()
    redo = "redo" in sys.argv
    rows = [r for r in F.sheet_get("new", 10000) if redo or not r.get("score")]
    F.log(f"refine: {len(rows)} contacts to upgrade")
    ups = []
    with ThreadPoolExecutor(16) as ex:
        for fut in as_completed([ex.submit(recheck, r) for r in rows]):
            r, u = fut.result()
            if u:
                u["osm_id"] = r["osm_id"]
                if redo: u.update({"competitor": "", "competitor_site": ""})
                ups.append(u)
    from collections import Counter
    F.log("refine: tiers", dict(Counter(u["tier"] for u in ups)))
    F.log("refine: sheet updated", F.sheet_update(ups))
    budget = max(60, F.time_left() - 120)
    F.competitor_step([], budget)
    F.log("refine: DONE")

if __name__ == "__main__":
    main()
