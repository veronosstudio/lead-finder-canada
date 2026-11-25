"""How a person would write a business name in an email (Kash, Nov 25).

"Debra J. Hilstrom Attorney At Law, Pllc" -> person's name -> "your firm"
"Utility Construction Management Co. (ucmc), Llc" -> "Utility Construction Management"
"Yungwirth Matthew S" (backwards licence-register name) -> "your firm"
"www.pro-dent.ca" -> "your practice"
"Plant Plant" -> "Plant"
"Brown And White" -> "Brown and White"

natural(raw, first_name, service) returns (company_for_subject, possessive_for_body).
When the name would read like a mail merge, the subject gets "your firm/practice/business" and the body says "your website".
bad_fit(...) flags businesses that won't buy: web/marketing/IT shops and big multi-partner firms.
"""
import re

SUFFIX = re.compile(r"[,\s]+(l\.?\s?l\.?\s?c\.?|p\.?\s?l\.?\s?l\.?\s?c\.?|p\.?\s?c\.?|p\.?\s?a\.?|inc\.?|incorporated|ltd\.?|limited|corp\.?|corporation|"
                    r"u\.?l\.?c\.?|l\.?l\.?p\.?|l\.?p\.?|chtd\.?|chartered|professional corporation|prof\.? corp\.?|co\.?|s\.?c\.?|pllc|plc)\s*$", re.I)
TAIL = re.compile(r"[,\s]+(attorneys?|lawyers?)\s+at\s+law\s*$|[,\s]+esq\.?\s*$", re.I)
SMALL = {"and", "of", "the", "for", "at", "in", "on", "de", "du", "la", "le", "des", "et"}
KEEP_UPPER = re.compile(r"^(?:[A-Z]{2,5}|[A-Z]&[A-Z]|DDS|DMD|CPA|HVAC|RV|BBQ|II|III|IV)$")


def _case(w, first):
    if KEEP_UPPER.match(w): return w
    lw = w.lower()
    if lw in SMALL and not first: return lw
    if re.fullmatch(r"(mc|mac)[a-z]{2,}", lw): return lw[:2].title() + lw[2:].title() if lw.startswith("mc") else w
    if w.isupper() and len(w) > 5: return w.title()
    if w[:1].islower() and lw not in SMALL: return w[:1].upper() + w[1:]
    return w


def _person_like(n, first_name, first_names):
    w = [x for x in re.split(r"[\s,]+", n) if x]
    low = [x.lower().strip(".") for x in w]
    if re.match(r"dr\.?\s", n, re.I): return True
    fn = re.sub(r"^dr\.?\s+", "", (first_name or "").lower()).split()
    if fn and fn[0] in low and len(w) <= 6: return True       # "Debra J. Hilstrom", "Ross Gordon Law" -> "your firm"
    if not 2 <= len(w) <= 4: return False
    if not all(re.fullmatch(r"[A-Z][a-zA-Z'\-]*\.?|[A-Z]\.?", x) for x in w): return False
    if any(x in first_names for x in low[:2]) and (len(w) == 2 or any(len(x.strip(".")) == 1 for x in w)): return True
    return bool(re.fullmatch(r"[A-Z]\.?", w[-1]))  # "Yungwirth Matthew S"


def natural(raw, first_name="", generic="your business", first_names=frozenset()):
    n = (raw or "").strip()
    n = re.sub(r"(['’])S\b", r"\1s", n)
    if re.search(r"^(https?://|www\.)|\.(com|ca|net|org|biz|us|co)\b", n, re.I):
        return generic, "your"
    n = re.sub(r"\s*\([^)]*\)", "", n)                       # "(ucmc)"
    for _ in range(3):
        n2 = TAIL.sub("", SUFFIX.sub("", n)).strip(" ,.-")
        if n2 == n: break
        n = n2
    words = n.split()
    out = []
    for w in words:                                           # "Plant Plant"
        if not out or out[-1].lower() != w.lower(): out.append(w)
    n = " ".join(_case(w, i == 0) for i, w in enumerate(out))
    n = re.sub(r"\s+&\s+", " & ", n).strip(" ,")
    if not n or len(n) < 3 or n.lower() in ("your firm", "your practice", "your business"):
        return generic, "your"
    if _person_like(n, first_name, first_names):
        return generic, "your"
    if n.count(",") >= 1 or len(n) > 34 or len(n.split()) > 5:   # long multi-name firms read like a database
        return generic, "your"
    return n, n + ("'" if n.lower().endswith("s") else "'s")


NOT_A_FIT = re.compile(r"web ?(design|dev|site|studio|solutions|services)|websites?\b|\bmarketing\b|\bseo\b|digital (agency|marketing|media|studio|solutions)|"
                       r"\bsoftware\b|\bit (services|solutions|support)\b|tech(nology)? (services|solutions)|computer|\bhosting\b|\bapps?\b|"
                       r"branding|advertising|creative agency|graphic design|\bagency\b|\bmedia group\b", re.I)


def bad_fit(raw_name, website="", email=""):
    """Businesses that won't hire a solo web person: web/marketing/IT shops and big multi-partner firms."""
    raw = raw_name or ""
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", (website or "").lower())).split("/")[0]
    if NOT_A_FIT.search(raw) or NOT_A_FIT.search(host.replace("-", " ")):
        return "web/marketing/IT business"
    core = SUFFIX.sub("", re.sub(r"\s*\([^)]*\)", "", raw)).strip(" ,")
    if core.count(",") >= 2 or len(re.findall(r"[,&]", core)) >= 3:
        return "big multi-partner firm"
    ed = (email or "").split("@")[-1].lower()
    if ed in BIG_FIRM_DOMAINS:
        return "big multi-partner firm"
    return ""


# National/large firms that turn up in licence registers; they never buy from a solo web person.
BIG_FIRM_DOMAINS = {"duanemorris.com", "hallrender.com", "bakermckenzie.com", "dentons.com", "gowlingwlg.com", "blg.com", "mcmillan.ca",
                    "fasken.com", "osler.com", "mccarthy.ca", "nortonrosefulbright.com", "kirkland.com", "lw.com", "jonesday.com",
                    "sidley.com", "dlapiper.com", "hoganlovells.com", "foxrothschild.com", "lewisbrisbois.com", "littler.com",
                    "fisherphillips.com", "jacksonlewis.com", "ogletree.com", "bclaws.ca", "mltaikins.com", "millerthomson.com",
                    "fieldlaw.com", "bennettjones.com", "stikeman.com", "torys.com", "cassels.com", "airdberlis.com", "bdo.ca",
                    "kpmg.com", "pwc.com", "ey.com", "deloitte.com", "mnp.ca", "edwardjones.com", "remax.ca", "remax.com",
                    "kw.com", "coldwellbanker.com", "century21.ca", "royallepage.ca", "statefarm.com", "allstate.com"}
