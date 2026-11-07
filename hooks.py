"""Turn the finder's why_dated reasons into one plain-English line for the first email.

Only things the check actually found, worded so the owner can confirm them in seconds.
Fits after "Noticed your site ...". Strongest reason wins, in this order.
"""
import re, datetime as dt

OLD_YEAR = dt.date.today().year - 4  # ©2022 or older (in 2026) reads as clearly old

GENERIC = "was getting a bit dated"

def hook(why_dated: str) -> str:
    w = (why_dated or "").lower()
    if "not built for phones" in w:
        return "is pretty tough to read on a phone"
    if "no secure https" in w:
        return 'shows a "Not secure" warning in Chrome'
    m = re.search(r"copyright ((?:19|20)\d{2})", w)
    if m and int(m.group(1)) <= OLD_YEAR:
        return f"still says ©{m.group(1)} at the bottom"
    # Flash is not used: a leftover .swf reference doesn't prove anything is broken.
    return GENERIC

def tier(why_dated: str) -> str:
    """A = clearly old to the owner at a glance. B = borderline (send later, softer pitch). Same rule as the sheet script."""
    w = (why_dated or "").lower()
    if re.search(r"not built for phones|no secure https|flash|table layout|<font|old builder", w):
        return "A"
    m = re.search(r"copyright ((?:19|20)\d{2})", w)
    if m and int(m.group(1)) <= OLD_YEAR:
        return "A"
    return "B"
