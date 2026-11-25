"""Shared email hygiene for the scraper and the Instantly top-up (Kash, Nov 24: stop bounces at the source).

clean_email(e)  -> tidied address ("" if it can't be one)
junk_email(e)   -> True for template / placeholder / file-name addresses
same_site(e, d) -> True when the address is on the business's own domain (proper dot boundary)
verify(emails)  -> {email: "ok" | "catchall" | "bad" | "unknown"}  (catchall = server accepts anything, so unconfirmed) using the Reacher CLI (REACHER_BIN); no binary -> all "unknown"
"""
import os, re, json, subprocess
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor

EMAIL_FULL = re.compile(r"[a-z0-9][a-z0-9._+'-]{0,63}@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,24}")
JUNK_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "email.com", "yourdomain.com", "yoursite.com", "mysite.com",
                "website.com", "company.com", "test.com", "sentry.io", "wixpress.com", "sentry-next.wixpress.com", "godaddy.com",
                "squarespace.com", "mail.com", "dental.com", "yourcompany.com", "business.com", "site.com", "address.com"}
JUNK_LOCAL = re.compile(r"^(?:your(?:name|email)?|name|user|username|email|test|sample|example|someone|john\.?doe|jane\.?doe|first\.?last|firstname|noreply|no-reply|donotreply|webmaster|postmaster|hostmaster|abuse|privacy)$")
FILE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".pdf", ".ico")

def clean_email(e):
    e = unquote(unquote(str(e or ""))).strip().lower()
    e = re.sub(r"^(?:mailto:|[\s<>\"'(\[]+)+", "", e)
    e = e.split("?")[0].strip(" .;,:<>\"'()[]")
    return e if EMAIL_FULL.fullmatch(e) else ""

def junk_email(e):
    if not e or not EMAIL_FULL.fullmatch(e): return True
    local, dom = e.split("@", 1)
    return (dom in JUNK_DOMAINS or e.endswith(FILE_EXT) or bool(JUNK_LOCAL.match(local))
            or "@2x" in e or re.search(r"\d{5,}", local) is not None or local.startswith(".") or ".." in e)

def same_site(e, site_domain):
    dom, site = e.split("@", 1)[1], (site_domain or "").lower().removeprefix("www.")
    return bool(site) and (dom == site or dom.endswith("." + site) or site.endswith("." + dom))

def verify(emails, workers=24):
    emails = list(dict.fromkeys(emails))
    binp = os.environ.get("REACHER_BIN", "")
    if not binp or not os.path.exists(binp): return {e: "unknown" for e in emails}
    def one(e):
        try:
            p = subprocess.run([binp, "--from-email", "hello@veronosstudio.com", "--hello-name", "veronosstudio.com", e],
                               capture_output=True, text=True, timeout=90)
            j = json.loads(p.stdout); smtp = j.get("smtp") if isinstance(j.get("smtp"), dict) else {}
            r = j.get("is_reachable")
            if r == "invalid": return "bad"
            if r == "risky" and smtp.get("is_catch_all") is False and smtp.get("is_deliverable") is False: return "bad"
            if r in ("safe", "risky"):
                return "catchall" if smtp.get("is_catch_all") else "ok"
            return "unknown"
        except Exception:
            return "unknown"
    with ThreadPoolExecutor(workers) as ex:
        return dict(zip(emails, ex.map(one, emails)))
