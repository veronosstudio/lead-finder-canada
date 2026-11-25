"""Kash (Nov 25): website checks shared by requalify.py and the top-up.

fetch(url)        -> (state, html): "up" | "abandoned" | "parked" | "down" | "no site"; hard 25s limit per site
phone_fit(urls)   -> {url: True/False/None}: opens each site at phone size in a real browser.
                     False = sideways scrolling or tiny text (the "doesn't fit a phone" claim is true), None = couldn't load.
"""
import os, time, asyncio
import requests
import refine as R

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
MAX_BYTES, LIMIT_S = 600_000, 25


def _get(url, s):
    """GET with a hard overall deadline (some servers trickle data forever)."""
    t0 = time.time()
    r = s.get(url, timeout=(8, 12), headers={"User-Agent": UA}, allow_redirects=True, stream=True)
    buf = b""
    for chunk in r.iter_content(16384):
        buf += chunk
        if len(buf) >= MAX_BYTES or time.time() - t0 > LIMIT_S: break
    r.close()
    return r.status_code, buf.decode(r.encoding or "utf-8", "replace")


def fetch(url):
    if not url: return "no site", ""
    url = url if url.startswith("http") else "https://" + url
    s = requests.Session()
    for u in (url.replace("http://", "https://", 1), url.replace("https://", "http://", 1)):
        try:
            code, html = _get(u, s)
        except Exception:
            continue
        if code >= 400: continue
        if R.parked(html): return "parked", html
        if R.looks_abandoned(html): return "abandoned", html
        return "up", html
    return "down", ""


def site_state(url):
    return fetch(url)[0]


FIT_JS = """() => {
  const w = window.innerWidth, sw = document.documentElement.scrollWidth;
  let small = 0, total = 0;
  for (const el of document.querySelectorAll('p, li, a, span, td')) {
    const t = (el.innerText || '').trim(); if (t.length < 20) continue;
    const r = el.getBoundingClientRect(); if (r.width === 0) continue;
    total++; if (parseFloat(getComputedStyle(el).fontSize) < 11) small++;
  }
  // no mobile viewport: the phone shows a shrunken desktop page (layout wider than the screen) -> pinch and zoom
  return {sideways: sw > w + 8, tiny: total > 10 && small / total > 0.5, zoomed: w > 500};
}"""


async def _fit_all(urls, workers=6):
    if os.path.isdir("/opt/pw-browsers"): os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    from playwright.async_api import async_playwright
    out, sem = {}, asyncio.Semaphore(workers)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        async def one(u):
            async with sem:
                ctx = await b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                          user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
                pg = await ctx.new_page()
                try:
                    await pg.goto(u if u.startswith("http") else "https://" + u, wait_until="load", timeout=25000)
                    await pg.wait_for_timeout(800)
                    r = await pg.evaluate(FIT_JS)
                    out[u] = not (r["sideways"] or r["tiny"] or r["zoomed"])
                except Exception:
                    out[u] = None
                finally:
                    await ctx.close()
        await asyncio.gather(*[one(u) for u in urls])
        await b.close()
    return out


def phone_fit(urls, workers=6):
    urls = [u for u in dict.fromkeys(urls) if u]
    return asyncio.run(_fit_all(urls, workers)) if urls else {}
