import csv, json, pathlib, tempfile, map_pages as m

U = lambda p: f"https://www.x.com{p}"
places = m.load_places()
assert places[("new", "york")] == "New York" and places[("los", "angeles")] == "Los Angeles" and ("mobile",) not in places and ("enterprise",) not in places
# places: longest name first, whole words only
assert m.find_place("/kansas-city-seo/", places) == "Kansas City" and m.find_place("Kansas SEO", places) == "Kansas"
assert m.find_place("/new-york-personal-injury-law-firm-seo/", places) == "New York" and m.find_place("/charlotte-nc-law-firm-seo-agency/", places) == "Charlotte"
assert m.find_place("Mobile SEO for enterprise sites", places) == "" and m.find_place("bostonian guide", places) == "" and m.find_place("", places) == ""
assert m.url_key("https://WWW.x.com/A-Page/?utm=1") == "x.com/a-page" and m.url_key("http://x.com/a-page") == "x.com/a-page"

# what a sitemap's file name says
S = lambda name: m.sitemap_says(name)[0]
assert S("https://x.com/post-sitemap.xml") == "article" and S("https://x.com/page-sitemap2.xml") == "page" and S("https://x.com/category-sitemap.xml") == "hub"
assert S("https://x.com/podcast-sitemap.xml") == "media" and S("https://x.com/tribe_events-sitemap.xml") == "other" and S("https://x.com/post_tag-sitemap.xml") == "hub"
assert S("https://x.com/wp-sitemap-posts-post-1.xml") == "article" and S("https://x.com/wp-sitemap-posts-page-1.xml") == "page"
assert S("https://x.com/wp-sitemap-taxonomies-category-1.xml") == "hub" and S("https://x.com/wp-sitemap-users-1.xml") == "hub"
assert S("https://x.com/sitemap-pt-post-2024-01.xml") == "article" and S("https://x.com/sitemap.xml") is None and S("") is None
# what the page's own code says
C = lambda **k: m.page_code_says(k)[0]
assert C(body_class="post-template-default single single-post postid-9") == "article" and C(body_class="page-template-default page page-id-4") == "page"
assert C(body_class="home page-template page") == "homepage" and C(body_class="blog wp-custom-logo") == "hub" and C(body_class="archive category") == "hub"
assert C(body_class="single single-podcast") == "media" and C(body_class="single single-tribe_events") == "other"
assert C(body_class="", schema_types=["WebPage", "BlogPosting"]) == "article" and C(body_class="", schema_types=["WebPage"], published_time=True) == "article"
assert C(body_class="", schema_types=["WebPage"]) is None and m.page_code_says(None) == (None, "")
# what the URL says
L = lambda p: m.url_says(U(p))[0]
assert L("/") == "homepage" and L("/blog/") == "hub" and L("/blog/a-post/") == "article" and L("/2024/05/a-post/") == "article"
assert L("/services/") == "hub" and L("/services/seo/") == "service" and L("/web-design-services/") == "service" and L("/category/seo/") == "hub"
assert L("/podcast/episode-9/") == "media" and L("/locations/boston/") == "location" and L("/event/expo/") == "other" and L("/law-firm-seo/") is None

# parsing the page and the sitemap
html_post = ('<html><head><meta property="article:published_time" content="2024-01-02"/>'
             '<script type="application/ld+json">{"@graph":[{"@type":"WebPage"},{"@type":["Article","BlogPosting"]}]}</script>'
             '<script type="application/ld+json">{not json</script></head><body data-x="1" class="single  single-post\n postid-7">hi</body></html>')
clues = m.page_clues(html_post)
assert clues == {"body_class": "single single-post postid-7", "schema_types": ["Article", "BlogPosting", "WebPage"], "published_time": True}, clues
assert m.page_clues("<html><body>plain</body></html>") == {"body_class": "", "schema_types": [], "published_time": False}
xml = "<urlset><url><loc> https://x.com/a/ </loc><image:image><image:loc>https://x.com/i.png</image:loc></image:image></url><url><loc><![CDATA[https://x.com/b/?x=1&amp;y=2]]></loc></url></urlset>"
assert m.locs(xml) == ["https://x.com/a/", "https://x.com/b/?x=1&y=2"]

# combining the clues
K = lambda path, title="T", dated="", sitemap=None, code=None, found=True: m.classify(U(path), title, dated, sitemap, code, places, found)
post, page = {"body_class": "single single-post"}, {"body_class": "page page-id-3"}
r = K("/a-post/", dated=0.0, sitemap="https://x.com/post-sitemap.xml", code=post)
assert (r["page_type"], r["confidence"]) == ("article", "confirmed") and "points the other way" in r["note"]      # Google shows no date, the site says article
r = K("/a-post/", dated=1.0, sitemap="https://x.com/page-sitemap.xml", code=post)
assert (r["page_type"], r["confidence"]) == ("unknown", "signals disagree") and r["note"] == "sitemap says page; page code says article"
assert (K("/a-post/", dated=1.0)["page_type"], K("/a-post/", dated=1.0)["confidence"]) == ("article", "publish date only")
assert K("/a-page/", dated=0.2)["page_type"] == "page" and (K("/a-page/")["page_type"], K("/a-page/")["confidence"]) == ("unknown", "no signal")
assert K("/a-page/", found=False)["sitemap_says"] == "no sitemap found" and K("/a-page/")["sitemap_says"] == "not listed in the sitemap"
r = K("/blog/a-post/", dated=1.0)
assert (r["page_type"], r["confidence"]) == ("article", "confirmed")                # URL folder plus Google's date
assert K("/blog/a-post/")["confidence"] == "one signal"
r = K("/blog/", sitemap="https://x.com/post-sitemap.xml", code={"body_class": "blog"})
assert (r["page_type"], r["confidence"]) == ("hub", "confirmed") and "outranks the sitemap" in r["note"]           # Yoast lists the blog index with the posts
assert K("/", sitemap="https://x.com/page-sitemap.xml", code={"body_class": "home page"})["page_type"] == "homepage"
assert K("/podcast/ep-1/", dated=1.0, sitemap="https://x.com/podcast-sitemap.xml", code={"body_class": "single single-podcast"})["page_type"] == "media"
assert K("/case_studies/acme/", sitemap="https://x.com/case_studies-sitemap.xml")["page_type"] == "other"
r = K("/podcast/ep-1/", dated=0.0, sitemap="https://x.com/page-sitemap.xml", code=page)        # a podcast episode built as an ordinary page
assert (r["page_type"], r["confidence"]) == ("media", "confirmed") and r["note"].startswith("no clue says article; they differ on the kind of page: sitemap says page")
r = K("/event/expo/", sitemap="https://x.com/page-sitemap.xml", code=page)
assert r["page_type"] == "other" and K("/podcast/ep-1/", sitemap="https://x.com/post-sitemap.xml", code=post)["page_type"] == "unknown"
assert K("/services/seo/", sitemap="https://x.com/page-sitemap.xml", code=page)["page_type"] == "service"
# location: a standing page with the same place in its URL and title
r = K("/dallas-attorney-seo-agency/", "Dallas Attorney SEO Agency", 0.0, "https://x.com/page-sitemap.xml", page)
assert (r["page_type"], r["place"], r["confidence"]) == ("location", "Dallas", "confirmed")
assert K("/dallas-seo/", "Law Firm SEO Agency", 0.0, "https://x.com/page-sitemap.xml", page)["page_type"] == "page"       # place only in the URL
r = K("/best-lawyers-in-chicago/", "The Best Lawyers in Chicago", 1.0, "https://x.com/post-sitemap.xml", post)
assert (r["page_type"], r["place"]) == ("article", "Chicago")                       # an article about a place stays an article
assert K("/team/madison-jones/", "Madison Jones", 0.0, "https://x.com/page-sitemap.xml", page)["page_type"] == "page"     # a person, not a city
assert K("/services/seo-chicago/", "Chicago SEO Services", 0.0, "https://x.com/page-sitemap.xml", page)["page_type"] == "location"

# end to end with a fake site: robots.txt points at an index with two child sitemaps
site = {
    "https://www.x.com/robots.txt": "User-agent: *\nSitemap: https://www.x.com/sitemap_index.xml\n",
    "https://www.x.com/sitemap_index.xml": "<sitemapindex><sitemap><loc>https://www.x.com/post-sitemap.xml</loc></sitemap><sitemap><loc>https://www.x.com/page-sitemap.xml</loc></sitemap></sitemapindex>",
    "https://www.x.com/post-sitemap.xml": "<urlset><url><loc>https://www.x.com/blog/</loc></url><url><loc>https://www.x.com/a-post/</loc></url></urlset>",
    "https://www.x.com/page-sitemap.xml": "<urlset><url><loc>https://www.x.com/</loc></url><url><loc>http://x.com/boston-seo</loc></url></urlset>",
    U("/"): '<body class="home page">', U("/a-post/"): html_post, U("/boston-seo/"): '<body class="page page-id-2">', U("/blog/"): '<body class="blog">',
}
def fake(url):
    if url not in site:
        raise OSError("404")
    return site[url]
root = pathlib.Path(tempfile.mkdtemp()); folder = root / "x.com" / "analysis"; folder.mkdir(parents=True)
def write(path, rows):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
write(folder / "pages.csv", [{"url": U("/"), "title": "X", "dated_share": 0.0}, {"url": U("/a-post/"), "title": "A post", "dated_share": 1.0},
                             {"url": U("/boston-seo/"), "title": "Boston SEO Agency", "dated_share": 0.0}, {"url": U("/blog/"), "title": "Blog", "dated_share": 0.1},
                             {"url": U("/gone/"), "title": "Gone", "dated_share": 1.0}, {"url": U("/broken/"), "title": "Broken", "dated_share": ""},
                             {"url": "https://lp.x.com/", "title": "Landing", "dated_share": 0.0}])
write(folder / "url_status.csv", [{"url": U("/gone/"), "status_code": "301", "redirects_to": U("/a-post/")}])
signals = m.fetch_signals("x.com", root, fake, pause=0)
assert set(signals["sitemaps"]) == {"https://www.x.com/post-sitemap.xml", "https://www.x.com/page-sitemap.xml"}
assert set(signals["pages"]) == {U("/"), U("/a-post/"), U("/boston-seo/"), U("/blog/")}            # /gone/ redirects: not requested
assert sorted(f[0] for f in signals["failed"]) == ["https://lp.x.com/", U("/broken/")]
rows = {r["url"]: r for r in m.build_map("x.com", root)}
assert [rows[U(p)]["page_type"] for p in ("/", "/a-post/", "/boston-seo/", "/blog/")] == ["homepage", "article", "location", "hub"]
assert rows[U("/boston-seo/")]["place"] == "Boston" and rows[U("/boston-seo/")]["sitemap_says"] == "page (page-sitemap.xml)"
assert rows[U("/gone/")]["page_type"] == "article" and rows[U("/gone/")]["confidence"] == "publish date only"
assert rows[U("/broken/")]["page_type"] == "unknown" and rows[U("/broken/")]["sitemap_says"] == "not listed in the sitemap"
assert rows["https://lp.x.com/"]["page_type"] == "homepage" and rows["https://lp.x.com/"]["sitemap_says"] == "no sitemap found"
saved = list(csv.DictReader((folder / "page_map.csv").open()))
assert len(saved) == 7 and list(saved[0]) == m.COLUMNS and json.loads((root / "x.com" / "page_signals.json").read_text())["fetched_at"]
lines = m.summary_lines("x.com", list(rows.values()), signals)
assert lines[0].startswith("x.com: 7 pages typed:") and any("unknown: /broken/" in l for l in lines) and "2 failed" in lines[2]
# a site with no sitemap and no saved clues still gets a map from the URL and Google's date
bare = root / "y.com" / "analysis"; bare.mkdir(parents=True)
write(bare / "pages.csv", [{"url": "https://y.com/blog/p/", "title": "P", "dated_share": 1.0}, {"url": "https://y.com/q/", "title": "Q", "dated_share": 0.0}])
assert [r["page_type"] for r in m.build_map("y.com", root)] == ["article", "page"]
assert m.read_sitemaps("nothing.example", fake, pause=0) == {}
print("ALL TESTS PASSED")
