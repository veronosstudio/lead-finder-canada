#!/usr/bin/env python3
"""Veronos lead finder (Canada).

Each run:
  1. Pulls small businesses that list a website from OpenStreetMap (Overpass API), one province + category
     group at a time, continuing where the last run stopped (state/progress.json).
  2. Visits each website and scores how dated it looks (no mobile viewport, old copyright year, no HTTPS,
     old builders/tech). Modern sites and chains are dropped.
  3. Keeps only emails the business publishes on its own site (home, contact, about pages).
  4. Writes qualified leads to leads/YYYY-MM-DD.csv and appends everything checked to data/seen.csv
     so nobody is checked or delivered twice.
Stops at the daily target or the time budget, whichever comes first. No paid services, no AI.
"""
import csv, json, os, re, sys, time, random, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config.json")))
if os.environ.get("TEST_LEADS", "").strip().isdigit():  # quick test run: stop after N leads (manual runs only)
    CFG["daily_target"] = int(os.environ["TEST_LEADS"]); CFG["licence_minutes"] = 12; CFG["competitor_minutes"] = 4
STATE = os.path.join(ROOT, "state", "progress.json")
SEEN = os.path.join(ROOT, "data", "seen.csv")
TODAY = dt.date.today().isoformat()
OUT = os.path.join(ROOT, "leads", f"{TODAY}.csv")
START = time.time()
BUDGET = CFG["time_budget_minutes"] * 60
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
YEAR = dt.date.today().year
CONTACTED = set()
def fp(x):
    import hashlib
    return hashlib.sha256(x.strip().lower().encode()).hexdigest()[:20]
FIELDS = ["date", "business", "category", "town", "province", "website", "email", "email_source", "phone",
          "text_line", "dated_score", "why_dated", "osm_id", "service", "first_name", "score", "score_parts", "tier",
          "competitor", "competitor_site", "hook", "since"]
import refine as R
import hooks as H
if os.path.exists(OUT) and open(OUT).readline().strip().split(",") != FIELDS:  # header changed today: start a second file
    OUT = os.path.join(ROOT, "leads", f"{TODAY}-v2.csv")

def log(*a):
    print(f"[{int(time.time()-START):>5}s]", *a, flush=True)

def time_left():
    return BUDGET - (time.time() - START)

# ---------------- state ----------------
def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"step": 0}

def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"), indent=1)

def steps():
    """Every (province, category group) pair, province-major."""
    groups = list(CFG["category_groups"].keys())
    return [(p, g) for p in CFG["provinces"] for g in groups]

def load_seen():
    seen_ids, seen_domains = set(), set()
    ac = os.path.join(ROOT, "data", "already_contacted.txt")
    if os.path.exists(ac):
        for line in open(ac):
            line = line.strip()
            if line and not line.startswith("#"):
                CONTACTED.add(line)
    if os.path.exists(SEEN):
        for r in csv.DictReader(open(SEEN)):
            seen_ids.add(r["osm_id"]); seen_domains.add(r["domain"])
    return seen_ids, seen_domains

def append_seen(rows):
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    new = not os.path.exists(SEEN)
    with open(SEEN, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["osm_id", "domain", "checked", "result"])
        w.writerows(rows)

# ---------------- 1. OpenStreetMap ----------------
def overpass(province, group):
    sel = CFG["category_groups"][group]
    q = f"""[out:json][timeout:240];
area["ISO3166-2"="{province}"]["admin_level"="4"]->.a;
({sel}["website"](area.a);{sel}["contact:website"](area.a););
out tags center;"""
    for attempt in range(6):
        if time_left() < 480:  # not enough time left to query and still check sites; save what we have
            log("overpass: out of time for today"); return None
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=min(300, max(60, time_left() - 360)),
                              headers={"User-Agent": "veronos-lead-finder/1.0"})
            if r.status_code == 200:
                return r.json().get("elements", [])
            log("overpass", url, r.status_code)
        except Exception as e:
            log("overpass error", url, str(e)[:120])
        time.sleep(min(20 + attempt * 15, max(0, time_left() - 480)))
    return None

def norm_site(u):
    u = (u or "").strip().split(";")[0].strip()
    if not u: return ""
    if not u.startswith("http"): u = "http://" + u
    return u

def domain(u):
    d = urlparse(u).netloc.lower()
    return d[4:] if d.startswith("www.") else d

BAD_HOSTS = ("facebook.com", "instagram.com", "linktr.ee", "google.com", "goo.gl", "yelp.", "yellowpages.",
             "canada411", "squareup.com", "square.site", "booksy.com", "vagaro.com", "fresha.com", "wixsite.com/",
             "business.site", "tiktok.com", "twitter.com", "x.com", "youtube.com", "linkedin.com")

def candidates(elements, province, group, seen_ids, seen_domains):
    words = CFG["skip_name_words"]
    by_domain = {}
    for e in elements:
        t = e.get("tags", {})
        name = t.get("name", "").strip()
        site = norm_site(t.get("website") or t.get("contact:website"))
        if not name or not site: continue
        if t.get("brand") or t.get("brand:wikidata"): continue
        if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", name.lower()) for w in words): continue
        if any(b in site.lower() for b in BAD_HOSTS): continue
        d = domain(site)
        if not d: continue
        by_domain.setdefault(d, []).append(e)
    out = []
    for d, es in by_domain.items():
        if len(es) > 2: continue  # same site on 3+ map entries = multi-location / chain
        e = es[0]; oid = f'{e["type"]}/{e["id"]}'
        if oid in seen_ids or d in seen_domains: continue
        t = e["tags"]
        out.append({
            "osm_id": oid, "business": t.get("name", "").strip(), "category": t.get("craft") or t.get("shop") or t.get("healthcare") or t.get("office") or ("church" if t.get("amenity") == "place_of_worship" else group),
            "town": t.get("addr:city", ""), "province": province.split("-")[1],
            "website": norm_site(t.get("website") or t.get("contact:website")), "domain": d,
            "phone": t.get("phone") or t.get("contact:phone", ""),
            "osm_email": t.get("email") or t.get("contact:email", ""),
            "lat": e.get("lat") or (e.get("center") or {}).get("lat", ""), "lon": e.get("lon") or (e.get("center") or {}).get("lon", ""),
        })
    random.shuffle(out)
    return out

# ---------------- 2. how dated is the site ----------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = ("example.", "sample@", "test@", "youremail", "your@", "email@", "johndoe", "janedoe", "john.doe", "mysite", "yoursite", "placeholder", "sentry", "wixpress", "domain.com", "email.com", "yourname", "name@", "user@", "@2x",
              ".png", ".jpg", ".gif", ".webp", ".svg", "godaddy", "squarespace", "noreply", "no-reply")
FREE_MAIL = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.", "telus.net", "telusplanet.net", "shaw.ca",
             "live.com", "live.ca", "icloud.com", "me.com", "sasktel.net", "mts.net", "eastlink.ca", "bell.net",
             "sympatico.ca", "rogers.com", "cogeco.ca", "xplornet.com", "netago.ca", "cable-lynx.net", "msn.com",
             "aol.com", "videotron.ca", "nb.sympatico.ca", "persona.ca", "accesscomm.ca")

PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")

def text_line(html):
    """A number the business says you can TEXT: an sms: link, or 'text us' / 'call or text' next to a number."""
    m = re.search(r'href=["\']sms:([+\d\s().-]{10,20})', html, re.I)
    if m: return re.sub(r"[^\d+]", "", m.group(1))
    plain = re.sub(r"<[^>]+>", " ", html)
    for k in re.finditer(r"(text\s+us|call\s+or\s+text|text\s+or\s+call|txt\s+us|send\s+us\s+a\s+text|text\s+only|texts?\s+welcome)", plain, re.I):
        near = plain[max(0, k.start() - 80): k.end() + 80]
        p = PHONE_RE.search(near)
        if p: return p.group(0).strip()
    return ""

def get(url, s):
    return s.get(url, timeout=15, headers={"User-Agent": UA}, allow_redirects=True)

def score(html, final_url, https_ok):
    reasons, pts = [], 0
    low = html.lower()
    if 'name="viewport"' not in low and "name='viewport'" not in low and "name=viewport" not in low:
        pts += 3; reasons.append("not built for phones")
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", low)]
    if years:
        y = max(years)
        if y <= YEAR - 3: pts += 2; reasons.append(f"copyright {y}")
    if not https_ok:
        pts += 2; reasons.append("no secure https")
    gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if gen:
        g = gen.group(1).lower()
        if any(x in g for x in ("frontpage", "dreamweaver", "iweb", "joomla! 1", "joomla! 2", "homestead", "web.com", "sitebuilder", "website tonight", "yola")):
            pts += 2; reasons.append(f"old builder ({gen.group(1)[:30]})")
        m = re.search(r"wordpress (\d+)\.", g)
        if m and int(m.group(1)) < 5: pts += 1; reasons.append(f"old WordPress {m.group(1)}")
    if re.search(r"jquery[.-]?(1\.\d+)", low): pts += 1; reasons.append("old jQuery")
    if "<table" in low and low.count("<table") >= 3 and "<div" in low and low.count("<div") < 30:
        pts += 1; reasons.append("table layout")
    if ".swf" in low or "shockwave" in low: pts += 2; reasons.append("Flash")
    if "<font" in low: pts += 1; reasons.append("old <font> tags")
    # Owner-built / DIY builders: the sweet spot (most of our hand-picked leads were Wix, Weebly, GoDaddy).
    diy = [("Wix", ("static.wixstatic.com", "wix.com website builder")), ("Weebly", ("weebly.com", "editmysite.com")),
           ("GoDaddy builder", ("img1.wsimg.com", "starfield technologies")), ("Site123", ("site123",)),
           ("Jimdo", ("jimdo",)), ("Webs", ("webs.com",)), ("Yola", ("yola",)), ("Homestead", ("homestead.com",)),
           ("Webnode", ("webnode",)), ("Strikingly", ("strikingly",))]
    for label, marks in diy:
        if any(m in low for m in marks): pts += 2; reasons.append(f"DIY {label} site"); break
    else:
        if "static1.squarespace.com" in low or "duda" in low: pts += 1; reasons.append("template builder")
    if "layerslider" in low or "revslider" in low or "revolution slider" in low: pts += 1; reasons.append("old slider theme")
    if re.search(r"/themes/twenty(ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen)", low): pts += 2; reasons.append("old default theme")
    if "<h1" not in low: pts += 1; reasons.append("no main headline")
    if "tel:" not in low: pts += 1; reasons.append("phone not tappable")
    modern = sum(x in low for x in ("__next", "tailwind", "data-reactroot", "_nuxt", "gatsby", "webflow", "framerusercontent", "astro-island"))
    if modern: pts -= 3 * modern
    if len(low) < 1500: pts -= 2  # parked / redirect stubs are not leads
    return pts, reasons

def emails_from(html, site_domain):
    found = []
    for m in re.findall(r'mailto:([^"\'?>\s]+)', html, re.I) + EMAIL_RE.findall(html):
        e = m.strip().strip(".").lower()
        if not EMAIL_RE.fullmatch(e) or any(j in e for j in JUNK_EMAIL): continue
        dom = e.split("@")[1]
        if dom == site_domain or dom.endswith("." + site_domain) or site_domain.endswith(dom) or any(dom.endswith(f) for f in FREE_MAIL):
            if e not in found: found.append(e)
    return found

def check(c):
    s = requests.Session()
    try:
        try:
            r = get(c["website"].replace("http://", "https://", 1), s); https_ok = r.url.startswith("https://")
        except requests.exceptions.SSLError:
            r = get(c["website"].replace("https://", "http://", 1), s); https_ok = False
        except Exception:
            r = get(c["website"], s); https_ok = r.url.startswith("https://")
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", "text/html"):
            return c, "dead", None
        html = r.text[:600000]
        if domain(r.url) != c["domain"] and any(b in r.url for b in BAD_HOSTS):
            return c, "redirects-away", None
        pts, why = score(html, r.url, https_ok)
        if R.is_chain(c["business"], html):
            return c, "chain", None
        if pts < CFG["min_dated_score"]:
            return c, f"modern({pts})", None
        emails, src = emails_from(html, c["domain"]), r.url
        txt = text_line(html)
        if not emails:
            links = re.findall(r'href=["\']([^"\'#]+)', html, re.I)
            pages = [urljoin(r.url, l) for l in links if re.search(r"contact|about|reach|location|find-us", l, re.I)]
            for extra in ["contact", "contact-us", "contact.html", "contactus.html", "about"]:
                pages.append(urljoin(r.url if r.url.endswith("/") else r.url + "/", extra))
            for p in list(dict.fromkeys(pages))[:5]:
                if domain(p) != domain(r.url): continue
                try:
                    pr = get(p, s)
                    if pr.status_code < 400:
                        emails = emails_from(pr.text[:400000], c["domain"])
                        txt = txt or text_line(pr.text[:400000])
                        if emails: src = pr.url; break
                except Exception:
                    pass
        if not emails:
            return c, f"dated-no-email({pts})", None
        if fp(c["domain"]) in CONTACTED or any(fp(e) in CONTACTED for e in emails):
            return c, "already-contacted", None
        own = [e for e in emails if e.endswith(c["domain"])]
        best = sorted(own or emails, key=lambda e: not R.personal_email(e))[0]   # a person's address beats info@
        why_s = "; ".join(why) + (f"; licensed since {c['since']}" if c.get("since") else "")
        title = (re.search(r"<title[^>]*>([^<]{0,200})", html, re.I) or [None, ""])[1]
        plain = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html))
        svc = R.service_of(c["category"], c["business"], title)
        fname = R.first_name(best, plain)
        sig = R.site_signals(html)
        total, parts = R.score(why_s, svc, c.get("since", ""), sig, "", best, fname, c["phone"], c["category"])
        tier = R.tier_of(total, parts["need"])
        if tier == "skip":
            return c, f"weak({total})", None
        return c, "LEAD", {"date": TODAY, "business": c["business"], "category": c["category"], "town": c["town"],
                           "province": c["province"], "website": r.url, "email": best, "email_source": src,
                           "phone": c["phone"], "text_line": txt, "dated_score": pts, "why_dated": why_s, "osm_id": c["osm_id"],
                           "service": svc, "first_name": fname, "score": total,
                           "score_parts": " ".join(f"{k}={v}" for k, v in parts.items()), "tier": tier,
                           "competitor": "", "competitor_site": "", "hook": H.hook(why_s, sig), "since": c.get("since", "") or "", "_lat": c.get("lat", ""), "_lon": c.get("lon", "")}
    except Exception as e:
        return c, "error:" + type(e).__name__, None

# ---------------- Google Sheet ----------------
DEFAULT_SHEET_URL = "https://script.google.com/macros/s/AKfycbzWsFlBCrg-7bWt35pbDLNzHY3_8mudPtmr8jBnKWUcgnBVcM6iWXhEu-OmsYO7Z14d/exec"

def sheet_creds():
    clean = lambda v: (v or "").strip().strip('"').strip("'").strip()
    url, token = clean(os.environ.get("SHEET_URL")), clean(os.environ.get("SHEET_TOKEN"))
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    return (f"https://script.google.com/macros/s/{m.group(1)}/exec" if m else DEFAULT_SHEET_URL), token

def sheet_get(status="new", limit=5000):
    url, token = sheet_creds()
    if not token: return []
    try:
        return requests.get(url, params={"token": token, "status": status, "limit": limit}, timeout=120).json().get("rows", [])
    except Exception as e:
        log("sheet read failed:", str(e)[:120]); return []

def sheet_update(updates):
    url, token = sheet_creds()
    if not token or not updates: return 0
    done = 0
    for i in range(0, len(updates), 300):
        try:
            j = requests.post(url, data=json.dumps({"token": token, "action": "update", "updates": updates[i:i + 300]}),
                              headers={"Content-Type": "application/json"}, timeout=300).json()
            done += j.get("updated", 0)
            if not j.get("ok"): log("sheet refused update:", str(j.get("error"))[:80])
        except Exception as e:
            log("sheet update failed:", str(e)[:150])
    return done

def parse_parts(s):
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", s or "")}

def competitor_step(leads, budget_s):
    """Give contacts (tonight's + the sheet's backlog) an exact competitor with a genuinely good site; re-score them."""
    import competitors as C
    rows = {l["osm_id"]: l for l in leads if l.get("service")}
    for r in sheet_get("new", 5000):
        if r.get("service") and not r.get("competitor") and r.get("tier") in ("A+", "A", "B") and r["osm_id"] not in rows:
            rows[r["osm_id"]] = r
    contacts = sorted(rows.values(), key=lambda r: -int(r.get("score") or 0))
    if not contacts: return 0
    found = C.match(contacts, sys.modules[__name__], budget_s, log)
    ups = []
    for oid, (name, site) in found.items():
        parts = parse_parts(rows[oid].get("score_parts")); parts["pressure"] = 15
        total = sum(parts.values())
        ups.append({"osm_id": oid, "competitor": name, "competitor_site": site, "score": total,
                    "score_parts": " ".join(f"{k}={v}" for k, v in parts.items()), "tier": R.tier_of(total, parts.get("need", 0))})
    n = sheet_update(ups)
    log(f"competitors: sheet updated {n}")
    return n

def post_to_sheet(leads):
    clean = lambda v: (v or "").strip().strip('"').strip("'").strip()
    url, token = clean(os.environ.get("SHEET_URL")), clean(os.environ.get("SHEET_TOKEN"))
    # The web-app URL isn't secret (it does nothing without the token), so fall back to the known one if the
    # SHEET_URL secret is mangled. Only the token must come from secrets.
    m = re.search(r"macros/s/([A-Za-z0-9_-]{20,})", url)
    url = f"https://script.google.com/macros/s/{m.group(1)}/exec" if m else DEFAULT_SHEET_URL
    if not url or not token or not leads:
        return 0
    added = 0
    for i in range(0, len(leads), 200):
        try:
            r = requests.post(url, data=json.dumps({"token": token, "rows": leads[i:i + 200]}),
                              headers={"Content-Type": "application/json"}, timeout=120, allow_redirects=True)
            j = r.json(); added += j.get("added", 0)
            if not j.get("ok"): log("sheet refused:", str(j.get("error"))[:80], "(check the SHEET_TOKEN secret)")
        except Exception as e:
            log("sheet post failed:", str(e)[:150])
    log("sheet: added", added)
    return added

# ---------------- source 2: city business licences ----------------
def licence_pass(seen_ids, seen_domains, leads, seen_rows, budget_s):
    """Calgary, Edmonton, Red Deer and Vancouver licence lists -> website -> same check. Oldest licences first."""
    import licences as L
    stop_at = time.time() + budget_s
    pool = []
    for name, fn in L.SOURCES.items():
        if name not in CFG.get("licence_sources", list(L.SOURCES)): continue
        n0 = len(pool)
        try:
            for b in fn():
                if b["key"] not in seen_ids: pool.append(b)
        except Exception as e:
            log(f"licence source {name} failed: {str(e)[:120]}")
        log(f"licences: {name} -> {len(pool) - n0} not yet checked")
    pool.sort(key=lambda b: b["since"] or "9999")
    checked = found = 0
    def one(b):
        site = L.find_website(b["name"], b["city"], UA)
        if not site: return b, None, "no-site", None
        d = domain(site)
        if d in seen_domains or fp(d) in CONTACTED: return b, d, "already-seen", None
        c = {"osm_id": b["key"], "business": b["name"].title() if b["name"].isupper() else b["name"], "category": b["cat"],
             "town": b["city"], "province": L.PROVINCE.get(b["city"], ""), "website": site, "domain": d, "phone": "", "osm_email": "",
             "since": b["since"]}
        _, res, lead = check(c)
        return b, d, res, lead
    i = 0
    with ThreadPoolExecutor(CFG.get("licence_workers", 32)) as ex:
        while i < len(pool) and time.time() < stop_at and time_left() > 300 and len(leads) < CFG["daily_target"]:
            batch = pool[i:i + 200]; i += len(batch)
            for fut in as_completed([ex.submit(one, b) for b in batch]):
                b, d, res, lead = fut.result(); checked += 1
                seen_ids.add(b["key"])
                if d: seen_domains.add(d); found += 1
                seen_rows.append([b["key"], d or "", TODAY, res])
                if lead and len(leads) < CFG["daily_target"]:
                    leads.append(lead); log(f"  LEAD [licence] {lead['business']} ({lead['town']}) {lead['email']} :: {lead['why_dated']}")
    log(f"licences: checked {checked}, websites found {found}, {len(pool) - i} left for tomorrow")
    return checked

# ---------------- run ----------------
_FLUSHED = {"leads": 0, "seen": 0}
def flush(leads, seen_rows, state):
    """Write new leads to the CSV, record checked sites, save progress, post new leads to the sheet. Safe to call repeatedly."""
    new_leads, new_seen = leads[_FLUSHED["leads"]:], seen_rows[_FLUSHED["seen"]:]
    _FLUSHED["leads"], _FLUSHED["seen"] = len(leads), len(seen_rows)
    if new_leads:
        write = os.path.exists(OUT)
        with open(OUT, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if not write: w.writeheader()
            w.writerows(new_leads)
    if new_seen: append_seen(new_seen)
    save_state(state)
    added = post_to_sheet([{k: v for k, v in l.items() if not k.startswith("_")} for l in new_leads]) if new_leads else 0
    log(f"saved {len(new_leads)} leads, sheet added {added}")
    return added

def main():
    state = load_state(); plan = steps()
    seen_ids, seen_domains = load_seen()
    leads, seen_rows, checked = [], [], 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Source 2 first (it finds far more), then OpenStreetMap with the time that's left.
    checked += licence_pass(seen_ids, seen_domains, leads, seen_rows, CFG.get("licence_minutes", 34) * 60)
    posted = flush(leads, seen_rows, state)  # checkpoint: licence leads are safe in the sheet before the map part starts
    reserve = 0 if os.environ.get("TEST_LEADS") else CFG.get("competitor_minutes", 12) * 60
    while len(leads) < CFG["daily_target"] and time_left() > 360 + reserve:
        if state["step"] >= len(plan):
            log("All provinces and categories done. Add categories or reset state/progress.json."); break
        prov, group = plan[state["step"]]
        pool = state.get("pool")
        if not pool:
            log(f"querying OpenStreetMap: {prov} / {group}")
            els = overpass(prov, group)
            if els is None:
                log("Overpass unavailable, stopping for today"); break
            pool = candidates(els, prov, group, seen_ids, seen_domains)
            log(f"  {len(els)} map entries -> {len(pool)} new websites to check")
            state["pool"] = pool; save_state(state)
            time.sleep(5)
        batch, rest = pool[:CFG["workers"] * 4], pool[CFG["workers"] * 4:]
        with ThreadPoolExecutor(CFG["workers"]) as ex:
            for fut in as_completed([ex.submit(check, c) for c in batch]):
                c, result, lead = fut.result(); checked += 1
                seen_ids.add(c["osm_id"]); seen_domains.add(c["domain"])
                seen_rows.append([c["osm_id"], c["domain"], TODAY, result])
                if lead and len(leads) < CFG["daily_target"]:
                    leads.append(lead); log(f"  LEAD {lead['business']} ({lead['town']}) {lead['email']} :: {lead['why_dated']}")
        state["pool"] = rest
        if not rest:
            state["step"] += 1; state["pool"] = []
        save_state(state)
        if not batch: continue
    sheet_added = posted + flush(leads, seen_rows, state)
    if time_left() > 180:
        competitor_step(leads, min(CFG.get("competitor_minutes", 12) * 60, time_left() - 120))
    summary = {"date": TODAY, "checked": checked, "leads": len(leads), "step": state["step"], "of": len(plan),
               "at": plan[min(state["step"], len(plan) - 1)], "minutes": round((time.time() - START) / 60, 1), "sheet_added": sheet_added}
    json.dump(summary, open(os.path.join(ROOT, "state", "last_run.json"), "w"), indent=1)
    log("DONE", summary)

if __name__ == "__main__":
    main()
