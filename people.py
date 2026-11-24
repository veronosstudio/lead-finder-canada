"""Find the decision maker on a business's own website, and the best published email to reach them.

Order of preference for the email (all must be published on their own site, nothing is guessed):
  1. the owner / founder / doctor / managing partner's own address  -> "owner"   (a manager's -> "manager")
  2. another named person's address                                             -> email_type "named"
  3. the general inbox: office@, info@, contact@, hello@ ...                    -> email_type "general"
The greeting uses the decision maker's name when the email goes to a general inbox ("Hi Dr. Lee," / "Hi Dave,"),
the named person's own name when it goes to them, and "Hi there," when we don't have a name we can trust.
"""
import re
from urllib.parse import urljoin, urlparse

import refine as R

# role -> rank (lower = more of a decision maker)
ROLES = [
    (r"owner|co-?owner|founder|co-?founder|proprietor|president|ceo|chief executive|principal|managing partner|founding partner|managing attorney|managing member", 1, "owner"),
    (r"dds|dmd|d\.d\.s|d\.m\.d|orthodontist|dentist|chiropractor|d\.c\.|optometrist|o\.d\.|physician|m\.d\.|dvm|d\.v\.m|veterinarian|physical therapist|dpt", 2, "doctor"),
    (r"attorney|lawyer|esq\.?|partner|cpa|financial advis[eo]r|architect", 2, "professional"),
    (r"office manager|practice manager|general manager|operations manager|clinic manager|manager|director", 3, "manager"),
]
GENERAL_INBOX = ("info", "office", "contact", "hello", "admin", "frontdesk", "front.desk", "reception", "appointments",
                 "appointment", "schedule", "scheduling", "service", "sales", "team", "mail", "inquiries", "inquiry",
                 "support", "help", "smile", "smiles", "care", "patients", "clinic", "dental", "law", "legal", "staff")
NAME = r"([A-Z][a-z]{1,14}(?:-[A-Z][a-z]+)?)\s+(?:[A-Z]\.\s+)?((?:Mc|Mac|O')?[A-Z][a-zA-Z'\-]{1,20})"
NOT_LAST = {"Dental", "Law", "Group", "Office", "Center", "Centre", "Clinic", "Family", "Team", "Services", "Company",
            "Construction", "Plumbing", "Electric", "Roofing", "Heating", "Cooling", "Associates", "Inc", "Llc", "Ltd",
            "And", "The", "Our", "Owner", "Founder", "President", "Manager", "Director", "Attorney", "Dentistry",
            "Orthodontics", "Pediatrics", "Chiropractic", "Insurance", "Financial", "Accounting", "Realty", "Home"}
TEAM_LINK = re.compile(r"about|team|staff|our-doctor|our-dentist|doctor|meet|attorney|lawyer|people|leadership|our-story|"
                       r"who-we-are|owner|founder|bio|profile|contact", re.I)

def plain(html):
    t = re.sub(r"<(script|style|noscript)[\s\S]*?</\1>", " ", html or "", flags=re.I)
    t = re.sub(r"<br\s*/?>|</(p|div|li|h\d|td|tr|span|a|strong|b)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;|&#160;", " ", t); t = re.sub(r"&amp;", "&", t)
    return re.sub(r"[ \t]+", " ", t)

def team_links(base_url, html, limit=4):
    host = urlparse(base_url).netloc.lower().replace("www.", "")
    out = []
    for href in re.findall(r'href=["\']([^"\'#]+)', html or "", re.I):
        u = urljoin(base_url, href)
        p = urlparse(u)
        if p.netloc.lower().replace("www.", "") != host or re.search(r"\.(pdf|jpe?g|png|gif|mp4|zip)$", p.path, re.I): continue
        if TEAM_LINK.search(p.path) and u not in out: out.append(u)
    # people pages before the contact page
    out.sort(key=lambda u: 1 if "contact" in u.lower() else 0)
    return out[:limit]

def _ok_name(first, last):
    return first.lower() in R.FIRST_NAMES and last not in NOT_LAST and first != last

def people(text):
    """[(rank, role_kind, first, last, is_dr)] found next to a role word, best first."""
    found = {}
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if len(line) > 160: line = line[:160]
        window = " ".join(lines[i:i + 3])[:260]          # name on one line, title on the next
        # "Dr. Sarah Lee", "Dr Sarah Lee, DDS"
        for m in re.finditer(r"\bDr\.?\s+" + NAME, line):
            f, l = m.group(1), m.group(2)
            if _ok_name(f, l): found.setdefault((f, l), (2, "doctor", True))
        for m in re.finditer(NAME, line):
            f, l = m.group(1), m.group(2)
            if not _ok_name(f, l): continue
            near = window[max(0, window.find(m.group(0)) - 60): window.find(m.group(0)) + len(m.group(0)) + 90].lower()
            for pat, rank, kind in ROLES:
                if re.search(r"(?<![a-z])(" + pat + r")(?![a-z])", near):
                    is_dr = bool(re.search(r"\bdr\.?\s+" + re.escape(f.lower()), near)) or kind == "doctor"
                    old = found.get((f, l))
                    if not old or rank < old[0]: found[(f, l)] = (rank, kind, is_dr)
                    break
    return sorted(((v[0], v[1], k[0], k[1], v[2]) for k, v in found.items()), key=lambda x: x[0])

def matches(email, first, last):
    local = email.split("@")[0].lower()
    f, l = first.lower(), last.lower()
    return f in local or (len(l) >= 3 and l in local) or local in (f[0] + l, f + l[0], f[0] + "." + l)

def is_general(email):
    local = email.split("@")[0].lower()
    return any(local == g or local.startswith(g) for g in GENERAL_INBOX)

# Kash (Nov 24): when only shared inboxes exist, pick the one the owner is most likely to read, not just the first found.
# Best: office/info/contact/hello/admin. Then front desk. Then service/support. Worst: sales, and back-office
# boxes (careers, billing, marketing...) which are only used if nothing else exists.
GEN_ORDER = [("office", "info", "contact", "hello", "admin", "owner", "mail", "inquiries", "inquiry", "team"),
             ("frontdesk", "front.desk", "frontoffice", "reception", "appointments", "appointment", "schedule", "scheduling",
              "smile", "smiles", "patients", "clinic", "dental", "law", "legal", "staff"),
             ("service", "support", "help", "care", "customerservice", "cs"),
             ("sales",)]
BACK_OFFICE = ("career", "jobs", "job", "hr", "hiring", "recruit", "billing", "accounts", "accounting", "invoice", "ap@",
               "payable", "payroll", "marketing", "media", "press", "pr@", "privacy", "legal-notice", "webmaster", "web@",
               "events", "donate", "volunteer", "orders", "returns", "shipping", "warranty", "parts")

def general_rank(e):
    local = e.split("@")[0].lower()
    if any(local.startswith(b.rstrip("@")) for b in BACK_OFFICE): return 9
    for i, group in enumerate(GEN_ORDER):
        if any(local == g or local.startswith(g) for g in group): return i
    return 5

def best_contact(emails, text):
    """Pick the email + the name to greet. Returns dict(email, email_type, first_name, contact_name, contact_role)."""
    ppl = people(text)
    dm = [p for p in ppl if p[0] <= 3]
    pick = None
    for rank, kind, f, l, dr in dm:                         # 1. a decision maker's own address
        for e in emails:
            if not is_general(e) and matches(e, f, l):
                pick = (e, "owner" if rank <= 2 else "manager", f, l, kind, dr); break
        if pick: break
    if not pick:                                              # 2. any named person's own address
        for e in emails:
            if is_general(e): continue
            for rank, kind, f, l, dr in ppl:
                if matches(e, f, l): pick = (e, "named", f, l, kind, dr); break
            if pick: break
            fn = R.first_name(e)
            if fn and not pick: pick = (e, "named", fn, "", "", False)
    if not pick:                                              # 3. the general inbox, greeting the decision maker
        gen = sorted([e for e in emails if is_general(e)] or emails, key=general_rank)
        if not gen: return None
        if dm:
            rank, kind, f, l, dr = dm[0]
            pick = (gen[0], "general", f, l, kind, dr)
        else:
            pick = (gen[0], "general", "", "", "", False)
    e, typ, f, l, kind, dr = pick
    greet = f"Dr. {l}" if dr and l else f
    return {"email": e, "email_type": typ, "first_name": greet, "contact_name": f"{f} {l}".strip(), "contact_role": kind}
