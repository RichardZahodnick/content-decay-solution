import csv, pathlib, tempfile, score_keyword_fit as s
U = lambda p: f"https://x.com{p}"
root = pathlib.Path(tempfile.mkdtemp()); folder = root / "x.com" / "analysis"; folder.mkdir(parents=True)
def write(path, rows):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
page = lambda url, title: {"url": U(url), "title": title, "status": "stable", "traffic_before": 50, "traffic_now": 50, "keywords_now": 9, "keywords_lost": 0, "referring_domains": 1, "page_rank": 1}
write(folder / "pages.csv", [page("/hours/", "Billable Hours Guide"), page("/work/", "How Many Hours Do Lawyers Work?")])
write(folder / "pairs_judged.csv", [{"page_a": U("/hours/"), "page_b": U("/work/"), "p_same_topic": 0.8, "overlap_of_smaller_page": 0.1, "url_swaps": 3,
                                     "decided_by": "kev", "shared_volume": 1, "top_shared_searches": "", "verdict": "merge candidate"}])
kw = lambda url, k, rank: {"url": U(url), "keyword": k, "rank": rank, "search_volume": 100, "is_lost": "False"}
write(root / "x.com" / "keywords.csv", [kw("/hours/", "lawyer free time", 5), kw("/work/", "lawyer free time", 30), kw("/hours/", "billable hours", 3), kw("/work/", "billable hours", 8)])
s.recommend.run("x.com", root)                                       # first pass: by ranking
seen = []
def fake(body):
    q = body["questions"]["q"]; st = body["state"]; seen.append((st["search_query"], st["page_title"]))
    assert q["criteria"] == s.FIT_CRITERIA and q["type"] == "noul"
    good = (st["search_query"] == "lawyer free time") == ("Work" in st["page_title"])
    return {"answers": {"q": {"noul": 0.9 if good else 0.2}}}
fits, assignments = s.score_site("x.com", root, fake)
assert len(fits) == 4 and len(seen) == 4 and ("lawyer free time", "How Many Hours Do Lawyers Work?") in seen
a = {x["search"]: x for x in assignments}
assert a["lawyer free time"]["assign_to"] == U("/work/") and a["lawyer free time"]["why"] == "better topical fit"     # ranking said /hours/
assert a["billable hours"]["assign_to"] == U("/hours/") and a["billable hours"]["fit_page_a"] == 0.9
saved = {x["search"]: x for x in csv.DictReader((folder / "keyword_assignments.csv").open())}
assert saved["lawyer free time"]["assign_to"] == U("/work/") and len(list(csv.DictReader((folder / "keyword_fit.csv").open()))) == 4
print("ALL TESTS PASSED")
