"""Turn the finder's why_dated reasons into one plain-English line for the first email.

Only things the check actually found, worded so the owner can confirm them in seconds.
Fits after "Noticed your site ...". Strongest reason wins, in this order.
"""
import re, datetime as dt

OLD_YEAR = dt.date.today().year - 4  # ©2022 or older (in 2026) reads as clearly old

GENERIC = "looks like it hasn't had a refresh in a while"

def hook(why_dated: str, signals: dict = None) -> str:
    """Fits after "your site ...". Human wording; only what the check actually found."""
    w = (why_dated or "").lower(); sig = signals or {}
    if "not built for phones" in w:
        return "is really hard to use on a phone"
    if "no secure https" in w:
        return 'pops up a "Not secure" warning when people open it'
    m = re.search(r"copyright ((?:19|20)\d{2})", w)
    if m and int(m.group(1)) <= OLD_YEAR:
        return f"still says {m.group(1)} at the bottom"
    if sig.get("contact_form") is False and sig.get("booking") is False:
        return "doesn't have an easy way for people to ask for a quote"
    # Flash is not used: a leftover .swf reference doesn't prove anything is broken.
    return GENERIC

SERVICE_WORDS = {"plumber": "plumbing", "electrician": "electrical work", "hvac": "heating and cooling", "roofer": "roofing",
    "renovation": "renovations", "auto_body": "auto body work", "auto_repair": "auto repair", "tires": "tires",
    "dentist": "dental care", "lawyer": "legal work", "chiropractor": "chiropractic care", "physio": "physio",
    "optometrist": "eye care", "accountant": "accounting", "architect": "architecture", "insurance": "insurance",
    "realtor": "real estate", "landscaper": "landscaping", "painter": "painting", "flooring": "flooring",
    "windows": "windows and doors", "cleaner": "cleaning", "locksmith": "locksmithing", "welding": "welding and fabrication",
    "hair": "hair", "beauty": "beauty services", "massage": "massage therapy", "tattoo": "tattoos", "florist": "flowers",
    "furniture": "furniture", "jewelry": "jewelry", "pet": "pet care", "bicycle": "bikes", "hardware": "hardware",
    "pest": "pest control", "dry_cleaner": "dry cleaning", "moving": "moving", "auto_parts": "auto parts"}

def service_word(service: str) -> str:
    return SERVICE_WORDS.get(service or "", "")

def since_year(why_dated: str) -> str:
    """The year they got their city business licence, only when we actually know it."""
    m = re.search(r"licensed since ((?:19|20)\d{2})", (why_dated or "").lower())
    return m.group(1) if m else ""

def tier(why_dated: str) -> str:
    """A = clearly old to the owner at a glance. B = borderline (send later, softer pitch). Same rule as the sheet script."""
    w = (why_dated or "").lower()
    if re.search(r"not built for phones|no secure https|flash|table layout|<font|old builder", w):
        return "A"
    m = re.search(r"copyright ((?:19|20)\d{2})", w)
    if m and int(m.group(1)) <= OLD_YEAR:
        return "A"
    return "B"
