#!/usr/bin/env python3
"""Map every page to a type (article, service page, location page, ...) and a place, before any pair is judged.

Usage:  python3 map_pages.py example.com                 fetch the clues from the live site, then classify
        python3 map_pages.py --reclassify example.com    classify again from the saved clues (no requests)
Why:    only two articles may be merged, so the system has to know which pages are articles. No single clue
        works on every site, so four are read and compared. When they disagree, the page is typed "unknown"
        and is never merged: the safe default for a site built in a way this code has not seen.
Reads:  ~/openclaw/data/<site>/analysis/pages.csv, url_status.csv (if present)
Writes: ~/openclaw/data/<site>/page_signals.json     what was fetched: sitemap lists and each page's own markup clues
        ~/openclaw/data/<site>/analysis/page_map.csv  url, page_type, place, confidence, and what each clue said
No API cost. Requests go to the site itself: its robots.txt and sitemaps, then one request per page, one every half second.

THE FOUR CLUES
  1. Sitemap     which child sitemap lists the page (post-sitemap.xml, page-sitemap.xml, podcast-sitemap.xml ...)
  2. Page code   the page's own markup: WordPress body class (single-post, page, blog ...), Article schema, publish-date tag
  3. URL         folders such as /blog/, /services/, /podcast/, /category/
  4. Google      whether Google shows a publish date beside the page's results (dated_share in pages.csv)
HOW THEY COMBINE
  - Clues 1 to 3 each vote for a family: article, standing page, media (podcast or video), or other.
  - One family named: that is the type. "confirmed" when two or more clues agree (Google's date counts as support).
  - More than one family named, and one of them is article: "unknown".
  - More than one family named, none of them article (a podcast episode built as an ordinary page, say): the page is
    typed by its most specific clue. Whichever clue is right, it is not an article, so it is never merged.
  - None of 1 to 3 available: Google's date decides alone ("publish date only"). No clue at all: "unknown".
  - A homepage or index page named by the URL or the page code is typed that way whatever the sitemap says
    (Yoast lists the blog index inside the post sitemap).
  - A standing page with the same US place in its URL and its title is a location page (us_places.txt).
"""
import csv, datetime, gzip, html, json, os, pathlib, re, sys, time, urllib.request

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
PLACES_FILE = pathlib.Path(__file__).with_name("us_places.txt")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
PAUSE_SECONDS = 0.5
MAX_BYTES = 3_000_000
MAX_CHILD_SITEMAPS = 60
ARTICLE_SHARE = 0.50          # Google shows a publish date on at least this share of the page's results
COLUMNS = ["url", "page_type", "place", "confidence", "sitemap_says", "page_code_says", "url_says", "google_date_says", "note"]

# what a post type's name means, wherever it shows up (sitemap file name, WordPress body class)
ARTICLE_WORDS = {"post", "posts", "blog", "blogs", "article", "articles", "news", "insight", "insights"}
MEDIA_WORDS = {"podcast", "podcasts", "episode", "episodes", "video", "videos", "webinar", "webinars"}
HUB_WORDS = {"category", "categories", "tag", "tags", "post_tag", "author", "authors", "topic", "topics"}
LOCATION_WORDS = {"location", "locations", "city", "cities", "area", "areas", "service_area", "service_areas"}
SERVICE_WORDS = {"service", "services", "practice_area", "practice_areas"}
FAMILY = {"article": "article", "media": "media", "other": "other", "homepage": "page", "hub": "page",
          "location": "page", "service": "page", "page": "page"}
SPECIFIC_FIRST = ["homepage", "hub", "location", "service", "page"]
PEOPLE_PATH = r"/(author|authors|team|staff|people|attorneys?|lawyers?|our-team|about)(/|$)"

URL_RULES = [
    (r"^/$", "homepage"),
    (r"^/(blog|news|articles|insights|portfolio|services|about|contact|resources|podcasts?|videos|events|locations)/?$", "hub"),
    (r"/(category|tag|author|topics?)/", "hub"),
    (r"/(podcasts?|episodes?|videos?|webinars?)/.", "media"),
    (r"/(blog|news|articles?|insights|posts?)/.|/(19|20)\d\d/\d\d/", "article"),
    (r"/(locations?|areas-we-serve|service-areas?|cities)/.", "location"),
    (r"/services?/.|-services/?$", "service"),
    (r"/(events?|venues?|case[-_]stud(y|ies))/.", "other"),
]

words = lambda text: re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()
path_of = lambda url: "/" + url.split("://", 1)[-1].split("/", 1)[-1].split("?")[0].split("#")[0] if "/" in url.split("://", 1)[-1] else "/"
host_of = lambda url: url.split("://", 1)[-1].split("/", 1)[0].lower()


def url_key(url):
    """One spelling per page, so a sitemap entry matches the ranking data: no scheme, no www, no query, no trailing slash."""
    rest = url.split("://", 1)[-1].split("?")[0].split("#")[0].lower()
    return re.sub(r"^www\.", "", rest).rstrip("/")


def load_places(path=PLACES_FILE):
    """{tuple of words: name to show}, e.g. ('new', 'york'): 'New York'."""
    places = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            name, shown, _ = line.split("\t")
            places[tuple(name.split())] = shown
    return places


def find_place(text, places):
    """The first US place named in the text, longest name first ('kansas city' before 'kansas'). '' if none."""
    tokens = words(text)
    longest = max((len(k) for k in places), default=0)
    for start in range(len(tokens)):
        for size in range(min(longest, len(tokens) - start), 0, -1):
            shown = places.get(tuple(tokens[start:start + size]))
            if shown:
                return shown
    return ""


def kind_of_post_type(token):
    token = token.lower().strip("-_")
    if token in ARTICLE_WORDS:
        return "article"
    if token in MEDIA_WORDS or any(word in token for word in ("podcast", "episode", "video", "webinar")):
        return "media"
    if token in HUB_WORDS or token.endswith(("_category", "_tag", "-category", "-tag")):
        return "hub"
    if token in LOCATION_WORDS:
        return "location"
    if token in SERVICE_WORDS:
        return "service"
    if token in ("page", "pages"):
        return "page"
    return "other"


def sitemap_says(name):
    """What a child sitemap's file name says about the pages it lists. (label, text) or (None, text)."""
    if not name:
        return None, ""
    file = name.rsplit("/", 1)[-1].lower()
    core = re.match(r"wp-sitemap-(posts|taxonomies|users)-?([a-z0-9_]*?)-?\d*\.xml", file)      # WordPress's built-in sitemaps
    if core:
        label = "hub" if core.group(1) != "posts" else kind_of_post_type(core.group(2))
        return label, f"{label} ({file})"
    noise = {"sitemap", "sitemaps", "wp", "pt", "tax", "xml", "gz", "index", "main", ""}
    tokens = [t for t in re.split(r"[-.]", file) if t not in noise and not t.isdigit()]
    known = [kind_of_post_type(t) for t in tokens if kind_of_post_type(t) != "other"]
    if known:                                                                                    # post-sitemap.xml, sitemap-pt-post-2024-01.xml
        return known[0], f"{known[0]} ({file})"
    if re.match(r"[a-z0-9_-]+?[-_]sitemap\d*\.xml", file):                                       # a post type this code has no name for
        return "other", f"other ({file})"
    return None, f"listed in {file}, which does not state a type"


def page_code_says(clues):
    """What the page's own markup says. clues: {body_class, schema_types, published_time}."""
    if not clues:
        return None, ""
    classes = set((clues.get("body_class") or "").lower().split())
    if "home" in classes:
        return "homepage", "homepage (body class home)"
    if classes & {"blog", "archive", "category", "tag", "author", "search"}:
        return "hub", f"hub (body class {sorted(classes & {'blog', 'archive', 'category', 'tag', 'author', 'search'})[0]})"
    single = sorted(c for c in classes if c.startswith("single-") and not c.startswith("single-format"))
    if single:
        label = kind_of_post_type(single[0][len("single-"):])
        return label, f"{label} (body class {single[0]})"
    if "page" in classes or any(c.startswith(("page-template", "page-id-")) for c in classes):
        return "page", "page (body class page)"
    schema = set(clues.get("schema_types") or [])
    if schema & {"PodcastEpisode", "Episode", "RadioEpisode"}:
        return "media", "media (schema PodcastEpisode)"
    if schema & {"Article", "BlogPosting", "NewsArticle", "TechArticle"}:
        return "article", "article (schema " + sorted(schema & {"Article", "BlogPosting", "NewsArticle", "TechArticle"})[0] + ")"
    if schema & {"CollectionPage", "Blog"}:
        return "hub", "hub (schema CollectionPage)"
    if clues.get("published_time"):
        return "article", "article (publish-date tag in the page)"
    return None, "no type clue in the page's code"


def url_says(url):
    path = path_of(url).lower()
    for pattern, label in URL_RULES:
        if re.search(pattern, path):
            return label, f"{label} (URL pattern)"
    return None, "the URL has no telling folder"


def google_says(dated_share):
    if dated_share in ("", None):
        return None, "no ranking results to check"
    dated = float(dated_share) >= ARTICLE_SHARE
    return ("dated" if dated else "undated"), f"publish date shown on {float(dated_share):.0%} of results"


def classify(url, title, dated_share, sitemap_name, clues, places, sitemaps_found=True):
    """One row of page_map.csv. Pure: no requests."""
    votes = []
    listed = sitemap_says(sitemap_name)
    if not sitemap_name:
        listed = (None, "not listed in the sitemap" if sitemaps_found else "no sitemap found")
    coded, addressed, google = page_code_says(clues), url_says(url), google_says(dated_share)
    for source, (label, _) in (("sitemap", listed), ("page code", coded), ("URL", addressed)):
        if label:
            votes.append((source, label))
    structural = [label for source, label in votes if source != "sitemap" and label in ("homepage", "hub")]
    families = {FAMILY[label] for _, label in votes}
    note = ""
    if structural:
        page_type = "homepage" if "homepage" in structural else "hub"
        agreeing = sum(1 for _, label in votes if FAMILY[label] == "page")
        confidence = "confirmed" if agreeing >= 2 else "one signal"
        if len(families) > 1:
            note = "its URL or code marks it as a homepage or index, which outranks the sitemap"
    elif len(families) > 1 and "article" in families:
        page_type, confidence = "unknown", "signals disagree"
        note = "; ".join(f"{source} says {label}" for source, label in votes)
    elif len(families) > 1:
        labels = [label for _, label in votes]
        page_type = "media" if "media" in labels else "other" if "other" in labels else next(l for l in SPECIFIC_FIRST if l in labels)
        confidence = "confirmed"
        note = "no clue says article; they differ on the kind of page: " + "; ".join(f"{source} says {label}" for source, label in votes)
    elif families:
        family = families.pop()
        labels = [label for _, label in votes]
        page_type = next(l for l in SPECIFIC_FIRST if l in labels) if family == "page" else family
        agrees = google[0] and ((family == "article") == (google[0] == "dated")) and family in ("article", "page")
        confidence = "confirmed" if len(votes) + bool(agrees) >= 2 else "one signal"
        if google[0] and family in ("article", "page") and not agrees:
            note = f"Google's publish date points the other way ({google[1]}); the site's own clues outrank it"
    elif google[0]:
        page_type, confidence = ("article" if google[0] == "dated" else "page"), "publish date only"
    else:
        page_type, confidence = "unknown", "no signal"
    place = ""
    if not re.search(PEOPLE_PATH, path_of(url).lower()):
        in_url, in_title = find_place(path_of(url), places), find_place(title, places)
        if in_url and in_url == in_title:
            place = in_url
    if page_type in ("page", "service") and place:
        page_type = "location"
    return {"url": url, "page_type": page_type, "place": place, "confidence": confidence, "sitemap_says": listed[1],
            "page_code_says": coded[1], "url_says": addressed[1], "google_date_says": google[1], "note": note}


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(MAX_BYTES)
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def locs(xml):
    """Page or child-sitemap addresses in a sitemap file. Image and video entries (<image:loc>) are not matched."""
    found = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", xml, flags=re.S)
    return [html.unescape(u.strip()) for u in found if u.strip()]


def read_sitemaps(host, fetch=download, pause=PAUSE_SECONDS):
    """{child sitemap address: [page addresses]} for one host. Empty when the site publishes no sitemap."""
    starts = []
    try:
        robots = fetch(f"https://{host}/robots.txt")
        starts = [line.split(":", 1)[1].strip() for line in robots.splitlines() if line.lower().startswith("sitemap:")]
    except Exception:
        pass
    starts += [f"https://{host}/sitemap_index.xml", f"https://{host}/sitemap.xml", f"https://{host}/wp-sitemap.xml"]
    out, tried = {}, set()
    for start in starts:
        if start in tried or out:
            continue
        tried.add(start)
        try:
            xml = fetch(start)
        except Exception:
            continue
        time.sleep(pause)
        if "<sitemapindex" in xml:
            for child in locs(xml)[:MAX_CHILD_SITEMAPS]:
                try:
                    out[child] = locs(fetch(child))
                except Exception:
                    out[child] = []
                time.sleep(pause)
        elif "<urlset" in xml:
            out[start] = locs(xml)
    return out


def page_clues(page_html):
    """The type clues a page carries in its own markup."""
    body = re.search(r"<body[^>]*\bclass\s*=\s*[\"']([^\"']*)[\"']", page_html, flags=re.I)
    published = re.search(r"<meta[^>]+property\s*=\s*[\"']article:published_time[\"'][^>]*>", page_html, flags=re.I)
    types = set()
    def walk(node):
        if isinstance(node, dict):
            kind = node.get("@type")
            for value in kind if isinstance(kind, list) else [kind]:
                if isinstance(value, str):
                    types.add(value)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    for block in re.findall(r"<script[^>]+type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page_html, flags=re.S | re.I):
        try:
            walk(json.loads(block))
        except ValueError:
            pass
    return {"body_class": re.sub(r"\s+", " ", body.group(1)).strip() if body else "",
            "schema_types": sorted(types), "published_time": bool(published)}


def fetch_signals(domain, data_dir=DATA_DIR, fetch=download, pause=PAUSE_SECONDS):
    folder = data_dir / domain / "analysis"
    urls = [row["url"] for row in csv.DictReader((folder / "pages.csv").open())]
    status = folder / "url_status.csv"
    moved = {r["url"] for r in csv.DictReader(status.open()) if str(r["status_code"]) != "200"} if status.exists() else set()
    hosts = sorted({host_of(u) for u in urls}, key=lambda h: -sum(host_of(u) == h for u in urls))[:5]
    sitemaps = {}
    for host in hosts:
        sitemaps.update(read_sitemaps(host, fetch, pause))
    pages, failed = {}, []
    wanted = [u for u in urls if u not in moved]
    for number, url in enumerate(wanted, 1):
        try:
            pages[url] = page_clues(fetch(url))
        except Exception as error:
            failed.append((url, type(error).__name__))
        print(f"\r  {number}/{len(wanted)} pages read", end="", flush=True)
        time.sleep(pause)
    print()
    signals = {"fetched_at": datetime.datetime.now().isoformat(timespec="seconds"), "sitemaps": sitemaps, "pages": pages,
               "failed": [list(f) for f in failed]}
    (data_dir / domain / "page_signals.json").write_text(json.dumps(signals, indent=1))
    return signals


def build_map(domain, data_dir=DATA_DIR, places=None):
    """Classify every page from the saved clues. Works with no saved clues too (URL and Google's date only)."""
    folder = data_dir / domain / "analysis"
    saved = data_dir / domain / "page_signals.json"
    signals = json.loads(saved.read_text()) if saved.exists() else {"sitemaps": {}, "pages": {}}
    places = places if places is not None else load_places()
    listed_in = {}
    for child, urls in signals["sitemaps"].items():
        for url in urls:
            listed_in.setdefault(url_key(url), child)
    hosts_with_sitemap = {re.sub(r"^www\.", "", host_of(u)) for urls in signals["sitemaps"].values() for u in urls}
    rows = []
    for page in csv.DictReader((folder / "pages.csv").open()):
        url = page["url"]
        has_sitemap = re.sub(r"^www\.", "", host_of(url)) in hosts_with_sitemap
        rows.append(classify(url, page.get("title", ""), page.get("dated_share", ""), listed_in.get(url_key(url)),
                             signals["pages"].get(url), places, has_sitemap))
    with (folder / "page_map.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def summary_lines(domain, rows, signals=None):
    import collections
    types = collections.Counter(r["page_type"] for r in rows)
    sure = collections.Counter(r["confidence"] for r in rows)
    lines = [f"{domain}: {len(rows)} pages typed: " + ", ".join(f"{n} {t}" for t, n in types.most_common()),
             "  How sure: " + ", ".join(f"{n} {c}" for c, n in sure.most_common())]
    if signals is not None:
        lines.append(f"  Sitemaps read: {len(signals['sitemaps'])} listing {sum(len(u) for u in signals['sitemaps'].values())} addresses; "
                     f"{len(signals['pages'])} pages read, {len(signals.get('failed', []))} failed")
    for row in rows:
        if row["page_type"] == "unknown":
            lines.append(f"  unknown: {path_of(row['url'])} ({row['note'] or row['confidence']})")
    return lines


if __name__ == "__main__":
    args = sys.argv[1:] or sys.exit(__doc__)
    reclassify = args[0] == "--reclassify"
    for domain in args[1:] if reclassify else args:
        signals = None if reclassify else fetch_signals(domain)
        rows = build_map(domain)
        print("\n".join(summary_lines(domain, rows, signals)))
        print(f"  Saved in {DATA_DIR / domain / 'analysis' / 'page_map.csv'}")
