"""Kash (Nov 24): one measurable business problem per lead -> {{notice}} (the fact), {{cost}} (what it costs them),
{{tip}} (a free fix for email 2). Every line must be true for that site."""
import re

def pick(why="", hook="", speed=None):
    w, h = (why or "").lower(), (hook or "").lower()
    not_mobile = "not built for phones" in w or "tough to get around" in h or "tough to use on a phone" in h
    not_secure = "no secure https" in w or "not secure" in h
    no_tap = "phone not tappable" in w
    m = re.search(r"easy way (?:for people )?to ([^.]+)", hook or "")
    no_book = bool(m)
    if speed and speed >= 6: return "speed"
    if not_mobile: return "mobile"
    if not_secure: return "secure"
    if speed and speed >= 4: return "speed"
    if no_tap: return "tap"
    if no_book: return "book"
    return "dated"

def lines(kind, speed=None):
    s = f"{round(speed)}" if speed else ""
    over = bool(speed and speed > 25)  # Google's test sometimes times out at 60-130s; nobody believes that number
    return {
        "speed":  ((f"takes over 20 seconds to load on a phone in Google's speed test." if over else f"takes about {s} seconds to load on a phone in Google's speed test."),
                   "Over half of people leave a site that takes longer than 3 seconds.",
                   "shrinking the big photos on your homepage usually cuts the load time in half."),
        "mobile": ("doesn't fit a phone screen, so people have to pinch and zoom.",
                   "Most people searching for you are on their phone, and a lot of them just hit back.",
                   "put a big tap-to-call button at the top of the page for people on their phone."),
        "secure": ('shows a "Not secure" warning in Chrome.',
                   "That's enough for a lot of people to leave before they ever call.",
                   "your web host can usually turn on a free security certificate in a few minutes, and the warning goes away."),
        "tap":    ("has a phone number you can't tap to call on mobile.",
                   "Some people won't bother copying it, so the call goes to whoever's next on Google.",
                   "make your phone number a tap-to-call link so people can reach you in one tap."),
        "book":   ("has no quick way to book or send a message.",
                   "People who aren't ready to call right then just leave.",
                   "add a simple contact form so people can reach you after hours."),
        "dated":  ("looks a few years old.",
                   "People judge a business by its website before they ever call.",
                   "put your phone number and a \"Get a quote\" button right at the top of your homepage."),
    }[kind]

def build(why="", hook="", speed=None):
    k = pick(why, hook, speed)
    n, c, t = lines(k, speed)
    return {"notice": n, "cost": c, "tip": t, "issue": k, "speed": speed or ""}
