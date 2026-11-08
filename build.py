#!/usr/bin/env python3
"""
MENA Signal - builds a minimalist front page of Middle East geopolitics,
defence and naval news. Every story links out to its original publisher.

Usage:  python build.py        -> writes site/index.html
Only uses the Python standard library.
"""
import concurrent.futures as cf
import email.utils
import html
import json
import math
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site"
TEMPLATE = ROOT / "template.html"

SITE_NAME = "MENA Signal"
NEWS_WINDOW_H = 72          # news older than this is dropped
SPECIALIST_WINDOW_D = 7     # defence/naval trade press has less Middle East volume
ANALYSIS_WINDOW_D = 14      # think-tank pieces publish slower
OG_LOOKUPS = 160            # max article pages fetched to find a missing image
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# regional=True  -> every story is in scope (feed is Middle East only)
# regional=False -> story must mention the region to be kept
FEEDS = [
    # --- Geopolitics & regional news
    dict(name="Al-Monitor", url="https://www.al-monitor.com/rss", cat="geopolitics", regional=True),
    dict(name="Middle East Eye", url="https://www.middleeasteye.net/rss", cat="geopolitics", regional=True),
    dict(name="BBC Middle East", url="https://feeds.bbci.co.uk/news/world/middle_east/rss.xml", cat="geopolitics", regional=True),
    dict(name="Al Jazeera", url="https://www.aljazeera.com/xml/rss/all.xml", cat="geopolitics"),
    dict(name="The National", url="https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml", cat="geopolitics"),
    dict(name="Arab News", url="https://www.arabnews.com/rss.xml", cat="geopolitics"),
    dict(name="Asharq Al-Awsat", url="https://english.aawsat.com/feed", cat="geopolitics"),
    dict(name="Al Arabiya", url="https://english.alarabiya.net/feed/rss2/en.xml", cat="geopolitics"),
    dict(name="Times of Israel", url="https://www.timesofisrael.com/feed/", cat="geopolitics", regional=True),
    dict(name="Amwaj.media", url="https://amwaj.media/feed", cat="geopolitics", regional=True),
    dict(name="Foreign Policy", url="https://foreignpolicy.com/feed/", cat="geopolitics"),
    # --- Defence
    dict(name="Defense News", url="https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", cat="defence"),
    dict(name="Breaking Defense", url="https://breakingdefense.com/feed/", cat="defence"),
    dict(name="The War Zone", url="https://www.twz.com/feed", cat="defence"),
    dict(name="The Defense Post", url="https://thedefensepost.com/feed/", cat="defence"),
    dict(name="Defense One", url="https://www.defenseone.com/rss/all/", cat="defence"),
    dict(name="Defence Blog", url="https://defence-blog.com/feed/", cat="defence"),
    dict(name="Army Technology", url="https://www.army-technology.com/feed/", cat="defence"),
    dict(name="Airforce Technology", url="https://www.airforce-technology.com/feed/", cat="defence"),
    dict(name="Naval Technology", url="https://www.naval-technology.com/feed/", cat="naval"),
    # --- Naval & maritime
    dict(name="Naval News", url="https://www.navalnews.com/feed/", cat="naval"),
    dict(name="USNI News", url="https://news.usni.org/feed", cat="naval"),
    dict(name="gCaptain", url="https://gcaptain.com/feed/", cat="naval"),
    dict(name="Splash247", url="https://splash247.com/feed/", cat="naval"),
    dict(name="Maritime Executive", url="https://maritime-executive.com/articles.rss", cat="naval"),
    # --- Analysis & think tanks
    dict(name="Washington Institute", url="https://www.washingtoninstitute.org/rss.xml", cat="analysis", regional=True),
    dict(name="Atlantic Council", url="https://www.atlanticcouncil.org/feed/", cat="analysis"),
    dict(name="Crisis Group", url="https://www.crisisgroup.org/rss", cat="analysis"),
    dict(name="ECFR", url="https://ecfr.eu/feed/", cat="analysis"),
    dict(name="War on the Rocks", url="https://warontherocks.com/feed/", cat="analysis"),
    dict(name="Stimson Center", url="https://www.stimson.org/feed/", cat="analysis"),
]

COUNTRIES = {
    "Iran": ["iran", "iranian", "tehran", "irgc", "khamenei", "pezeshkian"],
    "Israel": ["israel", "israeli", "idf", "netanyahu", "tel aviv", "jerusalem"],
    "Palestine": ["gaza", "hamas", "west bank", "palestine", "palestinian", "palestinians"],
    "Lebanon": ["lebanon", "lebanese", "beirut", "hezbollah"],
    "Syria": ["syria", "syrian", "damascus", "aleppo"],
    "Iraq": ["iraq", "iraqi", "baghdad", "erbil", "kurdistan"],
    "Saudi Arabia": ["saudi", "riyadh", "jeddah", "bin salman", "neom", "aramco"],
    "UAE": ["uae", "emirati", "emirates", "abu dhabi", "dubai"],
    "Qatar": ["qatar", "qatari", "doha"],
    "Oman": ["oman", "omani", "muscat"],
    "Bahrain": ["bahrain", "bahraini", "manama"],
    "Kuwait": ["kuwait", "kuwaiti"],
    "Yemen": ["yemen", "yemeni", "houthi", "houthis", "sanaa", "aden"],
    "Egypt": ["egypt", "egyptian", "cairo", "sisi", "suez", "sinai"],
    "Jordan": ["jordan", "jordanian", "amman"],
    "Turkey": ["turkey", "turkiye", "türkiye", "turkish", "ankara", "erdogan", "erdoğan"],
}
REGION_TERMS = ["middle east", "mena", "levant", "gcc", "gulf", "persian gulf", "arabian gulf",
                "red sea", "hormuz", "bab el-mandeb", "bab al-mandab", "eastern mediterranean",
                "arab", "kurdish", "kurds", "libya", "sudan", "djibouti", "opec"]
NOT_REGION = ["gulf of mexico", "gulf of america", "gulf coast", "gulf of alaska", "gulf of finland",
              "gulf of guinea", "gulf of thailand", "gulf of aden"]  # aden re-added via Yemen terms

CATEGORY_TERMS = {
    "naval": ["navy", "naval", "warship", "warships", "frigate", "frigates", "corvette", "destroyer",
              "submarine", "submarines", "aircraft carrier", "carrier strike", "fleet", "maritime",
              "shipping", "vessel", "vessels", "tanker", "tankers", "strait", "red sea", "hormuz",
              "suez canal", "port", "coast guard", "sailors", "minehunter", "amphibious", "seized ship",
              "cargo ship", "bulk carrier", "container ship", "sea lane", "patrol boat", "uss"],
    "defence": ["missile", "missiles", "drone", "drones", "uav", "fighter jet", "fighter jets", "f-35",
                "f-16", "f-15", "rafale", "eurofighter", "typhoon", "air defense", "air defence",
                "patriot", "thaad", "iron dome", "arrow", "david's sling", "arms sale", "arms deal",
                "procurement", "defense contract", "defence contract", "defense industry",
                "defence industry", "military exercise", "drill", "drills", "tank", "tanks",
                "artillery", "weapons", "edge group", "sami", "air force", "helicopter",
                "pentagon", "radar", "munitions", "interceptor", "ballistic", "cruise missile",
                "defense", "defence", "military", "armed forces", "army", "military aid",
                "defense minister", "defence minister", "warplane", "warplanes", "cyberattack"],
    "security": ["attack", "attacks", "strike", "strikes", "airstrike", "airstrikes", "militia",
                 "militias", "hezbollah", "houthi", "houthis", "hamas", "isis", "islamic state",
                 "terror", "terrorist", "ceasefire", "killed", "clashes", "war", "conflict",
                 "border", "raid", "hostage", "hostages", "insurgent", "bombing", "shelling",
                 "casualties", "displaced", "offensive", "troops", "rebel", "rebels", "rsf",
                 "humanitarian", "refugees", "detainees", "settlers", "armed factions", "barrage"],
    "geopolitics": ["diplomacy", "diplomatic", "talks", "summit", "sanctions", "opec", "oil",
                    "normalization", "normalisation", "election", "elections", "president",
                    "prime minister", "foreign minister", "minister", "visit", "agreement",
                    "relations", "china", "chinese", "russia", "russian", "washington", "trump",
                    "trade", "economy", "nuclear deal", "nuclear talks", "envoy", "united nations",
                    "un security council", "investment", "energy", "gas", "lng", "abraham accords",
                    "mediation", "negotiations", "parliament", "government"],
}
CATEGORY_ORDER = ["geopolitics", "defence", "naval", "security", "analysis"]

# Stories matching these are dropped (lifestyle, sport, ads...)
NOISE_TERMS = ["sponsored", "sponsored content", "restaurant", "restaurants", "recipe", "recipes",
               "wwe", "football", "soccer", "head coach", "fifa", "cricket", "tennis", "golf",
               "formula 1", "f1", "celebrity", "film", "movie", "box office", "fashion", "travel",
               "hotel", "diwali", "concert", "festival", "horoscope", "podcast", "quiz", "crossword",
               "things to do", "beach", "daily briefing", "what's on", "netflix", "album", "singer",
               "real estate", "property prices", "salary", "visa rules", "school holidays", "ramadan timings"]

STOPWORDS = set("""the a an and or of to in on for with at by from as is are was were be been
its it this that after over says said new into amid about will could would may has have had
not but than more out up off how why what who us news report reports""".split())


# ------------------------------------------------------------------ helpers

def phrase_regex(terms):
    parts = sorted({re.escape(t) for t in terms}, key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(parts) + r")(?![\w-])", re.I)


REGION_RE = phrase_regex(REGION_TERMS + [t for ts in COUNTRIES.values() for t in ts])
NOT_REGION_RE = phrase_regex(NOT_REGION)
COUNTRY_RES = {c: phrase_regex(ts) for c, ts in COUNTRIES.items()}
CAT_RES = {c: phrase_regex(ts) for c, ts in CATEGORY_TERMS.items()}
NOISE_RE = phrase_regex(NOISE_TERMS)


def relevant(it):
    """Must touch geopolitics/defence/naval/security, and not be lifestyle or sport."""
    if it["feed_cat"] == "analysis":
        return True
    text = f"{it['title']} {it['summary']}"
    if NOISE_RE.search(it["title"]) or "sponsored" in it["link"].lower():
        return False
    return any(rx.search(text) for rx in CAT_RES.values())


def http_get(url, timeout=15, limit=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit) if limit else r.read()


def localname(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def clean_text(s, words=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*(The post .* appeared first on .*|Continue reading.*|Read more.*)$", "", s, flags=re.I)
    if words:
        w = s.split()
        if len(w) > words:
            s = " ".join(w[:words]).rstrip(",;:.") + "…"
    return s


def parse_date(s):
    if not s:
        return None
    d = None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def shrink_image(url):
    """Ask image resizers (Arc XP, WordPress) for ~1200px wide images instead of originals."""
    if not url:
        return url
    p = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(p.query, keep_blank_values=True))
    try:
        w = int(q.get("width") or q.get("w") or 0)
    except ValueError:
        return url
    if w > 1400:
        key = "width" if "width" in q else "w"
        hkey = "height" if "height" in q else ("h" if "h" in q else None)
        if hkey:
            try:
                q[hkey] = str(round(int(q[hkey]) * 1200 / w))
            except ValueError:
                q.pop(hkey)
        q[key] = "1200"
        return urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode(q)))
    return url


IMG_IN_HTML = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def first_img(htmltext):
    for m in IMG_IN_HTML.finditer(htmltext or ""):
        src = html.unescape(m.group(1))
        if any(b in src.lower() for b in ("pixel", "feedburner", "gravatar", "emoji", "1x1", "spacer")):
            continue
        return src
    return None


# ------------------------------------------------------------------ parsing

def parse_item(el, feed):
    title = link = date = desc = content = img = None
    for c in el:
        ln = localname(c.tag)
        ns = c.tag.split("}")[0] if "}" in c.tag else ""
        txt = (c.text or "").strip()
        if "search.yahoo.com/mrss" in ns:
            for m in c.iter():
                if localname(m.tag) in ("content", "thumbnail") and m.get("url"):
                    medium, typ = m.get("medium", ""), m.get("type", "")
                    if not img and (medium == "image" or typ.startswith("image") or
                                    localname(m.tag) == "thumbnail" or not (medium or typ)):
                        img = m.get("url")
            continue
        if ln == "title":
            title = title or clean_text("".join(c.itertext()))
        elif ln == "link":
            href = c.get("href")
            if href:
                rel = c.get("rel", "alternate")
                if rel == "alternate" and not link:
                    link = href
                elif rel == "enclosure" and "image" in (c.get("type") or "") and not img:
                    img = href
            elif txt and not link:
                link = txt
        elif ln == "guid" and txt.startswith("http") and c.get("isPermaLink", "true") != "false":
            link = link or txt
        elif ln in ("pubDate", "published", "updated", "date", "issued"):
            date = date or txt
        elif ln in ("description", "summary"):
            desc = desc or "".join(c.itertext())
        elif ln in ("encoded", "content"):
            content = content or "".join(c.itertext())
        elif ln == "enclosure" and "image" in (c.get("type") or "") and not img:
            img = c.get("url")
        elif ln == "image" and not img:
            img = c.get("href") or c.get("url") or txt or None
    if not title or not link:
        return None
    img = img or first_img(content) or first_img(desc)
    if img and img.startswith("//"):
        img = "https:" + img
    return dict(title=title, link=link.strip(), date=parse_date(date),
                summary=clean_text(desc or content, words=28), img=img,
                source=feed["name"], feed_cat=feed["cat"], regional=feed.get("regional", False))


def parse_feed(data, feed):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        data = re.sub(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", b"", data)
        data = re.sub(rb"&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)", b"&amp;", data)
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return parse_items_one_by_one(data, feed)
    out = []
    for el in root.iter():
        if localname(el.tag) in ("item", "entry"):
            it = parse_item(el, feed)
            if it:
                out.append(it)
    return out


def parse_items_one_by_one(data, feed):
    """Fallback for broken feeds: parse each <item> on its own, skip the bad ones."""
    head = data[:4000].decode("utf-8", "ignore")
    nsdecl = " ".join(dict.fromkeys(re.findall(r'xmlns:\w+="[^"]+"', head)))
    out = []
    for blob in re.findall(rb"<item[\s>].*?</item>", data, re.S):
        try:
            el = ET.fromstring(b"<rss " + nsdecl.encode() + b">" + blob + b"</rss>")
            it = parse_item(el.find("item"), feed)
            if it:
                out.append(it)
        except ET.ParseError:
            continue
    return out


def fetch_feed(feed):
    try:
        items = parse_feed(http_get(feed["url"]), feed)
        return feed, items, None
    except Exception as e:  # noqa: BLE001
        return feed, [], f"{type(e).__name__}: {e}"[:120]


def fetch_og_image(url):
    try:
        page = http_get(url, timeout=8, limit=400_000).decode("utf-8", "ignore")
    except Exception:
        return None
    for prop in ("og:image", "twitter:image", "twitter:image:src"):
        for tag in re.findall(r"<meta[^>]+>", page, re.I):
            if re.search(r"(?:property|name)=[\"']" + re.escape(prop) + r"[\"']", tag, re.I):
                m = re.search(r"content=[\"']([^\"']+)[\"']", tag, re.I)
                if m:
                    return urllib.parse.urljoin(url, html.unescape(m.group(1)))
    return None


# ------------------------------------------------------------------ logic

def in_region(it):
    text = NOT_REGION_RE.sub(" ", f"{it['title']} {it['summary']}")
    if "gulf of aden" in f"{it['title']} {it['summary']}".lower():
        return True
    return bool(REGION_RE.search(text))


def categorise(it):
    if it["feed_cat"] == "analysis":
        return "analysis"
    scores = {c: 0.0 for c in CATEGORY_TERMS}
    scores[it["feed_cat"]] += 1.0
    for c, rx in CAT_RES.items():
        scores[c] += 2 * len(rx.findall(it["title"])) + len(rx.findall(it["summary"]))
    return max(scores, key=lambda c: (scores[c], -CATEGORY_ORDER.index(c)))


def countries_of(it):
    text = f"{it['title']} {it['summary']}"
    return [c for c, rx in COUNTRY_RES.items() if rx.search(text)]


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9']+", title.lower()) if len(w) > 2 and w not in STOPWORDS}


def cluster(items):
    """Group stories about the same event (similar headlines)."""
    groups = []
    for it in items:
        tk = tokens(it["title"])
        for g in groups:
            inter = len(tk & g["tk"])
            if inter >= 3 and inter / max(1, len(tk | g["tk"])) >= 0.4:
                g["items"].append(it)
                g["tk"] |= tk
                break
        else:
            groups.append(dict(tk=set(tk), items=[it]))
    return [g["items"] for g in groups]


def main():
    now = datetime.now(timezone.utc)
    print(f"Fetching {len(FEEDS)} feeds…")
    raw, report = [], []
    with cf.ThreadPoolExecutor(max_workers=14) as ex:
        for feed, items, err in ex.map(fetch_feed, FEEDS):
            raw.extend(items)
            report.append((feed["name"], len(items), err))
    for name, n, err in sorted(report):
        print(f"  {'FAIL' if err else 'ok  '} {name:<22} {n:>3} items {err or ''}")

    # time window, region filter, dedupe by URL
    seen, kept = set(), []
    for it in raw:
        d = it["date"] or now
        if it["feed_cat"] == "analysis":
            window = timedelta(days=ANALYSIS_WINDOW_D)
        elif it["feed_cat"] in ("defence", "naval"):
            window = timedelta(days=SPECIALIST_WINDOW_D)
        else:
            window = timedelta(hours=NEWS_WINDOW_H)
        if d > now + timedelta(hours=1) or now - d > window:
            continue
        if not it["regional"] and not in_region(it):
            continue
        if not relevant(it):
            continue
        key = it["link"].split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        it["date"] = d
        kept.append(it)
    print(f"{len(raw)} raw items -> {len(kept)} in scope")

    # fill in missing images from the article's og:image
    missing = sorted([i for i in kept if not i["img"]], key=lambda i: i["date"], reverse=True)[:OG_LOOKUPS]
    if missing:
        print(f"Looking up {len(missing)} missing images…")
        with cf.ThreadPoolExecutor(max_workers=20) as ex:
            for it, img in zip(missing, ex.map(lambda i: fetch_og_image(i["link"]), missing)):
                it["img"] = img

    for it in kept:
        it["cat"] = categorise(it)
        it["countries"] = countries_of(it)

    # cluster same-event stories; keep one representative, list the others
    news = sorted([i for i in kept if i["cat"] != "analysis"], key=lambda i: i["date"], reverse=True)
    analysis = [i for i in kept if i["cat"] == "analysis"]
    stories = []
    for grp in cluster(news):
        rep = max(grp, key=lambda i: (bool(i["img"]), len(i["summary"]) > 40, i["date"]))
        others, srcs = [], {rep["source"]}
        for o in grp:
            if o["source"] not in srcs:
                srcs.add(o["source"])
                others.append(dict(source=o["source"], link=o["link"]))
        rep["also"] = others
        rep["countries"] = sorted({c for o in grp for c in o["countries"]})
        stories.append(rep)
    for a in analysis:
        a["also"] = []
    stories += analysis

    def score(it):
        age_h = max(0.0, (now - it["date"]).total_seconds() / 3600)
        return round(10 * math.exp(-age_h / 18) + 2.0 * len(it["also"]) + (1.0 if it["img"] else 0), 3)

    out = []
    for it in stories:
        out.append(dict(
            title=it["title"], link=it["link"], source=it["source"],
            domain=urllib.parse.urlparse(it["link"]).netloc.replace("www.", ""),
            cat=it["cat"], countries=it["countries"], date=it["date"].isoformat(),
            summary=it["summary"], img=shrink_image(it["img"]), also=it["also"], score=score(it)))
    out.sort(key=lambda i: i["score"], reverse=True)

    sources = {n for n, c, e in report if c and not e}
    payload = dict(site=SITE_NAME, updated=now.isoformat(), items=out, sources=[
        dict(name=f["name"], url="https://" + urllib.parse.urlparse(f["url"]).netloc, cat=f["cat"])
        for f in FEEDS if f["name"] in sources])

    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data).replace("__SITE__", SITE_NAME)
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(page, encoding="utf-8")
    counts = {c: sum(1 for i in out if i["cat"] == c) for c in CATEGORY_ORDER}
    print(f"Wrote {OUT / 'index.html'}  ({len(out)} stories: {counts})")


if __name__ == "__main__":
    sys.exit(main())
