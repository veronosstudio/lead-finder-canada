"""Google PageSpeed Insights (free) -> how long a site takes to load on a phone.
mobile_load(url) -> seconds (float, Largest Contentful Paint on Google's mobile test) or None.
Set PAGESPEED_KEY for a higher quota; works without one at low volume."""
import os, time, requests
API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

def mobile_load(url, tries=2):
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if os.environ.get("PAGESPEED_KEY"): params["key"] = os.environ["PAGESPEED_KEY"]
    for i in range(tries):
        try:
            r = requests.get(API, params=params, timeout=90)
            if r.status_code == 429: time.sleep(10 * (i + 1)); continue
            if not r.ok:
                if os.environ.get("SPEED_DEBUG"): print("PSI", r.status_code, r.text[:300])
                return None
            a = r.json()["lighthouseResult"]["audits"]
            ms = a.get("largest-contentful-paint", {}).get("numericValue") or a.get("speed-index", {}).get("numericValue")
            return round(ms / 1000, 1) if ms else None
        except Exception:
            time.sleep(3)
    return None

if __name__ == "__main__":
    import sys, json
    from concurrent.futures import ThreadPoolExecutor
    urls = sys.argv[1:]
    t = time.time()
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(mobile_load, urls))
    for u, s in zip(urls, res): print(f"{s}s  {u}")
    print(f"{sum(1 for s in res if s)}/{len(urls)} measured in {time.time()-t:.0f}s")
