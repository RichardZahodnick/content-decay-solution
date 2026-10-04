import csv, json, pathlib, tempfile, recommend as r

U = lambda p: f"https://x.com{p}"
assert r.path_of(U("/a/b/")) == "/a/b/" and r.path_of(U("/")) == "/" and r.path_of("https://x.com") == "/"
assert r.protected_kind(U("/")) == "homepage" and r.protected_kind(U("/blog/")) == "index page"
assert r.protected_kind(U("/law-firm-seo-services/")) == "service page" and r.protected_kind(U("/services/seo/x/")) == "service page"
assert r.protected_kind(U("/blog/a-post/")) == "" and r.protected_kind(U("/seo-for-lawyers/")) == ""

def pair(a, b, kev, overlap, swaps, by="kev"):
    return {"page_a": U(a), "page_b": U(b), "p_same_topic": kev, "overlap_of_smaller_page": overlap, "url_swaps": swaps,
            "decided_by": by, "shared_volume": 100, "top_shared_searches": "x (100)", "verdict": "merge candidate" if kev >= 0.75 else "needs review"}
C = lambda *a, status={}, **k: r.call_for_pair(pair(*a, **k), status)[0]
assert C("/a/", "/b/", 0.70, 0.50, 0) == "merge" and C("/a/", "/b/", 0.69, 0.9, 0) == "separate" and C("/a/", "/b/", 0.9, 0.49, 0) == "separate"
assert C("/a/", "/b/", 0.9, 0.49, 2) == "differentiate" and C("/a/", "/b/", 0.60, 0.1, 2) == "differentiate" and C("/a/", "/b/", 0.59, 0.1, 9) == "separate"
assert C("/", "/b/", 0.99, 1.0, 9) == "keep both" and C("/a/", "/x-services/", 0.99, 1.0, 9) == "keep both"
assert C("/a/", "/a//", 1.0, 0.1, 0, by="code: same page, two addresses") == "redirect duplicate"
assert C("/", "/a/", 1.0, 1.0, 0, by="code: same title apart from the year") == "redirect duplicate"       # code beats protection
st = {U("/b/"): {"status_code": "301", "redirects_to": U("/a/")}, U("/c/"): {"status_code": "404", "redirects_to": ""}, U("/a/"): {"status_code": "200", "redirects_to": ""},
      U("/p//"): {"status_code": "301", "redirects_to": U("/p/")}, U("/pay/"): {"status_code": "301", "redirects_to": "https://other.net/login?token=abc"}}
assert r.call_for_pair(pair("/a/", "/b/", 0.9, 0.9, 0), st) == ("already redirected", "/b/ already redirects to /a/")
assert r.call_for_pair(pair("/b/", "/a/", 0.9, 0.9, 0), st) == ("already redirected", "/b/ already redirects to /a/")
assert r.call_for_pair(pair("/a/", "/c/", 0.9, 0.9, 0), st)[0] == "page gone"
# an old address that redirects somewhere else is not "already merged": the pair is judged as usual
assert r.call_for_pair(pair("/lsa/", "/p//", 0.99, 0.9, 9), st) == ("old address", "/p// is an old address that now redirects to /p/")
assert r.call_for_pair(pair("/p/", "/p//", 1.0, 0.8, 4, by="code: same page, two addresses"), st)[0] == "already redirected"
assert "another site" in r.call_for_pair(pair("/a/", "/pay/", 0.2, 0.0, 0), st)[1] and "token" not in r.call_for_pair(pair("/a/", "/pay/", 0.2, 0.0, 0), st)[1]
# only two articles can merge: a page Google shows without a publish date is kept, whatever the scores say
dated = {U("/post-a/"): {"dated_share": 1.0}, U("/post-b/"): {"dated_share": 0.5}, U("/boston/"): {"dated_share": 0.0}, U("/unknown/"): {"dated_share": ""}}
mk = lambda a, b: r.call_for_pair(pair(a, b, 0.9, 0.9, 5), {}, dated)
assert mk("/post-a/", "/post-b/")[0] == "merge" and mk("/post-a/", "/unknown/")[0] == "merge"       # no date data: falls back to the URL patterns
call, why = mk("/post-a/", "/boston/")
assert call == "keep both" and why.startswith("/boston/ is a page with no publish date")
assert r.protected_kind(U("/boston/"), dated) and not r.protected_kind(U("/boston/")) and r.protected_kind(U("/"), dated) == "homepage"
# shared text
content = {U("/a/"): {"paragraphs": ["one two three four five six seven", "alpha beta gamma delta epsilon"], "headings": [["h2", "What Is a Partner?"], ["h2", "Only A"]], "word_count": 12},
           U("/b/"): {"paragraphs": ["One two three, four five six seven!", "totally different words in this other paragraph here"], "headings": [["h2", "what is a partner?"]], "word_count": 15}}
o = r.content_overlap(U("/a/"), U("/b/"), content)
assert o == {"share_of_a": 0.75, "share_of_b": 0.429, "shared_headings": ["What Is a Partner?"]}, o      # A has 4 runs, B has 7; 3 shared
assert r.content_overlap(U("/a/"), U("/zzz/"), content) is None

P = lambda url, tb, tn, kw, rd, pr, status="stable", lost=0: {"url": U(url), "title": "T", "status": status, "traffic_before": tb, "traffic_now": tn,
    "keywords_now": kw, "keywords_lost": lost, "referring_domains": rd, "page_rank": pr}
pages = {p["url"]: p for p in [
    P("/guide/", 800, 20, 40, 50, 200, "decayed", 10), P("/tips-2021/", 0, 0, 0, 0, 0), P("/strategies/", 10, 30, 20, 30, 180),
    P("/tool/", 400, 100, 100, 3, 100, "decayed", 20), P("/tool-2025/", 0, 0, 0, 5, 100),
    P("/x/", 100, 100, 80, 2, 0), P("/y/", 110, 95, 90, 2, 0),
    P("/hours/", 90, 90, 150, 11, 97), P("/work/", 160, 150, 90, 10, 80),
    P("/alone/", 200, 40, 30, 4, 50, "decayed", 7), P("/dead/", 20, 0, 0, 0, 0, "decayed", 5), P("/dead-linked/", 30, 0, 0, 6, 40, "decayed", 4),
    P("/weak/", 13, 1, 10, 0, 0, "decayed", 5), P("/design-services/", 16, 0, 0, 8, 30, "decayed", 14),
    P("/gone/", 50, 5, 3, 0, 0, "decayed", 2), P("/fine/", 50, 50, 10, 1, 1), P("/", 500, 900, 60, 600, 500)]}
# strength: /guide/ beats its group; dated URL is halved
s = r.strength([U("/tool/"), U("/tool-2025/")], pages)
assert s[U("/tool/")] == 0.86 and s[U("/tool-2025/")] == 0.25, s          # tool: .35*.6+.30+.20+.15 ; 2025: (.35+.15)/2
root = pathlib.Path(tempfile.mkdtemp()); folder = root / "x.com" / "analysis"; folder.mkdir(parents=True)
def write(path, rows):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
write(folder / "pages.csv", list(pages.values()))
write(folder / "pairs_judged.csv", [
    pair("/guide/", "/tips-2021/", 0.83, 1.0, 1), pair("/guide/", "/strategies/", 0.84, 0.65, 8),      # merge group of 3
    pair("/tool/", "/tool-2025/", 1.0, 0.67, 2, by="code: same title apart from the year"),            # duplicate
    pair("/x/", "/y/", 0.9, 0.6, 1),                                                                    # merge, close call
    pair("/hours/", "/work/", 0.82, 0.05, 3),                                                           # differentiate
    pair("/", "/guide/", 0.9, 0.7, 5), pair("/fine/", "/alone/", 0.3, 0.1, 0)])                         # keep both ; separate
kw = lambda url, k, rank, vol, lost=False: {"url": U(url), "keyword": k, "rank": rank, "search_volume": vol, "is_lost": str(lost)}
write(root / "x.com" / "keywords.csv", [
    kw("/hours/", "billable hours", 4, 900), kw("/work/", "billable hours", 9, 900),                    # both live -> /hours/ (ranks higher)
    kw("/hours/", "lawyer hours", 12, 500, lost=True), kw("/work/", "lawyers hours", 30, 500),          # only /work/ live (keys match after plural)
    kw("/hours/", "hours tie", 7, 50), kw("/work/", "hours tie", 7, 50),                                # tie -> stronger page
    kw("/hours/", "only hours", 3, 10), kw("/alone/", "big lost", 5, 1000, lost=True), kw("/alone/", "small lost", 5, 10, lost=True)])
write(folder / "url_status.csv", [{"url": U("/gone/"), "status_code": "301", "redirects_to": U("/fine/")}])
write(folder / "labels.csv", [
    {"pair": 1, "page_a": U("/guide/"), "page_b": U("/tips-2021/"), "human_call": "merge", "human_also_ok": ""},
    {"pair": 2, "page_a": U("/guide/"), "page_b": U("/strategies/"), "human_call": "merge", "human_also_ok": ""},
    {"pair": 3, "page_a": U("/tool/"), "page_b": U("/tool-2025/"), "human_call": "already merged", "human_also_ok": ""},
    {"pair": 4, "page_a": U("/x/"), "page_b": U("/y/"), "human_call": "differentiate", "human_also_ok": ""},
    {"pair": 5, "page_a": U("/hours/"), "page_b": U("/work/"), "human_call": "separate", "human_also_ok": "differentiate"},
    {"pair": 6, "page_a": U("/"), "page_b": U("/guide/"), "human_call": "separate", "human_also_ok": ""},
    {"pair": 7, "page_a": U("/fine/"), "page_b": U("/alone/"), "human_call": "merge", "human_also_ok": ""}])

calls, groups, assignments, recs, ev, checked = r.run("x.com", root)
assert checked and [c["call"] for c in calls] == ["merge", "merge", "redirect duplicate", "merge", "differentiate", "keep both", "separate"]
# groups, biggest traffic first: guide group (810), tool group (400), x/y (210)
assert [g["keep"] for g in groups] == [U("/guide/"), U("/tool/"), U("/y/")], [g["keep"] for g in groups]
g = groups[0]
assert set(g["redirect_to_it"]) == {U("/tips-2021/"), U("/strategies/")} and g["winner_is_clear"] and not g["all_duplicates"]
assert g["lowest_confidence"] == 0.83 and g["traffic_before"] == 810.0 and g["decayed_pages"] == [U("/guide/")] and g["group"] == 1
assert groups[1]["all_duplicates"] and groups[1]["redirect_to_it"] == [U("/tool-2025/")]
assert not groups[2]["winner_is_clear"] and groups[2]["winner_margin"] < 0.15
# keyword assignments for the differentiate pair only; "only hours" is not shared
a = {x["search"]: x for x in assignments}
assert set(a) == {"billable hours", "lawyer hours", "hours tie"}, set(a)
assert a["billable hours"]["assign_to"] == U("/hours/") and a["billable hours"]["why"] == "ranks higher"
assert a["lawyer hours"]["assign_to"] == U("/work/") and a["lawyer hours"]["page_a_rank"] == "12 (lost)" and a["lawyer hours"]["why"] == "the only page still ranking"
assert a["hours tie"]["why"] == "same rank; the stronger page" and assignments[0]["search"] == "billable hours"       # biggest volume first
# recommendations
by = {(x["action"], x["page"]): x for x in recs}
assert by[("Redirect duplicate", U("/tool/"))]["tier"] == "automatic candidate" and recs[0]["page"] == U("/tool/") and recs[0]["id"] == 1
assert by[("Merge and redirect", U("/guide/"))]["tier"] == "queued fix" and "decayed: /guide/" in by[("Merge and redirect", U("/guide/"))]["evidence"]
assert by[("Merge: a person picks the page to keep", U("/y/"))]["tier"] == "alert"
d = by[("Differentiate: brief for a strategist", U("/hours/"))]
assert d["other_pages"] == U("/work/") and "3 shared searches" in d["evidence"] and d["tier"] == "alert"
# briefs: one per merge group and per differentiate pair, plus the index
names = sorted(x.name for x in (folder / "briefs").glob("*.md"))
assert names == ["INDEX.md", "differentiate-hours--work.md", "merge-1-guide.md", "merge-2-tool.md", "merge-3-y.md"], names
m = (folder / "briefs" / "merge-1-guide.md").read_text()
assert m.startswith("# Merge: keep `/guide/`, redirect 2 pages into it") and "- `/tips-2021/` → `/guide/`" in m and "810 to 50 estimated" in m
assert "clear from the data" in m and "| Sites linking to it | 50 |" in m and "Nothing ranking would be lost" in m
assert "a close call; a person should pick" in (folder / "briefs" / "merge-3-y.md").read_text()
assert (folder / "briefs" / "merge-2-tool.md").read_text().startswith("# Redirect duplicate: keep `/tool/`, redirect 1 page into it")
b = (folder / "briefs" / "differentiate-hours--work.md").read_text()
assert "| billable hours | 900 | 4 | 9 | `/hours/` | ranks higher |" in b and "## What only `/hours/` ranks for" in b
assert "- only hours (10 searches a month, ranks #3)" in b and "hasn't been fetched" in b
assert "Notes from the hand review" not in b                                   # labels in this fixture carry no notes
assert "differentiate-hours--work.md" in (folder / "briefs" / "INDEX.md").read_text()
section = r.content_section(U("/a/"), U("/b/"), content)
assert "- 75% of the text on `/a/` also appears on `/b/`." in section and "- 43% of the text on `/b/` also appears on `/a/`." in section
assert "Headings on both pages: What Is a Partner?" in section and "Outline of `/a/` (12 words):" in section and "- Only A" in section
notes = r.review_notes(U("/b/"), U("/a/"), [{"page_a": U("/a/"), "page_b": U("/b/"), "human_words": "Merge", "human_notes_followup": "Revised: differentiate"}])
assert notes == "## Notes from the hand review\n\n- Revised: differentiate\n" and r.review_notes(U("/a/"), U("/q/"), []) == ""
long = "Separate (homepage and pillar page, both are needed)"
assert long in r.review_notes(U("/a/"), U("/b/"), [{"page_a": U("/a/"), "page_b": U("/b/"), "human_words": long, "human_notes_followup": ""}])
assert r.review_notes(U("/a/"), U("/b/"), [{"page_a": U("/a/"), "page_b": U("/b/"), "human_words": "Merge", "human_notes_followup": ""}]) == ""
assert r.slug(U("/a-b/c/")) == "a-b-c" and r.slug(U("/")) == "home"
ref = by[("Refresh: needs a content review", U("/alone/"))]
assert ref["tier"] == "alert" and "big lost, small lost" in ref["evidence"] and "200 -> 40" in ref["evidence"]
assert by[("Prune: remove or noindex", U("/dead/"))]["tier"] == "queued fix"
assert ("Refresh: needs a content review", U("/weak/")) in by            # still ranks for 10 keywords: not pruned
assert ("Refresh: needs a content review", U("/design-services/")) in by  # a service page is never pruned or redirected
assert "6 sites still link" in by[("Redirect to the closest live page", U("/dead-linked/"))]["evidence"]
assert by[("Already handled: stale data", U("/gone/"))]["tier"] == "no action"
# a decayed page that competes with a page that has to stay gets "sharpen targeting", with the rivals named
keep = [{"call": "keep both", "page_a": U("/"), "page_b": U("/alone/"), "url_swaps": "5", "p_same_topic": "0.9"},
        {"call": "keep both", "page_a": U("/alone/"), "page_b": U("/fine/"), "url_swaps": "0", "p_same_topic": "0.9"}]
sharp = [x for x in r.recommendations(keep, [], [], pages, [], {}) if x["page"] == U("/alone/")][0]
assert sharp["action"].startswith("Sharpen targeting") and sharp["evidence"].endswith("5 searches have swapped between it and 1 kept page: /") and sharp["tier"] == "alert"
assert not any(x["page"] == U("/tool/") and x["action"].startswith("Refresh") for x in recs)        # decayed page inside a group isn't listed twice
assert len(recs) == 10 and [x["tier"] for x in recs] == sorted([x["tier"] for x in recs], key=["automatic candidate", "queued fix", "alert", "no action"].index)
# with Kev fit scores, topical fit decides when the gap is big enough; otherwise ranking still decides
fits = {(U("/hours/"), "billable hours"): 0.2, (U("/work/"), "billable hours"): 0.9,       # clear: goes to /work/ despite the lower rank
        (U("/hours/"), "hours tie"): 0.50, (U("/work/"), "hours tie"): 0.55}               # too close: unchanged
rows_kw = list(csv.DictReader((root / "x.com" / "keywords.csv").open()))
a2 = {x["search"]: x for x in r.keyword_assignments(calls, rows_kw, pages, fits)}
assert a2["billable hours"]["assign_to"] == U("/work/") and a2["billable hours"]["why"] == "better topical fit" and a2["billable hours"]["fit_page_b"] == 0.9
assert a2["hours tie"]["why"] == "same rank; the stronger page" and a2["lawyer hours"]["fit_page_a"] == ""
# evaluation: rules_v2 merge calls = pairs 1,2,3 (right) + 4 (human said differentiate); pair 7 missed
assert ev["rules_version"] == "v4" and ev["page_map_used"] is False
e = ev["rules"]
assert (e["merge_true_positives"], e["merge_false_positives"], e["merge_missed"]) == (3, 1, 1) and e["merge_precision"] == 0.75 and e["merge_recall"] == 0.75
assert e["three_way_agreement_strict"] == round(4 / 7, 3) and e["three_way_agreement_lenient"] == round(5 / 7, 3)
assert {m["pair"] for m in e["disagreements"]} == {"4", "7"} and ev["pairs"] == 7
k = ev["kev_only"]     # kev-only merge candidates (>= 0.75): pairs 1,2,3,4,5,6 -> 3 right, 3 wrong
assert (k["merge_true_positives"], k["merge_false_positives"], k["merge_missed"]) == (3, 3, 1)
for name in ("pair_calls.csv", "keyword_assignments.csv", "recommendations.csv", "merge_plan.json", "evaluation.json"):
    assert (folder / name).exists()
# word-for-word shared text is added to the evidence when page text has been fetched
(root / "x.com" / "content.json").write_text(json.dumps({
    U("/x/"): {"title": "X", "headings": [["h2", "Same heading"]], "paragraphs": ["one two three four five six seven eight nine ten"], "word_count": 10},
    U("/y/"): {"title": "Y", "headings": [["h2", "Same heading"]], "paragraphs": ["one two three four five six seven eight nine ten", "and another paragraph that is only on this page here"], "word_count": 20}}))
calls3 = r.run("x.com", root)[0]
xy = next(c for c in calls3 if c["page_a"] == U("/x/"))
assert xy["shared_text"] == 1.0 and xy["reason"].endswith("100% of one page's text is word-for-word on the other")
assert next(c for c in calls3 if c["page_a"] == U("/hours/"))["shared_text"] == ""
assert "Headings on both pages: Same heading" in (folder / "briefs" / "merge-3-y.md").read_text()
(root / "x.com" / "content.json").unlink()
# ---- rules v4: with a page map, the page's type decides what can merge, and location pages get their own handling
pm = lambda kind, place="": {"page_type": kind, "place": place}
pmap = {U("/post-a/"): pm("article"), U("/post-b/"): pm("article"), U("/boston/"): pm("location", "Boston"), U("/dallas/"): pm("location", "Dallas"),
        U("/dallas-ppc/"): pm("location", "Dallas"), U("/seo/"): pm("page"), U("/pod/"): pm("media"), U("/odd/"): pm("unknown"), U("/case/"): pm("other"),
        U("/x-services/"): pm("article")}
v4 = lambda a, b: r.call_for_pair(pair(a, b, 0.9, 0.9, 5), {}, dated, pmap)
assert v4("/post-a/", "/post-b/")[0] == "merge"
assert v4("/boston/", "/dallas/") == ("keep both", "location pages for different places (Boston and Dallas)")
assert v4("/dallas/", "/dallas-ppc/") == ("keep both", "both are location pages for Dallas")
assert v4("/post-a/", "/boston/") == ("keep both", "/boston/ is a location page for Boston")
assert v4("/post-a/", "/pod/")[1] == "/pod/ is a podcast or video page" and v4("/post-a/", "/case/")[1] == "/case/ is a page of its own type, not an article"
assert v4("/post-a/", "/odd/") == ("keep both", "/odd/ is a page whose type could not be confirmed, so it is left alone")
assert v4("/post-a/", "/seo/")[1] == "/seo/ is a standing page, not an article"
assert v4("/post-a/", "/x-services/")[0] == "merge"                  # the page map outranks the URL pattern
assert v4("/post-a/", "/unknown/")[0] == "merge" and v4("/post-a/", "/nowhere-services/")[0] == "keep both"      # not in the map: the v3 test
assert r.type_label(U("/boston/"), pmap) == "location (Boston)" and r.type_label(U("/seo/"), pmap) == "page" and r.type_label(U("/zzz/"), pmap) == ""
geo = pathlib.Path(tempfile.mkdtemp()); gf = geo / "g.com" / "analysis"; gf.mkdir(parents=True)
G = lambda p: f"https://g.com{p}"
gp = lambda url, tb, tn, status="stable": {"url": G(url), "title": "T", "status": status, "traffic_before": tb, "traffic_now": tn,
                                             "keywords_now": 20, "keywords_lost": 3, "referring_domains": 5, "page_rank": 50}
write(gf / "pages.csv", [gp("/seo/", 900, 500, "decayed"), gp("/boston-seo/", 50, 40), gp("/dallas-seo/", 60, 55), gp("/chicago-seo/", 30, 30), gp("/blog/", 5, 5)])
gpair = lambda a, b, kev, swaps: {**pair(a, b, kev, 0.9, swaps), "page_a": G(a), "page_b": G(b)}
write(gf / "pairs_judged.csv", [gpair("/boston-seo/", "/seo/", 0.9, 3), gpair("/boston-seo/", "/dallas-seo/", 0.8, 2),
                                gpair("/chicago-seo/", "/dallas-seo/", 0.8, 1), gpair("/blog/", "/seo/", 0.9, 0)])
write(gf / "page_map.csv", [{"url": G("/seo/"), "page_type": "page", "place": ""}, {"url": G("/boston-seo/"), "page_type": "location", "place": "Boston"},
                            {"url": G("/dallas-seo/"), "page_type": "location", "place": "Dallas"}, {"url": G("/chicago-seo/"), "page_type": "location", "place": "Chicago"},
                            {"url": G("/blog/"), "page_type": "hub", "place": ""}])
gk = lambda url, k, rank, vol: {"url": G(url), "keyword": k, "rank": rank, "search_volume": vol, "is_lost": "False"}
write(geo / "g.com" / "keywords.csv", [
    gk("/seo/", "law firm seo", 9, 900), gk("/boston-seo/", "law firm seo", 4, 900),               # no place named -> the main page, though Boston ranks higher
    gk("/seo/", "boston law firm seo", 3, 100), gk("/boston-seo/", "boston law firm seo", 8, 100),  # names Boston -> the Boston page
    gk("/boston-seo/", "dallas seo agency", 5, 70), gk("/dallas-seo/", "dallas seo agency", 9, 70),  # names Dallas -> the Dallas page
    gk("/boston-seo/", "seo agency", 5, 60), gk("/dallas-seo/", "seo agency", 9, 60)])              # two location pages, no place named -> ranking decides
gcalls, ggroups, gassign, grecs, gev, _ = r.run("g.com", geo)
assert [c["call"] for c in gcalls] == ["keep both"] * 4 and gcalls[1]["reason"] == "location pages for different places (Boston and Dallas)"
assert gcalls[0]["type_a"] == "location (Boston)" and gcalls[0]["type_b"] == "page" and not ggroups and gev is None
ga = {x["search"]: x for x in gassign}
assert ga["law firm seo"]["assign_to"] == G("/seo/") and ga["law firm seo"]["why"].startswith("no place in the search")
assert ga["boston law firm seo"]["assign_to"] == G("/boston-seo/") and ga["boston law firm seo"]["why"] == "the search names Boston"
assert ga["dallas seo agency"]["assign_to"] == G("/dallas-seo/") and ga["seo agency"]["why"] == "ranks higher" and len(gassign) == 4
gby = {x["action"]: x for x in grecs}
one = gby["Sharpen targeting: it competes with pages that have to stay"]
assert one["page"] == G("/seo/") and one["competes_with"] == G("/boston-seo/") and one["brief"] == "sharpen-seo.md" and one["evidence"].endswith("location pages among them: 1")
two = gby["Sharpen targeting: location pages competing with each other"]
assert (two["page"], two["other_pages"], two["tier"], two["brief"]) == (G("/boston-seo/"), G("/dallas-seo/"), "alert", "sharpen-boston-seo--dallas-seo.md")
assert "2 searches have swapped between them; 2 shared searches with a suggested owner" in two["evidence"]
assert len(grecs) == 2 and list(grecs[0]) == r.REC_FIELDS                 # Chicago/Dallas swapped once: below the bar. Boston/main page is covered by the first finding
gnames = sorted(x.name for x in (gf / "briefs").glob("*.md"))
assert gnames == ["INDEX.md", "sharpen-boston-seo--dallas-seo.md", "sharpen-seo.md"], gnames
sb = (gf / "briefs" / "sharpen-seo.md").read_text()
assert sb.startswith("# Sharpen targeting: `/seo/`\n") and "900 to 500 estimated visits" in sb and "| Page type | page | location (Boston) |" in sb
assert "| law firm seo | 900 | 9 | 4 | `/seo/` | no place in the search" in sb and "2. Name the neighborhoods" in sb
jb = (gf / "briefs" / "sharpen-boston-seo--dallas-seo.md").read_text()
assert jb.startswith("# Sharpen targeting: `/boston-seo/` and `/dallas-seo/`") and "| dallas seo agency | 70 | 5 | 9 | `/dallas-seo/` | the search names Dallas |" in jb
assert "Sharpen targeting" in (gf / "briefs" / "INDEX.md").read_text()
general = r.sharpen_brief(U("/alone/"), [U("/fine/")], False, [], pages, None)
assert "2. Make the title, main heading" in general and "neighborhoods" not in general and "- None on record." in general and "Page type" not in general
# ---- broken addresses: an address that returns an error while searches or links still point at it is a finding, not "handled"
site_map = ["https://m.com/blog/a-post/", "https://m.com/blog/", "https://m.com/service-areas/milford/", "https://m.com/blog/twice/", "https://m.com/news/twice/", "https://m.com/hvac/still-here/"]
assert r.new_address("https://m.com/hvac/a-post/", site_map) == "https://m.com/blog/a-post/" and r.new_address("https://www.m.com/milford", site_map) == "https://m.com/service-areas/milford/"
assert r.new_address("https://m.com/x/twice/", site_map) == "" and r.new_address("https://m.com/x/nowhere/", site_map) == "" and r.new_address("https://m.com/", site_map) == ""
assert r.new_address("https://m.com/hvac/still-here/", site_map) == ""          # the only match is the page itself
M = lambda p: f"https://m.com{p}"
mp = lambda url, tb, tn, kw, rd, status="stable": {"url": M(url), "title": "T", "status": status, "traffic_before": tb, "traffic_now": tn, "keywords_now": kw,
                                                    "keywords_lost": 1, "referring_domains": rd, "page_rank": 0, "top10_now": 3}
mpages = {p["url"]: p for p in [mp("/hvac/a-post/", 2400, 750, 66, 0, "decayed"), mp("/milford/", 40, 70, 9, 0), mp("/highland-mi/", 70, 69, 25, 0),
                                mp("/old-linked/", 5, 0, 0, 4), mp("/dead/", 30, 0, 0, 0, "decayed"), mp("/moved/", 100, 10, 2, 0, "decayed"), mp("/fine/", 10, 10, 5, 0)]}
mstatus = {M("/hvac/a-post/"): {"status_code": "404", "redirects_to": ""}, M("/milford/"): {"status_code": "404", "redirects_to": ""}, M("/highland-mi/"): {"status_code": "410", "redirects_to": ""},
           M("/old-linked/"): {"status_code": "404", "redirects_to": ""}, M("/dead/"): {"status_code": "404", "redirects_to": ""},
           M("/moved/"): {"status_code": "301", "redirects_to": M("/fine/")}, M("/fine/"): {"status_code": "200", "redirects_to": ""}}
r.set_main_host(mpages)
mrecs = r.recommendations([], [], [], mpages, [], mstatus, None, site_map)
mby = {x["page"]: x for x in mrecs}
a = mby[M("/hvac/a-post/")]
assert (a["tier"], a["action"], a["redirect_to"]) == ("queued fix", r.BROKEN_FIX, "https://m.com/blog/a-post/")
assert a["evidence"] == "returns 404; ranked for 66 searches at the last data check (3 on page one), about 750 est. visits a month then; the sitemap lists a page with the same name at /blog/a-post/", a["evidence"]
assert mby[M("/milford/")]["redirect_to"] == "https://m.com/service-areas/milford/"                       # a stable page that is broken is still a finding
h = mby[M("/highland-mi/")]
assert (h["tier"], h["action"], h["redirect_to"]) == ("alert", r.BROKEN_ASK, "") and h["evidence"].startswith("returns 410") and h["evidence"].endswith("no single page with the same name")
assert mby[M("/old-linked/")]["action"] == r.BROKEN_ASK and "4 sites link to it" in mby[M("/old-linked/")]["evidence"]        # nothing ranks, but links still point at it
assert mby[M("/dead/")]["tier"] == "no action" and mby[M("/dead/")]["action"].startswith("Gone:")          # nothing points at it: nothing to do
assert mby[M("/moved/")]["action"] == "Already handled: stale data" and M("/fine/") not in mby
assert [x["page"] for x in mrecs][:2] == [M("/hvac/a-post/"), M("/milford/")] and "_weight" not in mrecs[0]      # queued first, most visits at stake first
# pages on a subdomain are shown with their host, so two homepages are not both "/"
r.set_main_host(["https://www.h.com/a/", "https://www.h.com/b/", "https://lp.h.com/"])
assert r.path_of("https://www.h.com/a/") == "/a/" and r.path_of("https://h.com/") == "/" and r.path_of("https://lp.h.com/") == "lp.h.com/"
assert r.slug("https://lp.h.com/") == "lp-h-com" and r.slug("https://www.h.com/") == "home"
assert "| Title | A / B |" in r.page_table(["https://www.h.com/a/"], {"https://www.h.com/a/": {"title": "A | B"}})
r.MAIN_HOSTS.clear()
# a site with nothing to recommend must not crash
empty = root / "e.com" / "analysis"; empty.mkdir(parents=True)
write(empty / "pages.csv", [P("/a/", 1, 1, 1, 0, 0)]); (empty / "pairs_judged.csv").write_text(""); (root / "e.com" / "keywords.csv").write_text("url,keyword,rank,search_volume,is_lost\n")
assert r.run("e.com", root)[3] == []
print("ALL TESTS PASSED")
