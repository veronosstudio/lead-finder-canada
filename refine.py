"""Ideal-client refinement: exact service, owner first name, chain/franchise filter, 0-100 score, tiers.

Pure functions (no network) so the nightly finder, the competitor matcher and the one-off backfill all score the same way.

Score parts (max):  need 30 | value 25 | alive 20 | pressure 15 | reach 10
Tiers: A+ >= 70 (in practice: has a verified competitor), A >= 55, B >= 40, C = hold (problems owners can't see), skip.
"""
import re, datetime as dt

YEAR = dt.date.today().year

# ---------------- exact service ----------------
# key: (keywords matched against category + business name + page title, value weight 0-1, OSM filter for competitor search)
SERVICES = {
    "plumber":        (r"plumb|drain|sewer|water heater", 1.0, '["craft"="plumber"]'),
    "electrician":    (r"electric(al|ian)\b|electrician", 1.0, '["craft"="electrician"]'),
    "hvac":           (r"hvac|heating|furnace|air condition|refrigerat|heating_engineer", 1.0, '["craft"~"^(hvac|heating_engineer)$"]'),
    "roofer":         (r"roof", 1.0, '["craft"="roofer"]'),
    "renovation":     (r"renovat|remodel|woodcraft|millwork|builder|construction|carpent|cabinet|kitchen|bath(room)?s?\b|basement|home improvement", 0.95,
                       '["craft"~"^(builder|carpenter)$"]'),
    "auto_body":      (r"collision|auto ?body|body ?shop|paint ?&? ?body", 0.9, '["shop"="car_repair"]["service:vehicle:body_repair"="yes"]'),
    "auto_repair":    (r"auto|automotive|mechanic|car_repair|car repair|truck repair|transmission|motorcycle_repair|truck_repair", 0.8,
                       '["shop"="car_repair"]'),
    "auto_parts":     (r"auto parts|car_parts|parts|salvage|wrecker", 0.5, '["shop"="car_parts"]'),
    "dealership":     (r"dealer|motors\b|\bford\b|toyota|honda|hyundai|chevrolet|\bgm\b|nissan|mazda|kia\b|subaru|volkswagen|dodge|chrysler|\bram\b|jeep|go auto", 0.3, '["shop"="car"]'),
    "tires":          (r"\btyres?\b|\btires?\b", 0.6, '["shop"="tyres"]'),
    "dentist":        (r"dent(al|ist)|orthodont", 1.0, '["healthcare"="dentist"]'),
    "lawyer":         (r"law(yer)?\b|attorney|law_firm|legal|barrister|solicitor|notary", 1.0, '["office"~"^(lawyer|notary)$"]'),
    "chiropractor":   (r"chiropract", 0.95, '["healthcare"="chiropractor"]'),
    "physio":         (r"physio|physical therap|rehab", 0.9, '["healthcare"="physiotherapist"]'),
    "optometrist":    (r"optomet|optician|eye care|eyewear", 0.85, '["healthcare"="optometrist"]'),
    "accountant":     (r"account|bookkeep|\btax\b|\bcpa\b", 0.9, '["office"="accountant"]'),
    "architect":      (r"architect", 0.85, '["office"="architect"]'),
    "insurance":      (r"insurance", 0.8, '["office"="insurance"]'),
    "realtor":        (r"realt|real estate|estate_agent", 0.5, '["office"="estate_agent"]'),
    "landscaper":     (r"landscap|lawn|yard|garden(er|ing)|tree (service|care)|snow removal|irrigation", 0.85, '["craft"~"^(gardener|landscaper)$"]'),
    "painter":        (r"paint(er|ing)", 0.75, '["craft"="painter"]'),
    "flooring":       (r"floor|carpet|tile|tiler|hardwood", 0.8, '["shop"="flooring"]'),
    "windows":        (r"window|glass|glazi|door", 0.9, '["craft"~"^(glaziery|window_construction)$"]'),
    "cleaner":        (r"clean|janitor|maid|carpet cleaning", 0.7, '["craft"="cleaning"]'),
    "locksmith":      (r"locksmith|security", 0.7, '["craft"="locksmith"]'),
    "welding":        (r"weld|fabricat|metal_construction|machin", 0.8, '["craft"~"^(welder|metal_construction)$"]'),
    "hair":           (r"hair|barber|salon", 0.4, '["shop"="hairdresser"]'),
    "beauty":         (r"beauty|spa\b|esthetic|nail|lash|cosmetic", 0.45, '["shop"="beauty"]'),
    "massage":        (r"massage", 0.5, '["shop"="massage"]'),
    "tattoo":         (r"tattoo", 0.35, '["shop"="tattoo"]'),
    "florist":        (r"florist|flower", 0.35, '["shop"="florist"]'),
    "furniture":      (r"furniture|mattress", 0.5, '["shop"="furniture"]'),
    "jewelry":        (r"jewel", 0.45, '["shop"="jewelry"]'),
    "pet":            (r"\bpet\b|groom|kennel|veterin", 0.45, '["shop"="pet"]'),
    "bicycle":        (r"bicycle|bike", 0.35, '["shop"="bicycle"]'),
    "hardware":       (r"hardware|doityourself", 0.4, '["shop"~"^(hardware|doityourself)$"]'),
    "pest":           (r"pest|exterminat|termite|bed ?bug", 0.75, '["craft"="pest_control"]'),
    "dry_cleaner":    (r"dry ?clean|laundr|tailor", 0.4, '["shop"~"^(dry_cleaning|laundry)$"]'),
    "moving":         (r"\bmov(ing|ers)\b|junk|haul|bin clean|disposal", 0.6, '["office"="moving_company"]'),
    "orthodontist":   (r"orthodont", 1.0, '["healthcare"="orthodontist"]'),
    "vet":            (r"veterin|animal hospital|pet clinic|\bvet\b", 0.9, '["amenity"="veterinary"]'),
    "medical":        (r"medical|clinic|physician|family practice|doctors?\b|med ?spa|aesthetic|laser|botox|dermatolog|cosmetic surg", 0.9, '["amenity"~"^(clinic|doctors)$"]'),
    "financial":      (r"financial|wealth|tax_advisor|tax advis|investment|mortgage", 0.9, '["office"~"^(financial|financial_advisor|tax_advisor)$"]'),
    "pool":           (r"\bpools?\b|swimming_pool|hot tub", 0.95, '["shop"="swimming_pool"]'),
    "solar":          (r"solar|photovoltaic", 1.0, '["craft"~"^(photovoltaic|solar)$"]'),
    "fencing":        (r"fenc|deck", 0.85, '["craft"="fence_maker"]'),
    "garage_doors":   (r"garage door", 0.85, '["shop"="doors"]'),
    "photographer":   (r"photograph|photo studio|videograph", 0.7, '["craft"="photographer"]'),
    "venue":          (r"venue|banquet|event (centre|center|space)|wedding|events_venue", 0.75, '["amenity"~"^(events_venue|conference_centre)$"]'),
    "funeral":        (r"funeral|memorial|cremat|mortuar", 0.9, '["shop"="funeral_directors"]'),
    "school":         (r"driving school|music school|dance|academy|tutor|language school|driving_school|music_school|dancing_school", 0.6, '["amenity"~"^(driving_school|music_school|dancing_school|language_school)$"]'),
    "church":         (r"\bchurch|place_of_worship|\bchapel\b|\bparish\b|\bministr(y|ies)\b|\bfellowship\b|congregation", 0.35,
                       '["amenity"="place_of_worship"]["religion"="christian"]'),
}
# order matters: more specific first
ORDER = ["funeral", "vet", "orthodontist", "pest", "solar", "pool", "garage_doors", "fencing", "photographer", "venue", "financial", "dry_cleaner", "moving", "dealership", "auto_parts", "auto_body", "tires", "dentist", "chiropractor", "physio", "optometrist", "lawyer", "accountant", "medical", "school", "architect", "insurance",
         "realtor", "roofer", "plumber", "electrician", "hvac", "landscaper", "painter", "flooring", "windows", "cleaner", "locksmith",
         "welding", "renovation", "auto_repair", "hair", "beauty", "massage", "tattoo", "florist", "furniture", "jewelry", "pet",
         "bicycle", "hardware", "church"]

def service_of(category="", business="", title=""):
    """Best exact service key, or '' when we can't tell (then no competitor is named)."""
    for text in (category, business, title):  # category first (most reliable), then name, then page title
        t = (text or "").lower().replace("_", " ")
        for k in ORDER:
            if re.search(SERVICES[k][0], t):
                return k
    return ""

B2B = re.compile(r"manufactur|wholesal|warehous|import|export|distribut|industrial|commercial school|training institute", re.I)

def value_weight(service, category=""):
    if service in SERVICES: return SERVICES[service][1]
    return 0.4 if B2B.search(category or "") else 0.6

# ---------------- owner first name ----------------
FIRST_NAMES = set("""
aaron adam adrian aidan alan albert alex alexander alexandra alexis ali alice alicia alison allan allison amanda amber amy andre andrea andrew
andy angela angie anita ann anna anne annie anthony april arthur ashley audrey austin barb barbara barry ben benjamin bernie beth betty bev
beverly bill billy blair blake bob bobby bonnie brad bradley brandon brenda brendan brent brett brian brittany brooke bruce bryan caleb
calvin cameron carl carla carlos carmen carol caroline carrie casey cathy chad charles charlie chelsea cheryl chris christian christina
christine christopher chuck cindy claire clark clayton clint cody colin connie connor corey craig crystal curtis cynthia dale dallas dan dana
daniel danielle danny darcy darlene darren darryl dave david dawn dean deanna debbie deborah debra dennis derek devin diana diane dianne don
donald donna doug douglas drew duane dustin dwayne dylan earl ed eddie edward elaine eli elizabeth ellen emily emma eric erica erik erin ethan
eva evan faith frank fred gail gary gavin gene george gerald gilles glen glenn gloria gord gordon grace graham grant greg gregory guy hailey
harold harry heather heidi helen henry holly howard ian irene isaac jack jackie jacob jacqueline jake james jamie jan jane janet janice jared
jasmine jason jay jean jeff jeffrey jen jenn jennifer jenny jeremy jerry jesse jessica jill jim jimmy joan joanne jodi jody joe joel john
johnny jon jonathan jordan jose joseph josh joshua joy joyce judy julia julie justin karen kari karl kate katherine kathleen kathy katie
kayla keith kelly kelsey ken kendra kenneth kerry kevin kim kimberly kirk kris krista kristen kristin kurt kyle lana lance larry laura
lauren laurie lee leah len leonard les leslie linda lindsay lisa liz logan lois lori lorne louis lucas luke lynn mandy marc marcel marcus
margaret maria marie marilyn mario mark marlene martin marty mary matt matthew maureen max megan melanie melissa michael michel michele
michelle mike mitch mitchell monica morgan murray nancy naomi natalie nathan neil nicholas nick nicole noah norm norman olivia owen pam
pamela pat patricia patrick paul paula peggy penny pete peter phil philip phillip rachel ralph randy ray raymond rebecca reg regan rene rhonda
ricardo rich richard rick ricky rob robert roberta robin rod rodney roger ron ronald rory ross roy russ russell ruth ryan sam samantha sandra
sandy sara sarah scott sean shane shannon sharon shaun shawn sheila shelley sherry shirley simon sonia stacey stan stanley stephanie stephen
steve steven stuart sue susan suzanne tammy tanya tara ted terri terry theresa thomas tiffany tim timothy tina todd tom tommy tony tracy
travis trevor troy tyler valerie vanessa vern vicki victor victoria vince vincent walter wanda warren wayne wendy wes wesley will william
willy zach zachary
""".split())
ROLE_WORDS = {"info", "office", "admin", "contact", "sales", "hello", "support", "reception", "service", "services", "accounts", "billing",
              "booking", "bookings", "appointments", "help", "team", "mail", "email", "inquiries", "enquiries", "general", "front",
              "frontdesk", "orders", "shop", "store", "church", "pastor", "parish", "dispatch", "estimates", "quotes", "jobs", "careers", "hr"}

def first_name(email="", html_text=""):
    """A first name only when it's clearly one: from the email's local part, or 'Owner: Dave' / 'I'm Dave' on the site."""
    local = (email or "").split("@")[0].lower()
    parts = [p for p in re.split(r"[._\-+]", local) if p]
    if parts and parts[0] not in ROLE_WORDS and parts[0] in FIRST_NAMES:
        return parts[0].capitalize()
    if html_text:
        for pat in (r"\b[Oo]wner(?:/[Oo]perator)?[:,\s\-–]+([A-Z][a-z]{2,12})\b", r"\b(?:Hi|Hello),? I['’]?m ([A-Z][a-z]{2,12})\b",
                    r"\bMeet ([A-Z][a-z]{2,12})\b", r"\b([A-Z][a-z]{2,12}) [A-Z][a-z]+,? (?:Owner|Founder|President)\b"):
            m = re.search(pat, html_text)
            if m and m.group(1).lower() in FIRST_NAMES:
                return m.group(1)
    return ""

def personal_email(email):
    local = (email or "").split("@")[0].lower()
    return bool(local) and local.split(".")[0] not in ROLE_WORDS and not any(r == local for r in ROLE_WORDS)

# ---------------- chains / franchises ----------------
CHAIN_WORDS = ["go auto", "go ford", "autocanada", "auto canada", "kal tire", "canadian tire", "mr. rooter", "mr rooter", "roto-rooter", "benjamin franklin", "one hour heating", "aire serv", "molly maid", "merry maids",
               "the cleaning authority", "jan-pro", "coit", "chem-dry", "chemdry", "two men and a truck", "college pro", "student works",
               "certapro", "five star painting", "window genie", "men in kilts", "1-800-got-junk", "junk king", "weed man", "lawn doctor",
               "nutri-lawn", "kumon", "sylvan", "orangetheory", "anytime fitness", "goodlife", "f45", "snap fitness", "massage addict",
               "first choice", "great clips", "supercuts", "magicuts", "chatters", "lens crafters", "lenscrafters", "specsavers",
               "fyidoctors", "ok tire", "kal tire", "fountain tire", "midas", "meineke", "speedy", "jiffy lube", "mr. lube", "mr lube",
               "craftsman collision", "boyd", "carstar", "fix auto", "maaco", "novus", "speedy glass", "apple auto glass", "royal lepage",
               "re/max", "remax", "century 21", "coldwell", "sutton", "exp realty", "h&r block", "liberty tax", "edward jones",
               "investors group", "ig wealth", "sun life", "desjardins", "state farm", "allstate", "co-operators", "pt health",
               "lifemark", "cbi health", "physio plus", "dentalcorp", "123dentist", "lumino", "denturist group"]
FRANCHISE_SIGNS = re.compile(r"franchise opportunit|own a franchise|find a location near|locations across (canada|north america)|"
                             r"independently owned and operated|\d{2,} locations", re.I)

def is_chain(business="", html_text=""):
    b = (business or "").lower()
    if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", b) for w in CHAIN_WORDS):
        return True
    return bool(html_text and FRANCHISE_SIGNS.search(html_text[:300000]))


# ---------- is it clearly dated? (only problems a person would notice) ----------
def badness(why_dated=""):
    """How bad the site is, in points, from what the check actually found on the page.
    Strong (3): a problem a visitor hits right away.  Medium (2): clearly old or DIY.  Weak (1): a rough edge.
    A copyright of the last 3 years counts for nothing (plenty of good sites forget to update it)."""
    w = (why_dated or "").lower(); pts, out = 0, []
    def add(n, label): nonlocal pts; pts += n; out.append(label)
    if "not built for phones" in w: add(3, "not built for phones")
    if "no secure https" in w: add(3, "not secure")
    for k in ("flash", "table layout", "<font", "marquee", "old builder"):
        if k in w: add(3, k)
    m = re.search(r"copyright (\d{4})", w)
    if m:
        y = int(m.group(1))
        if y <= YEAR - 6: add(3, f"copyright {y}")
        elif y <= YEAR - 4: add(2, f"copyright {y}")
    for k in ("diy ", "template builder", "old slider", "old jquery", "old wordpress", "old default theme"):
        if k in w: add(2, k.strip())
    for k in ("no main headline", "phone not tappable", "no contact form"):
        if k in w: add(1, k)
    return pts, out

BAD_ENOUGH = 3   # one strong problem, or a medium + a weak one, or three weak ones

def strong_reasons(why_dated=""):
    """Kept for older callers: the reasons, but only when the site is bad enough to email."""
    pts, out = badness(why_dated)
    return out if pts >= BAD_ENOUGH else []

# ---------------- site signals (from the page we already fetched) ----------------
def site_signals(html):
    low = (html or "").lower()
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", " ", low))
    no_copy = re.sub(r"(©|&copy;|copyright)\s*(\d{4}\s*[-–]\s*)?\d{4}", " ", text)
    return {
        "recent_content": bool(re.search(rf"\b({YEAR}|{YEAR - 1})\b", no_copy)),   # current/last year outside the copyright line
        "contact_form": "<form" in low and bool(re.search(r'type=["\']?email|<textarea', low)),
        "booking": bool(re.search(r"book (now|online|an appointment)|schedule (online|an appointment)|calendly|jane\.app|"
                                  r"housecallpro|jobber|setmore|square\.site/book|acuityscheduling", low)),
        "ads": bool(re.search(r"aw-\d{6,}|googleadservices|googleads\.g\.doubleclick|fbq\(['\"]init|connect\.facebook\.net/[^\"']*fbevents", low)),
        "team": bool(re.search(r"our team|meet the team|our staff|meet our|our technicians|our crew|employees|trucks", text)),
        "financing": bool(re.search(r"financing|payment plans?|0% interest|\bafford(able)? monthly|carecredit|sunbit|greensky|financeit|hearth\.co|affirm\.com|\bwells fargo financ", text)),
        "locations": bool(re.search(r"our locations|(two|three|four|five|\d+) locations|second location|multiple locations|offices in|service areas?\b", text)),
        "established": bool(re.search(r"\b(since|established|est\.?|founded( in)?|serving [a-z ,]+ since)\s*(19\d\d|200\d|201[0-6])\b|\b([1-9]\d)\+?\s*years (of experience|in business|serving)", text)),
        "emergency": bool(re.search(r"24/7|24 hours?|24-hour|emergency service|same[- ]day service", text)),
    }

def looks_abandoned(html, why_dated=""):
    """Kash (Nov 25): a dated site is our target, an abandoned one isn't. Abandoned = an old copyright (8+ years)
    AND nothing current on the page: no recent date, no booking, no contact form."""
    s = site_signals(html)
    if s["recent_content"] or s["booking"] or s["contact_form"]: return False
    low = (html or "").lower()
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?((?:19|20)\d{2})", low)]
    return bool(years) and max(years) <= YEAR - 8

# ---------------- who we target ----------------
# Must-have: a problem the owner would notice. Skip only the cheapest niches.
# Spend signals (ads, team, financing...) are NOT required: they raise the score so those businesses get emailed first.
LOW_NICHES = {k for k, v in SERVICES.items() if v[1] < 0.5}

MONEY_LABELS = {"ads": "runs ads", "team": "has a team", "financing": "offers financing", "locations": "multiple locations/service areas",
                "established": "10+ years in business", "emergency": "24/7 or emergency service"}

def money_signals(sig, since=""):
    out = [k for k in MONEY_LABELS if (sig or {}).get(k)]
    if "established" not in out and str(since).isdigit() and YEAR - int(since) >= 10:
        out.append("established")
    return out

def qualifies(why_dated, service, sig=None, since=""):
    """Returns '' when the business makes the list, else the reason it doesn't."""
    if not strong_reasons(why_dated): return "no clear problem"
    if service in LOW_NICHES: return f"low-value niche ({service})"
    return ""

# ---------------- the 0-100 score ----------------
def score(why_dated="", service="", since="", signals=None, competitor="", email="", fname="", phone="", category=""):
    w = (why_dated or "").lower(); s = signals or {}
    parts = {}
    # need (30): how bad the site is (badness points x 3)
    parts["need"] = min(30, badness(w)[0] * 3)
    # value (25): what one new customer is worth + how established
    yrs = (YEAR - int(since)) if str(since).isdigit() else None
    if yrs is None:
        m2 = re.search(r"licensed since (\d{4})", w); yrs = (YEAR - int(m2.group(1))) if m2 else None
    value = round(15 * value_weight(service, category)) + (6 if yrs and yrs >= 10 else 4 if yrs and yrs >= 5 else 2 if yrs else 1)
    if s.get("team"): value += 4
    if s.get("ads"): value += 6          # already paying for Google/Facebook ads: has a budget, and is wasting clicks
    value += 2 * len([k for k in ("financing", "locations", "established", "emergency") if s.get(k)])
    parts["value"] = min(25, value)
    # alive (20): proof they're still trading
    alive = 8
    if s.get("recent_content"): alive += 6
    if "licensed since" in w or str(since).isdigit(): alive += 3   # on a current city licence list
    if phone: alive += 3
    parts["alive"] = min(20, alive)
    # pressure (15): a nearby competitor with a genuinely good site
    parts["pressure"] = 15 if competitor else 0
    # reach (10): a real person
    reach = (6 if fname else 0) + (4 if personal_email(email) else 2 if email else 0)
    parts["reach"] = min(10, reach)
    total = sum(parts.values())
    return total, parts

def tier_of(total, need, why_dated=None):
    """Yay or nay. Every lead here already passed the dated-site check, so it's a YES (A = send first, B = send next).
    The only NOs ("skip") come from hard reasons set elsewhere: site down, chain/franchise, site redesigned since."""
    if why_dated is not None:
        return "A" if badness(why_dated)[0] >= 5 and total >= 45 else "B"
    return "A" if total >= 50 else "B"

def greeting(fname, company=""):
    return f"Hi {fname}," if fname else "Hi there,"
