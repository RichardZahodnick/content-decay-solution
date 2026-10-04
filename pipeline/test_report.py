import csv, json, pathlib, tempfile, build_report as b, test_recommend      # test_recommend builds a full fixture site

# pure helpers
assert b.nice_ticks(90201) == [0, 25000, 50000, 75000, 100000] and b.nice_ticks(1866) == [0, 500, 1000, 1500, 2000]
assert b.nice_ticks(7) == [0, 2, 4, 6, 8] and b.nice_ticks(0) == [0, 1] and b.month_name("2026-09-22") == "Sep 2026"
svg, g = b.line_chart("c", "Title <x>", ["2025-12", "2026-01", "2026-02"], [10, 40, 20], ("2026-01-15", "2026-02-20"))
assert svg.count("<polyline") == 1 and "Peak 40 in Jan 2026" in svg and "20 in Feb 2026" in svg and "Title &lt;x&gt;" in svg
assert 'class="window"' in svg and ">2026<" in svg and g["yMax"] == 40
assert b.line_chart("c", "t", [], [])[0].count("<polyline") == 0                # no data must not crash
assert 'width="0.0"' in b.bar_pair(100, 0, 100) and 'width="150.0"' in b.bar_pair(100, 0, 100)

# build a report from the recommend fixture, with history and a summary added
root = test_recommend.root
site = root / "x.com"
(site / "history.csv").write_text("month,etv,keywords,top3,top10\n2026-07,900,50,3,20\n2026-08,700,48,2,15\n2026-09,400,45,1,9\n")
(site / "analysis" / "summary.json").write_text(json.dumps({
    "site": "x.com", "pages": 17, "keyword_rows": 9, "site_change_pct": -0.2, "newest_check": "2026-09-10", "window_start": "2026-04-13",
    "status_counts": {"decayed": 7, "stable": 9}, "thresholds": {"MIN_TRAFFIC_BEFORE": 10.0, "DROP_PCT": -0.3, "RELATIVE_GAP": 0.15}}))
(site / "analysis" / "review.json").write_text(json.dumps({"reviewer": "an SEO <specialist>", "minutes": 30, "reviewer_caught": ["Checked the live site"]}))
pages = list(csv.DictReader((site / "analysis" / "pages.csv").open()))
for p in pages:
    p.update(traffic_change=float(p["traffic_now"]) - float(p["traffic_before"]), change_pct=float(p["traffic_now"]) / float(p["traffic_before"]) - 1 if float(p["traffic_before"]) else "",
             top10_before=3, top10_now=1)
with (site / "analysis" / "pages.csv").open("w", newline="") as h:
    w = csv.DictWriter(h, fieldnames=list(pages[0])); w.writeheader(); w.writerows(pages)
out = b.build("x.com", root, today="2026-10-02")
page = out.read_text()
assert out == site / "report.html" and page.startswith("<!doctype html>")
assert "7 of 17 pages lost ground on their own between Apr 2026 and Sep 2026." in page and "down 20% over the same window" in page
for text in ("Queued fixes", "Alerts", "Automatic", "Already handled", "Merge and redirect", "Differentiate: brief for a strategist",
             "Redirect into it:", "Suggested owner", "Checked against a person", "Rules v4", "an SEO &lt;specialist&gt;", "about 30 minutes", "Checked the live site",
             "Show the monthly numbers", "billable hours", "Refresh: needs a content review", "/gone/ redirects to"):
    assert text in page, text
assert "<specialist>" not in page and page.count("<svg class=\"chart\"") == 2 and "http://" not in page.replace("https://x.com", "") .replace("https://", "")
charts = json.loads(page.split("const CHARTS = ")[1].split(";\n")[0])
assert charts[0]["values"] == [900, 700, 400] and charts[1]["values"] == [20, 15, 9] and charts[0]["months"][0] == "Jul 2026"
assert "The page map has not been built for this site" in page and "<th>Type</th>" not in page and "analysis/briefs/merge-1-guide.md" in page
# with a page map: types in the table, the type counts, unknown pages listed, and the location finding shown as a pair
(test_recommend.geo / "g.com" / "history.csv").write_text("month,etv,keywords,top3,top10\n2026-08,700,48,2,15\n2026-09,400,45,1,9\n")
(test_recommend.gf / "summary.json").write_text(json.dumps({"site": "g.com", "pages": 5, "keyword_rows": 8, "site_change_pct": -0.1, "newest_check": "2026-09-10",
    "window_start": "2026-04-13", "status_counts": {"decayed": 1, "stable": 4}, "thresholds": {"MIN_TRAFFIC_BEFORE": 10.0, "DROP_PCT": -0.3, "RELATIVE_GAP": 0.15}}))
gpages = list(csv.DictReader((test_recommend.gf / "pages.csv").open()))
for gp in gpages:
    gp.update(traffic_change=float(gp["traffic_now"]) - float(gp["traffic_before"]), change_pct=float(gp["traffic_now"]) / float(gp["traffic_before"]) - 1, top10_before=3, top10_now=1)
with (test_recommend.gf / "pages.csv").open("w", newline="") as h:
    w = csv.DictWriter(h, fieldnames=list(gpages[0])); w.writeheader(); w.writerows(gpages)
gmap = list(csv.DictReader((test_recommend.gf / "page_map.csv").open()))
for row in gmap:
    row.update(confidence="confirmed" if row["page_type"] != "hub" else "signals disagree", note="sitemap says article; URL says hub" if row["page_type"] == "hub" else "",
               sitemap_says="page (page-sitemap.xml)", page_code_says="page (body class page)")
    if row["page_type"] == "hub":
        row["page_type"] = "unknown"
with (test_recommend.gf / "page_map.csv").open("w", newline="") as h:
    w = csv.DictWriter(h, fieldnames=list(gmap[0])); w.writeheader(); w.writerows(gmap)
geo_page = b.build("g.com", test_recommend.geo).read_text()
for text in ("<th>Type</th>", "<td>Standing page</td>", "<td>Location page</td><td class=\"num\">3</td><td class=\"num\">3</td>", "Unknown (never merged)",
             "Pages left as unknown:", "sitemap says article; URL says hub", "Sharpen targeting: location pages competing with each other",
             "Competes with:", "(2 shared searches)", "analysis/briefs/sharpen-seo.md", "the search names Dallas", "sharpen targeting"):
    assert text in geo_page, text
assert "The live site has not been read for this run" not in geo_page
assert "Keep <a class=\"path\" href=\"https://g.com/boston-seo/\"" not in geo_page          # a location pair is shown as "A and B", not as keep and redirect
# broken addresses: one grouped row per tier with the redirect list inside; they are not listed as "already handled"
import test_recommend as tr
mroot = pathlib.Path(tempfile.mkdtemp()); mf = mroot / "m.com" / "analysis"; mf.mkdir(parents=True)
mrows = [{**p, "traffic_change": float(p["traffic_now"]) - float(p["traffic_before"]), "change_pct": -0.5, "top10_before": 5} for p in tr.mpages.values()]
for name, rows in (("pages.csv", mrows), ("url_status.csv", [{"url": u, **s} for u, s in tr.mstatus.items()])):
    with (mf / name).open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
(mf / "pairs_judged.csv").write_text(""); (mroot / "m.com" / "keywords.csv").write_text("url,keyword,rank,search_volume,is_lost\n")
(mroot / "m.com" / "page_signals.json").write_text(json.dumps({"sitemaps": {"https://m.com/post-sitemap.xml": tr.site_map}, "pages": {}}))
(mroot / "m.com" / "history.csv").write_text("month,etv,keywords,top3,top10\n2026-08,700,48,2,15\n2026-09,400,45,1,9\n")
(mf / "summary.json").write_text(json.dumps({"site": "m.com", "pages": 7, "keyword_rows": 8, "site_change_pct": -0.5, "newest_check": "2026-09-10",
    "window_start": "2026-04-13", "status_counts": {"decayed": 3, "stable": 4}, "thresholds": {"MIN_TRAFFIC_BEFORE": 10.0, "DROP_PCT": -0.3, "RELATIVE_GAP": 0.15}}))
b.recommend.run("m.com", mroot)
rmap = list(csv.DictReader((mf / "redirect_map.csv").open()))
assert len(rmap) == 4 and rmap[0]["old_address"] == "https://m.com/hvac/a-post/" and rmap[0]["new_address"] == "https://m.com/blog/a-post/" and rmap[0]["how_found"] == "same page name in the sitemap"
assert [r["new_address"] for r in rmap].count("") == 2
mpage = b.build("m.com", mroot).read_text()
for text in ("Redirect 2 broken addresses to the page&#x27;s new address", "2 broken addresses with no redirect: a person picks where they go", "<th>Redirect it to</th>",
             'href="https://m.com/blog/a-post/"', "4 recommendations follow: 0 automatic, 2 queued for approval and 2 that need a person&#x27;s decision. 4 old addresses return an error page and have no redirect.",
             "analysis/redirect_map.csv", "/moved/ redirects to", "returns 404; ranked for 66 searches at the last data check (3 on page one), about 750 est. visits a month then", "Google may already show the new address"):
    assert text in mpage, text
assert "/hvac/a-post/ returns 404</li>" not in mpage                       # a broken address is not in the "already handled" list
# a site with no pairs, no recommendations and no evaluation still builds
bare = root / "e.com"
(bare / "history.csv").write_text("month,etv,keywords,top3,top10\n2026-09,5,1,0,0\n")
(bare / "analysis" / "summary.json").write_text(json.dumps({"site": "e.com", "pages": 1, "keyword_rows": 0, "site_change_pct": 0.1, "newest_check": "2026-09-10",
    "window_start": "2026-04-13", "status_counts": {"stable": 1}, "thresholds": {"MIN_TRAFFIC_BEFORE": 10.0, "DROP_PCT": -0.3, "RELATIVE_GAP": 0.15}}))
b.recommend.run("e.com", root)
bare_page = b.build("e.com", root).read_text()
assert "No pages decayed on their own" in bare_page and "Nothing in this tier on this run." in bare_page and "Checked against a person" not in bare_page
print("ALL TESTS PASSED")
