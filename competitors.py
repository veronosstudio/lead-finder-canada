"""Find an exact, honest competitor for each contact: same service, same town (nearest when we know where), a genuinely
good modern site we actually checked, and not a chain or franchise.

Pool of checked sites lives in data/competitor_pool.csv (public business names + websites only; no emails).
Town centres are cached in data/towns.json. Uses the Overpass API (works on GitHub; not from the local workspace).
"""
import csv, json, math, os, re, time
import requests
import refine as R

ROOT = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(ROOT, "data", "competitor_pool.csv")
TOWNS = os.path.join(ROOT, "data", "towns.json")
POOL_FIELDS = ["service", "town", "province", "business", "website", "domain", "lat", "lon", "good", "quality", "checked"]
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
BIG = {"calgary": 22000, "edmonton": 22000, "vancouver": 14000, "surrey": 12000, "winnipeg": 18000, "regina": 12000,
       "saskatoon": 12000, "red deer": 9000, "lethbridge": 9000, "kelowna": 12000, "victoria": 10000}

def norm_town(t): return re.sub(r"\s+", " ", (t or "").strip().lower())

def load_pool():
    if not os.path.exists(POOL): return []
    return list(csv.DictReader(open(POOL)))

def save_pool_rows(rows):
    new = not os.path.exists(POOL)
    with open(POOL, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=POOL_FIELDS, extrasaction="ignore")
        if new: w.writeheader()
        w.writerows(rows)

def _overpass(q, deadline):
    for attempt in range(3):
        if time.time() > deadline - 60: return None
        try:
            r = requests.post(OVERPASS[attempt % 3], data={"data": q}, timeout=min(120, max(30, deadline - time.time() - 30)),
                              headers={"User-Agent": "veronos-lead-finder/1.0"})
            if r.status_code == 200: return r.json().get("elements", [])
        except Exception:
            pass
        time.sleep(5)
    return None

def town_centre(town, province, cache, deadline):
    key = f"{norm_town(town)}|{province}"
    if key in cache: return cache[key]
    q = f"""[out:json][timeout:60];
area["ISO3166-2"="CA-{province}"]["admin_level"="4"]->.p;
node["place"~"^(city|town|village|hamlet)$"]["name"~"^{re.escape(town.strip())}$",i](area.p);
out 1;"""
    els = _overpass(q, deadline)
    if els is None: return None
    cache[key] = [els[0]["lat"], els[0]["lon"]] if els else []
    return cache[key]

def km(a, b):
    if not a or not b: return 9999
    la1, lo1, la2, lo2 = map(math.radians, [float(a[0]), float(a[1]), float(b[0]), float(b[1])])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))

def check_good(url, finder):
    """Is this a genuinely good, current site? Returns quality (higher = better) or None."""
    try:
        s = requests.Session()
        r = s.get(url.replace("http://", "https://", 1), timeout=12, headers={"User-Agent": finder.UA}, allow_redirects=True)
        if r.status_code >= 400 or not r.url.startswith("https://"): return None
        html = r.text[:600000]; low = html.lower()
        if len(low) < 5000 or 'name="viewport"' not in low and "name='viewport'" not in low: return None
        if R.is_chain("", html): return None
        pts, why = finder.score(html, r.url, True)
        if pts > 0: return None                      # anything we'd call dated is not "a really nice website"
        years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", low)]
        modern = sum(x in low for x in ("__next", "tailwind", "data-reactroot", "_nuxt", "gatsby", "webflow", "framerusercontent",
                                        "astro-island", "elementor", "wp-block", "squarespace", "wix-thunderbolt"))
        if years and max(years) < R.YEAR - 1: return None
        if not years and not modern: return None
        return 10 - pts + 3 * min(modern, 2) + (3 if years and max(years) >= R.YEAR - 1 else 0)
    except Exception:
        return None

def search_area(service, town, province, centre, finder, deadline, exclude_domains):
    """Ask OpenStreetMap for same-service businesses with websites near the town, check their sites, return pool rows."""
    flt = R.SERVICES[service][2]
    radius = BIG.get(norm_town(town), 7000)
    q = f"""[out:json][timeout:90];
(nwr{flt}["website"](around:{radius},{centre[0]},{centre[1]});nwr{flt}["contact:website"](around:{radius},{centre[0]},{centre[1]}););
out tags center 40;"""
    els = _overpass(q, deadline)
    if els is None: return None
    rows, seen = [], set()
    for e in els:
        t = e.get("tags", {}); name = (t.get("name") or "").strip()
        site = finder.norm_site(t.get("website") or t.get("contact:website"))
        if not name or not site or t.get("brand") or t.get("brand:wikidata") or R.is_chain(name): continue
        other = R.service_of("", name)
        if other and other != service: continue                  # e.g. a pest-control company tagged as "cleaning"
        path = site.split("//", 1)[-1].split("/", 1)[1].lower() if "/" in site.split("//", 1)[-1] else ""
        if "location" in path or norm_town(town).replace(" ", "-") in path or norm_town(town).replace(" ", "") in path:
            continue                                               # a city page on a multi-city brand's site, not a local business
        d = finder.domain(site)
        if not d or d in seen or d in exclude_domains or any(b in site.lower() for b in finder.BAD_HOSTS): continue
        seen.add(d)
        lat = e.get("lat") or (e.get("center") or {}).get("lat"); lon = e.get("lon") or (e.get("center") or {}).get("lon")
        rows.append({"service": service, "town": norm_town(town), "province": province, "business": name, "website": site,
                     "domain": d, "lat": lat or "", "lon": lon or ""})
    rows = sorted(rows, key=lambda r: km(centre, [r["lat"], r["lon"]]) if r["lat"] else 50)[:10]
    for r in rows:
        if time.time() > deadline - 20: break
        q_ = check_good(r["website"], finder)
        r.update({"good": "1" if q_ else "0", "quality": q_ or 0, "checked": finder.TODAY})
    return [r for r in rows if "good" in r]

def match(contacts, finder, budget_s, log=print):
    """contacts: rows with osm_id, service, town, province, website, business. Returns {osm_id: (name, site)}."""
    deadline = time.time() + budget_s
    pool = load_pool()
    towns = json.load(open(TOWNS)) if os.path.exists(TOWNS) else {}
    contact_domains = {finder.domain(c.get("website", "")) for c in contacts}
    groups = {}
    for c in contacts:
        if c.get("service") in R.SERVICES and c.get("town") and c.get("province"):
            groups.setdefault((c["service"], norm_town(c["town"]), c["province"]), []).append(c)
    # biggest groups first, so one search serves the most contacts
    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    found, searched, new_rows = {}, 0, []
    for (svc, town, prov), cs in order:
        if time.time() > deadline - 30: break
        have = [p for p in pool + new_rows if p["service"] == svc and p["town"] == town and p["province"] == prov]
        if not have:
            centre = town_centre(town, prov, towns, deadline)
            if centre is None: break           # Overpass unavailable: try again next run
            if not centre: continue
            rows = search_area(svc, town, prov, centre, finder, deadline, contact_domains)
            if rows is None: break
            if not rows:  # remember "nobody found" so we don't search again tonight
                rows = [{"service": svc, "town": town, "province": prov, "business": "", "website": "", "domain": "",
                         "lat": "", "lon": "", "good": "0", "quality": 0, "checked": finder.TODAY}]
            new_rows += rows; have = rows; searched += 1
        good = sorted([p for p in have if p.get("good") == "1" and p.get("business")], key=lambda p: -float(p.get("quality") or 0))
        for c in cs:
            own = finder.domain(c.get("website", ""))
            pick = next((p for p in good if p["domain"] != own and p["domain"] not in contact_domains), None)
            if pick: found[c["osm_id"]] = (pick["business"], pick["website"])
    if new_rows: save_pool_rows(new_rows)
    json.dump(towns, open(TOWNS, "w"))
    log(f"competitors: {len(groups)} service/town groups, searched {searched}, matched {len(found)} contacts")
    return found
