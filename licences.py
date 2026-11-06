"""Second lead source: official city business-licence lists (no websites in them), matched to each business's website.

Cities (official open data only): Calgary, Edmonton, Red Deer (AB), Vancouver (BC).
Surrey, Victoria and Lethbridge don't publish an official open list, so they're not included.

For each licensed business: guess its website from the trade name (many domain patterns, DNS checked first so dead
guesses cost almost nothing), confirm the site really is that business (name words + a local signal like the city,
province, postal code or a local area code), then run the same dated-site + published-email check as the map source.
"""
import random, re, socket, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

YEAR = dt.date.today().year
ESTABLISHED_BEFORE = f"{YEAR - 2}-01-01"   # licensed at least ~2 years ago

SKIP_TYPES = re.compile(r"food|restaurant|alcohol|liquor|cannabis|tobacco|vap|apartment|residential rental|erotic|body rub|"
                        r"escort|charit|delivery|courier|taxi|transportation network|food truck|temporary|travelling|"
                        r"market vendor|short-term|bed and breakfast|lottery|pawn|cheque|payday|adult", re.I)

AREA_CODES = {"Calgary": "403|587|825|368", "Edmonton": "780|587|825|368", "Red Deer": "403|587|825|368", "Vancouver": "604|778|236|672"}
PROVINCE = {"Calgary": "AB", "Edmonton": "AB", "Red Deer": "AB", "Vancouver": "BC"}

def _get(url, params=None, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=180, headers={"User-Agent": "veronos-lead-finder/1.0"})
            if r.status_code == 200: return r
        except Exception:
            pass
        time.sleep(5 * (i + 1))
    return None

def calgary():
    r = _get("https://data.calgary.ca/resource/vdjc-pybd.json", {
        "$select": "getbusid,tradename,licencetypes,address,first_iss_dt",
        "$where": f"first_iss_dt < '{ESTABLISHED_BEFORE}'", "$limit": "60000"})
    for x in (r.json() if r else []):
        t = x.get("licencetypes", "")
        if SKIP_TYPES.search(t) or not x.get("tradename"): continue
        yield {"key": f"lic/cal/{x['getbusid']}", "name": x["tradename"], "city": "Calgary", "cat": t.split(",")[0].strip().title(),
               "since": (x.get("first_iss_dt") or "")[:4]}

def edmonton():
    r = _get("https://data.edmonton.ca/resource/qhi4-bdpu.json", {
        "$select": "externalid,business_name,business_licence_category,originalissuedate,licencetype",
        "$where": f"originalissuedate < '{ESTABLISHED_BEFORE}' AND licencetype='Commercial'", "$limit": "60000"})
    for x in (r.json() if r else []):
        t = x.get("business_licence_category", "")
        if SKIP_TYPES.search(t) or not x.get("business_name"): continue
        yield {"key": f"lic/edm/{x['externalid']}", "name": x["business_name"], "city": "Edmonton", "cat": t.split(";")[0].strip(),
               "since": (x.get("originalissuedate") or "")[:4]}

def red_deer():
    skip = 0
    while True:
        r = _get("https://data.reddeer.ca/api/datasets/business-licences", {"skip": skip, "take": 1000})
        if not r: return
        rows = r.json().get("businessLicences", [])
        for x in rows:
            t = f'{x.get("licenseType","")} {x.get("licenseSubType","")} {x.get("licenseDescription","")}'
            if SKIP_TYPES.search(t) or "HOME-BASED" in (x.get("civicAddress") or "") or not (x.get("tradeName") or "").strip(): continue
            yield {"key": f"lic/rd/{x.get('licenseAccountNumber') or x.get('id')}", "name": x["tradeName"].strip(), "city": "Red Deer",
                   "cat": (x.get("licenseSubType") or x.get("licenseType") or "").strip().title(), "since": ""}
        if len(rows) < 1000: return
        skip += 1000

def vancouver():
    r = _get("https://opendata.vancouver.ca/api/explore/v2.1/catalog/datasets/business-licences/exports/json", {
        "select": "licencersn,businessname,businesstradename,businesstype,issueddate,status,city",
        "where": "status=\"Issued\"", "limit": "-1"})
    seen = set()
    for x in (r.json() if r else []):
        name = (x.get("businesstradename") or x.get("businessname") or "").strip()
        t = x.get("businesstype") or ""
        if not name or SKIP_TYPES.search(t) or name.lower() in seen: continue
        seen.add(name.lower())
        yield {"key": f"lic/van/{x.get('licencersn')}", "name": name, "city": "Vancouver", "cat": t.strip(), "since": ""}

SOURCES = {"calgary": calgary, "edmonton": edmonton, "red_deer": red_deer, "vancouver": vancouver}

# ---------------- website matching ----------------
CORP = {"ltd", "inc", "corp", "co", "limited", "incorporated", "llp", "lp", "ulc"}
STOP = CORP | {"the", "and", "of", "a"}
GENERIC_WORDS = {"services", "service", "solutions", "group", "enterprises", "company", "canada", "alberta", "calgary", "edmonton",
                 "vancouver", "red", "deer", "bc", "ab", "western", "north", "south", "east", "west", "international", "holdings"}
CITY_CODES = {"Calgary": ["yyc", "calgary"], "Edmonton": ["yeg", "edmonton"], "Red Deer": ["reddeer", "rd"], "Vancouver": ["van", "vancouver"]}

def words(name):
    name = re.sub(r"\(.*?\)|\bo/a\b.*|\bdba\b.*", "", name.lower()).replace("'", "").replace("&", " and ")
    name = re.sub(r"^\d{5,}\s*(alberta|b\.?c\.?)?\s*", "", name)  # numbered companies like "1234567 Alberta Ltd"
    return [re.sub(r"[^a-z0-9]", "", x) for x in name.split() if re.sub(r"[^a-z0-9]", "", x)]

def domain_guesses(name, city):
    w = [x for x in words(name) if x not in CORP]
    if not w or (len(w) == 1 and w[0] in ("alberta", "bc")): return []
    core = [x for x in w if x not in STOP] or w
    distinct = [x for x in core if x not in GENERIC_WORDS] or core
    joined = ["".join(w), "".join(core), "-".join(core), "".join(distinct), "".join(core[:2]), "".join(core[:3]),
              "".join(w) + "ltd", "".join(core) + "inc", "".join(x[0] for x in core) + "".join(core[-1:]) if len(core) > 2 else ""]
    if len(distinct[0]) >= 6: joined.append(distinct[0])
    for cc in CITY_CODES.get(city, []):
        joined += ["".join(core) + cc, cc + "".join(core), "".join(distinct[:2]) + cc]
    out = []
    for j in joined:
        if 4 < len(j) < 45 and j not in out: out.append(j)
    return [f"{j}{tld}" for j in out for tld in (".ca", ".com", ".net")]

import os
_PROXIED = bool(os.environ.get("HTTPS_PROXY")) and not os.environ.get("GITHUB_ACTIONS")
def resolves(host):
    if _PROXIED: return True  # local workspace has no direct DNS; on GitHub this check runs for real
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP); return True
    except Exception:
        return False

def is_their_site(html, name, city):
    low = html.lower()
    core = [x for x in words(name) if x not in STOP and x not in GENERIC_WORDS and len(x) > 2] or \
           [x for x in words(name) if x not in STOP and len(x) > 2]
    if not core: return False
    hit = sum(1 for x in core if x in low) / len(core)
    prov = PROVINCE.get(city, "")
    local = (city.lower() in low or ("alberta" in low if prov == "AB" else "british columbia" in low)
             or re.search(rf"\b{prov.lower()}\b", low) or re.search(rf"\b({AREA_CODES.get(city, '000')})[\s).-]*\d{{3}}[\s.-]?\d{{4}}", low)
             or re.search(r"\b[tv]\d[a-z]\s?\d[a-z]\d\b", low))
    return hit >= .6 and bool(local)

def find_website(name, city, ua):
    s = requests.Session()
    for host in domain_guesses(name, city):
        if not resolves(host): continue
        for url in (f"https://{host}", f"https://www.{host}", f"http://{host}"):
            try:
                r = s.get(url, timeout=10, headers={"User-Agent": ua}, allow_redirects=True)
            except Exception:
                continue
            if r.status_code < 400 and "html" in r.headers.get("content-type", "html") and is_their_site(r.text[:400000], name, city):
                return r.url
            break
    return ""
