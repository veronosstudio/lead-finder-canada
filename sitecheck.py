"""Kash (Nov 25): is a lead's website still up and showing signs of life? Shared by requalify.py and the top-up."""
import requests
import refine as R
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

def site_state(url):
    """"up", "abandoned" (old copyright and nothing current), "down", or "no site"."""
    if not url: return "no site"
    url = url if url.startswith("http") else "https://" + url
    s = requests.Session()
    for u in (url.replace("http://", "https://", 1), url.replace("https://", "http://", 1)):
        try:
            r = s.get(u, timeout=20, headers={"User-Agent": UA}, allow_redirects=True)
        except Exception:
            continue
        if r.status_code >= 400: continue
        return "abandoned" if R.looks_abandoned(r.text[:600000]) else "up"
    return "down"
