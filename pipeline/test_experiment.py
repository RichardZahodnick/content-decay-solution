import csv, pathlib, tempfile
import kev_experiment as k

# the pairs file: 6 same, 7 different, 2 hard, as in the run that chose the wording
rows = [("same", f"/guide-{n}/", f"/guide-{n}-2025/") for n in range(6)] + [("different", f"/topic-{n}/", f"/other-{n}/") for n in range(7)] \
     + [("different (hard)", f"/guide-{n}/", f"/related-{n}/") for n in range(2)]
data = pathlib.Path(tempfile.mkdtemp())
(data / "experiments").mkdir()
with (data / "experiments" / k.PAIRS_FILE).open("w", newline="") as handle:
    csv.writer(handle).writerows([("expected", "site", "path_a", "path_b")] + [(e, "example.com", a, b) for e, a, b in rows])
labeled = k.load_labeled(data)
assert len(labeled) == 15 and labeled[0] == ("same", "https://example.com/guide-0/", "https://example.com/guide-0-2025/")

pages = {url: {"title": "T" + url[19:], "searches": ["s" + url[19:]]} for _, a, b in labeled for url in (a, b)}
pages["https://example.com/guide-1-2025/"]["searches"] = []       # a page with no live searches
calls = []
def fake(body):
    q = body["questions"]["q"]
    assert q["type"] == "noul" and set(q["criteria"]) == {"true", "false"} and body["model"] == "kev-latest"
    calls.append(body["state"])
    blob = str(body["state"])
    return {"answers": {"q": {"type": "noul", "noul": 0.8 if ("guide-1-2025" in blob or "guide-2-2025" in blob) else 0.3}}}
results, summary = k.run(pages, labeled, fake)
assert len(results) == 15 and set(results[0]["scores"]) == set(k.VARIANTS) and results[1]["page_b"] == "/guide-1-2025/"
assert len(calls) == 15 * 6                                          # 4 single-call wordings + 2 calls for search fit
assert results[1]["scores"]["C titles only"] == 0.8 and results[0]["scores"]["C titles only"] == 0.3
# search fit falls back to the title when a page has no searches
assert any(s.get("search_query") == "T/guide-1-2025/" for s in calls if "search_query" in s)
s = summary["C titles only"]
assert s["lowest_same"] == 0.3 and s["highest_different"] == 0.3 and s["gap"] == 0.0 and s["pairs_ordered_correctly"] == round(2 * 9 / 54, 3)
assert k.text({"title": "X", "searches": []}) == "Title: X" and k.text({"title": "X", "searches": ["a", "b"]}) == "Title: X | Top searches: a, b"
try: k.kev({}, {"instructions": "x", "criteria": {}}, lambda b: {"answers": {}}); raise AssertionError
except SystemExit: pass
print("ALL TESTS PASSED")
