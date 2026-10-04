#!/usr/bin/env python3
"""Build the example site: made-up ranking data for a made-up company, run through the real pipeline.

Usage:  python3 example/make_example.py            writes example/data/northside-hvac.example/ and prints where the report is
        (that folder is built on your machine each time; it is not kept in the repo)
Needs:  nothing. No DataForSEO login, no decision model, no network. It takes about a second.

WHY THIS EXISTS. The pipeline normally needs a paid ranking-data account and a decision model running locally, and
its reports on real sites are not published. This gives anyone who clones the repo something to run and read.

WHAT IS REAL AND WHAT IS NOT
  Real:      every step that needs no outside service runs unchanged: finding decayed pages and competing pairs,
             the page map, the pair rules, the keyword owners, the work orders, the report.
  Simulated: the company, its pages and every number in keywords.csv and history.csv (written below, by hand);
             the live-site checks (which addresses load, what the sitemap lists, each page's code);
             the decision model's scores (SAME_TOPIC below, and a word-overlap stand-in for keyword fit).
The site's data folder holds SIMULATED.txt, so the report and the run summary both say so at the top.

The data is built to show one of each kind of finding: a duplicate to redirect, two articles to merge, two to
differentiate, location pages that compete, a decayed page with no rival, broken addresses with and without a
new address in the sitemap, and a page the live site shows is already handled.
"""
import csv, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import run_site as rs                                   # noqa: E402  (needs the path line above)

SITE = "northside-hvac.example"                         # .example is reserved for documentation: it can never be a real site
HOME = f"https://{SITE}"
NEWEST, PREVIOUS = "2026-09-18", "2026-07-10"           # each keyword's latest check and the one before it
NOTE = ("Northside Heating & Air is a made-up company. Every page, keyword and number in this report was written by hand "
        "for the example, and the decision model's scores were scripted. The analysis and the rules are the real ones.")

# click-through rate by position, in the shape of the ranking provider's model
CTR = {1: .30, 2: .16, 3: .10, 4: .07, 5: .05, 6: .04, 7: .03, 8: .025, 9: .02, 10: .015}
ctr = lambda rank: CTR.get(rank, .008 if rank <= 20 else .003)

ARTICLE = {"body_class": "single single-post", "schema_types": ["Article", "WebPage"], "published_time": True}
PAGE = {"body_class": "page page-template-default", "schema_types": ["WebPage"], "published_time": False}

# path: (title, links to it, live status, sitemap, page code, [(search, searches a month, rank now, rank before)])
#   rank now None    = the page lost this search (the rank before is the last one it held)
#   rank before None = the search is new for this page
PAGES = {
    "/": ("Northside Heating & Air | HVAC Service in Columbus, OH", 41, 200, "page", {**PAGE, "body_class": "home page"}, [
        ("northside heating and air", 880, 1, 1), ("hvac columbus ohio", 1900, 6, 6), ("hvac company near me", 5400, 14, 13)]),
    "/blog/": ("HVAC Tips and Advice | Northside Heating & Air", 3, 200, "post", {**PAGE, "body_class": "blog"}, [
        ("hvac tips", 1300, 9, 10)]),
    "/services/ac-repair/": ("Air Conditioner Repair Services", 12, 200, "page", PAGE, [
        ("ac repair", 12100, 5, 5), ("air conditioner repair near me", 8100, 8, 8)]),
    "/services/furnace-repair/": ("Furnace Repair Services", 15, 200, "page", PAGE, [
        ("furnace repair", 6600, 9, 5), ("furnace repair near me", 9900, 12, 8), ("emergency furnace repair", 1300, 7, 4),
        ("furnace repair columbus", 720, None, 6), ("furnace service columbus ohio", 320, None, 8)]),
    "/furnace-repair-columbus/": ("Furnace Repair in Columbus, OH", 4, 200, "page", PAGE, [
        ("furnace repair columbus", 720, 4, 9), ("furnace service columbus ohio", 320, 5, 11), ("furnace repair columbus oh cost", 480, 3, 3),
        ("24 hour furnace repair ohio", 210, 8, 10), ("furnace repair dayton", 390, None, 12)]),
    "/furnace-repair-dayton/": ("Furnace Repair in Dayton, OH", 2, 200, "page", PAGE, [
        ("furnace repair dayton", 390, 5, 7), ("furnace repair dayton oh cost", 260, 4, 4),
        ("furnace repair columbus", 720, None, 18), ("24 hour furnace repair ohio", 210, None, 9)]),
    "/blog/why-is-my-furnace-blowing-cold-air/": ("Why Is My Furnace Blowing Cold Air? 7 Common Causes", 14, 200, "post", ARTICLE, [
        ("furnace blowing cold air", 8100, 11, 5), ("why is my furnace blowing cold air", 5400, 9, 4),
        ("furnace not blowing hot air", 2900, 14, 7), ("heater blowing cold air in house", 1600, 8, 6)]),
    "/blog/furnace-blowing-cold-air-causes/": ("Furnace Blowing Cold Air: Causes and Fixes", 2, 200, "post", ARTICLE, [
        ("furnace blowing cold air", 8100, 16, 19), ("why is my furnace blowing cold air", 5400, 18, None),
        ("furnace blowing cold air fix", 880, 12, 12)]),
    "/blog/heat-pump-vs-furnace/": ("Heat Pump vs. Furnace: Which Is Right for Your Home?", 9, 200, "post", ARTICLE, [
        ("heat pump vs furnace", 6600, 5, 4), ("heat pump or gas furnace cost", 1300, 6, 6),
        ("do heat pumps work below freezing", 1900, 8, 10), ("heat pump in cold weather", 3600, None, 9)]),
    "/blog/how-does-a-heat-pump-work/": ("How Does a Heat Pump Work in Winter?", 6, 200, "post", ARTICLE, [
        ("how does a heat pump work", 12100, 9, 8), ("heat pump winter efficiency", 1000, 6, 9),
        ("heat pump in cold weather", 3600, 7, 11), ("do heat pumps work below freezing", 1900, None, 10)]),
    "/blog/best-thermostat-settings-winter-2025/": ("Best Thermostat Settings for Winter 2025", 5, 200, "post", ARTICLE, [
        ("best thermostat setting for winter", 4400, 15, 8), ("what temperature to set thermostat in winter", 6600, 19, 10)]),
    "/blog/best-thermostat-settings-winter/": ("Best Thermostat Settings for Winter 2026", 1, 200, "post", ARTICLE, [
        ("best thermostat setting for winter", 4400, 6, None), ("what temperature to set thermostat in winter", 6600, 7, None)]),
    "/blog/how-often-to-change-furnace-filter/": ("How Often Should You Change Your Furnace Filter?", 7, 200, "post", ARTICLE, [
        ("how often to change furnace filter", 14800, 12, 6), ("furnace filter replacement schedule", 1000, 10, 5),
        ("when to replace furnace filter", 2400, None, 9)]),
    "/blog/what-size-furnace-do-i-need/": ("What Size Furnace Do I Need? A Sizing Guide", 11, 200, "post", ARTICLE, [
        ("what size furnace do i need", 8100, 3, 4), ("furnace size calculator", 6600, 7, 7)]),
    "/blog/furnace-making-loud-noise/": ("Furnace Making a Loud Noise? What Each Sound Means", 8, 200, "post", ARTICLE, [
        ("furnace making loud noise", 6600, 2, 2), ("furnace banging noise", 2400, 3, 4)]),
    # an old address from before a redesign: the article now lives under /blog/, and nothing redirects to it
    "/hvac/ac-not-cooling/": ("AC Not Cooling? 8 Things to Check", 9, 404, None, None, [
        ("ac not cooling", 9900, 7, 7), ("air conditioner running but not cooling", 6600, 6, 6)]),
    "/hvac/spring-tune-up-special/": ("Spring AC Tune-Up Special", 3, 404, None, None, [
        ("ac tune up special", 590, 9, 9)]),
    # the ranking data shows this page losing everything; the live check shows it was already redirected
    "/furnace-tune-up/": ("Furnace Tune-Up", 6, 301, None, None, [
        ("furnace tune up", 5400, None, 8), ("furnace tune up cost", 2400, None, 7)]),
}
REDIRECTS = {"/furnace-tune-up/": "/services/furnace-maintenance/"}
SITEMAP_ONLY = {"post": ["/blog/ac-not-cooling/"], "page": ["/services/furnace-maintenance/"]}      # live pages with no ranking rows

SAME_TOPIC = {   # the decision model's scripted answer to "are these two pages about the same subject?"; any other pair gets 0.20
    frozenset({"/blog/why-is-my-furnace-blowing-cold-air/", "/blog/furnace-blowing-cold-air-causes/"}): 0.88,
    frozenset({"/blog/heat-pump-vs-furnace/", "/blog/how-does-a-heat-pump-work/"}): 0.66,
    frozenset({"/services/furnace-repair/", "/furnace-repair-columbus/"}): 0.74,
    frozenset({"/furnace-repair-columbus/", "/furnace-repair-dayton/"}): 0.71,
}


def keyword_rows():
    rows = []
    for path, (title, links, _, _, code, searches) in PAGES.items():
        for search, volume, now, before in searches:
            lost = now is None
            held = before if lost else now
            rows.append({
                "keyword": search, "core_keyword": "", "search_volume": volume, "intent": "informational", "difficulty": 0,
                "url": HOME + path, "title": title, "rank": held, "rank_absolute": held,
                "previous_rank_absolute": "" if lost or before is None else before,
                "is_new": before is None, "is_up": bool(before and not lost and now < before), "is_down": bool(before and not lost and now > before),
                "is_lost": lost, "etv": round(volume * ctr(held), 2), "referring_domains": links, "page_rank": min(60, links * 4),
                "ai_overview_on_serp": False, "serp_checked": NEWEST, "previous_check": "" if before is None else PREVIOUS,
                "dated": code is ARTICLE or (code is None and "/hvac/" in path)})
    return rows


def history_rows():
    """Six years of whole-site traffic: a slow climb to a peak in early 2025, then a slide."""
    rows = []
    for index in range(72):
        year, month = 2020 + (index + 9) // 12, (index + 9) % 12 + 1
        climb = 900 + 2400 * min(1, index / 52)
        slide = 1 - 0.022 * max(0, index - 52)
        season = 1.18 if month in (11, 12, 1, 2) else 0.92 if month in (4, 5, 9, 10) else 1.0     # heating and cooling seasons
        etv = round(climb * slide * season)
        rows.append({"month": f"{year}-{month:02d}", "etv": etv, "keywords": 180 + index * 3,
                     "top3": round(etv / 260), "top10": round(etv / 95)})
    return rows


def scripted_model(body):
    """Stands in for the decision model. Same request and reply shape as the real one."""
    state = body["state"]
    if "search_query" in state:                                  # keyword fit: how many of the search's words the title has
        words = lambda text: set(re.findall(r"[a-z]+", text.lower())) - {"a", "the", "in", "for", "to", "is", "my", "do", "does", "how", "oh"}
        query = words(state["search_query"])
        return {"answers": {"q": {"noul": round(0.15 + 0.7 * len(query & words(state["page_title"])) / max(1, len(query)), 3)}}}
    title_of = lambda text: text.split(" | Top searches:")[0].replace("Title: ", "")
    by_title = {info[0]: path for path, info in PAGES.items()}
    pair = frozenset(by_title.get(title_of(state[key])) for key in ("page_a", "page_b"))
    score = SAME_TOPIC.get(pair, 0.20)
    return {"answers": {"q": {"noul": round(score + (0.02 if "Top searches" in state["page_a"] else -0.02), 3)}}}


def write_inputs(data_dir):
    site = data_dir / SITE
    (site / "analysis").mkdir(parents=True, exist_ok=True)
    (site / "SIMULATED.txt").write_text(NOTE + "\n")
    rows = keyword_rows()
    for name, table in (("keywords.csv", rows), ("history.csv", history_rows())):
        with (site / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
    with (site / "analysis" / "url_status.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["url", "status_code", "redirects_to", "checked_at"])
        for path, info in PAGES.items():
            writer.writerow([HOME + path, info[2], HOME + REDIRECTS[path] if path in REDIRECTS else "", f"{NEWEST}T09:00:00"])
    sitemaps = {f"{HOME}/{kind}-sitemap.xml": [HOME + path for path, info in PAGES.items() if info[3] == kind] + [HOME + p for p in extra]
                for kind, extra in SITEMAP_ONLY.items()}
    signals = {"fetched_at": f"{NEWEST}T09:00:00", "sitemaps": sitemaps, "failed": [],
               "pages": {HOME + path: info[4] for path, info in PAGES.items() if info[4]}}
    (site / "page_signals.json").write_text(json.dumps(signals, indent=1))
    return site


def build(data_dir=HERE / "data", say=print):
    data_dir = pathlib.Path(data_dir)
    write_inputs(data_dir)
    skip = lambda note: (lambda domain, folder: ("skipped", note))
    steps = [   # the same nine steps as run_site.py; the four that need an outside service are replaced by the made-up inputs above
        ("pull rankings", "simulated", skip("ranking data written by make_example.py"), False),
        ("find decayed pages and competing pairs", "nothing", rs.analyze_step, True),
        ("judge the pairs", "simulated", rs.judge_step, False),
        ("check live addresses", "simulated", skip("address statuses written by make_example.py"), False),
        ("map page types", "simulated", lambda domain, folder: rs.map_step(domain, folder, offline=True), True),
        ("fetch page text", "simulated", skip("no page text in the example, so shared text is not measured"), False),
        ("recommend", "nothing", rs.recommend_step, True),
        ("score keyword fit", "simulated", rs.fit_step, False),
        ("build the report", "nothing", rs.report_step, True),
    ]
    return rs.run(SITE, data_dir, steps=steps, kev_send=scripted_model, say=say)


if __name__ == "__main__":
    status = build()
    site = HERE / "data" / SITE
    print(f"\n{'Finished' if status['ok'] else 'STOPPED'}. Everything here is simulated data for a made-up company.")
    print(f"Report:   {site / 'report.html'}")
    print(f"Summary:  {site / 'run_summary.md'}")
    print(f"Run the offline steps again on the same data with:\n  OPENCLAW_DATA={HERE / 'data'} python3 pipeline/run_site.py --offline {SITE}")
    sys.exit(0 if status["ok"] else 1)
