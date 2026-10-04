import csv, json, pathlib, tempfile, judge_pairs as j

assert j.same_address("https://x.com/ppc//", "https://x.com/ppc/") and j.same_address("https://X.com/a", "https://x.com/a/")
assert not j.same_address("https://x.com/a/", "https://x.com/b/")
assert j.verdict_for(0.75) == "merge candidate" and j.verdict_for(0.74) == "needs review"
assert j.verdict_for(0.45) == "needs review" and j.verdict_for(0.44) == "keep separate"
assert j.same_title_apart_from_year("Billing Software: The 18 Best Options in 2026", "Billing Software: The 18 Best Options in 2025")
assert not j.same_title_apart_from_year("Billing Software", "Billable Hours") and not j.same_title_apart_from_year("", "")

root = pathlib.Path(tempfile.mkdtemp()); folder = root / "x.com" / "analysis"; folder.mkdir(parents=True)
U = lambda p: f"https://x.com/{p}"
def write(path, rows):
    with path.open("w", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
write(folder / "pairs.csv", [
    {"page_a": U("a/"), "page_b": U("b/"), "shared_searches": 3, "involves_homepage": "False"},   # kev: same
    {"page_a": U("b/"), "page_b": U("c/"), "shared_searches": 2, "involves_homepage": "False"},   # kev: different
    {"page_a": U("c/"), "page_b": U("d/"), "shared_searches": 2, "involves_homepage": "False"},   # kev: unsure
    {"page_a": U("e/"), "page_b": U("e//"), "shared_searches": 5, "involves_homepage": "False"},  # same address
    {"page_a": U(""), "page_b": U("a/"), "shared_searches": 4, "involves_homepage": "True"},      # homepage, kev: same
    {"page_a": U("f/"), "page_b": U("g/"), "shared_searches": 2, "involves_homepage": "False"},   # same title, different year
])
write(folder / "pages.csv", [{"url": U(p), "title": "Title " + p, "traffic_before": t}
                             for p, t in [("a/", 100), ("b/", 300), ("c/", 50), ("d/", 5), ("e/", 20), ("e//", 1), ("", 900)]]
      + [{"url": U("f/"), "title": "Best Tools in 2026", "traffic_before": 2}, {"url": U("g/"), "title": "Best Tools in 2025", "traffic_before": 1}])
write(root / "x.com" / "keywords.csv", [
    {"url": U("a/"), "keyword": "small kw", "etv": 1, "is_lost": "False"},
    {"url": U("a/"), "keyword": "big kw", "etv": 9, "is_lost": "False"},
    {"url": U("a/"), "keyword": "gone kw", "etv": 99, "is_lost": "True"}])

seen = []
SCORES = {("a/", "b/"): (0.95, 0.85), ("b/", "c/"): (0.2, 0.0), ("c/", "d/"): (0.9, 0.3), ("", "a/"): (1.0, 0.9)}
def fake(body):
    q = body["questions"]["q"]
    assert body["model"] == "kev-latest" and q["type"] == "noul" and set(q["criteria"]) == {"true", "false"}
    seen.append(body["state"])
    a, b = body["state"]["page_a"], body["state"]["page_b"]
    with_searches = a.startswith("Title: ")
    key = tuple(x.replace("Title: Title ", "").replace("Title ", "").split(" |")[0] for x in (a, b))
    return {"answers": {"q": {"type": "noul", "noul": SCORES[key][0 if with_searches else 1]}}}

judged, groups, calls = j.judge_site("x.com", root, fake)
assert calls == 8 and len(judged) == 6                 # 4 pairs x 2 questions; the two code-decided pairs never go to Kev
assert seen[0] == {"page_a": "Title: Title a/ | Top searches: big kw, small kw", "page_b": "Title: Title b/"}   # lost kw excluded, best first
assert seen[1] == {"page_a": "Title a/", "page_b": "Title b/"}
v = {(p["page_a"], p["page_b"]): p for p in judged}
ab = v[(U("a/"), U("b/"))]
assert ab["verdict"] == "merge candidate" and ab["p_same_topic"] == 0.9 and ab["p_with_searches"] == 0.95 and ab["p_titles_only"] == 0.85
assert v[(U("b/"), U("c/"))]["verdict"] == "keep separate" and v[(U("b/"), U("c/"))]["p_same_topic"] == 0.1
assert v[(U("c/"), U("d/"))]["verdict"] == "needs review" and v[(U("c/"), U("d/"))]["p_same_topic"] == 0.6
assert v[(U("e/"), U("e//"))]["decided_by"] == "code: same page, two addresses" and v[(U("e/"), U("e//"))]["verdict"] == "merge candidate"
assert v[(U("f/"), U("g/"))]["decided_by"] == "code: same title apart from the year" and v[(U("f/"), U("g/"))]["p_same_topic"] == 1.0
assert v[(U(""), U("a/"))]["verdict"] == "needs review" and v[(U(""), U("a/"))]["p_same_topic"] == 0.95   # homepage is never auto-merged
# groups: {b, a} (b first: more traffic) and {e, e//}; c is NOT chained to a/b through the rejected b-c pair
assert [g["pages"] for g in groups] == [[U("b/"), U("a/")], [U("e/"), U("e//")], [U("f/"), U("g/")]], groups
assert groups[0]["lowest_pair_confidence"] == 0.9 and groups[1]["pairs"][0]["decided_by"].startswith("code")
assert len((folder / "kev_log.jsonl").read_text().splitlines()) == 8
assert len(list(csv.DictReader((folder / "pairs_judged.csv").open()))) == 6 and json.loads((folder / "merge_groups.json").read_text()) == groups
# a malformed Kev reply must stop the run, not be guessed at
P = {"title": "t", "top_searches": []}
for bad in ({"answers": {}}, {"answers": {"q": {"noul": "high"}}}, {"answers": {"q": {"noul": 1.4}}}):
    try: j.ask_kev(P, P, lambda body: bad); raise AssertionError("should have stopped")
    except SystemExit as e: assert "no usable answer" in str(e)
# selftest logic
good = lambda body: {"answers": {"q": {"noul": 0.9 if ("Budgeting Apps" in str(body["state"]["page_b"]) or "Faucet Repair" in str(body["state"]["page_b"])) else 0.1}}}
assert j.selftest(good) is True
assert j.selftest(lambda body: {"answers": {"q": {"noul": 0.5}}}) is False
print("ALL TESTS PASSED")
