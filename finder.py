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
          "text_line", "dated_score", "why_dated", "osm_id"]

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
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=300, headers={"User-Agent": "veronos-lead-finder/1.0"})
            if r.status_code == 200:
                return r.json().get("elements", [])
            log("overpass", url, r.status_code)
        except Exception as e:
            log("overpass error", url, str(e)[:120])
        time.sleep(20 + attempt * 15)
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
        })
    random.shuffle(out)
    return out

# ---------------- 2. how dated is the site ----------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = ("example.", "sentry", "wixpress", "domain.com", "email.com", "yourname", "name@", "user@", "@2x",
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
        best = (own or emails)[0]
        return c, "LEAD", {"date": TODAY, "business": c["business"], "category": c["category"], "town": c["town"],
                           "province": c["province"], "website": r.url, "email": best, "email_source": src,
                           "phone": c["phone"], "text_line": txt, "dated_score": pts, "why_dated": "; ".join(why), "osm_id": c["osm_id"]}
    except Exception as e:
        return c, "error:" + type(e).__name__, None

# ---------------- Google Sheet ----------------
def post_to_sheet(leads):
    url, token = os.environ.get("SHEET_URL"), os.environ.get("SHEET_TOKEN")
    if not url or not token or not leads:
        return 0
    added = 0
    for i in range(0, len(leads), 200):
        try:
            r = requests.post(url, data=json.dumps({"token": token, "rows": leads[i:i + 200]}),
                              headers={"Content-Type": "application/json"}, timeout=120, allow_redirects=True)
            added += r.json().get("added", 0)
        except Exception as e:
            log("sheet post failed:", str(e)[:150])
    log("sheet: added", added)
    return added

# ---------------- run ----------------
def main():
    state = load_state(); plan = steps()
    seen_ids, seen_domains = load_seen()
    leads, seen_rows, checked = [], [], 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    while len(leads) < CFG["daily_target"] and time_left() > 240:
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
    write = os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not write: w.writeheader()
        w.writerows(leads)
    append_seen(seen_rows)
    save_state(state)
    sheet_added = post_to_sheet(leads)
    summary = {"date": TODAY, "checked": checked, "leads": len(leads), "step": state["step"], "of": len(plan),
               "at": plan[min(state["step"], len(plan) - 1)], "minutes": round((time.time() - START) / 60, 1), "sheet_added": sheet_added}
    json.dump(summary, open(os.path.join(ROOT, "state", "last_run.json"), "w"), indent=1)
    log("DONE", summary)

if __name__ == "__main__":
    main()
