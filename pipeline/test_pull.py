import csv, pathlib, tempfile, pull_site as p, sizing_check as s

def item(kw, url, rank, lost=False):
    return {"keyword_data": {"keyword": kw, "keyword_info": {"search_volume": 100},
              "keyword_properties": {"core_keyword": "core", "keyword_difficulty": 9},
              "search_intent_info": {"main_intent": "commercial"}},
            "ranked_serp_element": {"is_lost": lost, "serp_item_types": ["ai_overview", "organic"],
              "last_updated_time": "2026-09-12 09:05:38 +00:00", "previous_updated_time": None,
              "serp_item": {"url": url, "title": "T", "pre_snippet": "01/28/2026 00:00:00" if url.endswith("/1") else None, "rank_group": rank, "rank_absolute": rank + 1, "etv": 3.5,
                "rank_changes": {"previous_rank_absolute": 5, "is_new": False, "is_up": True, "is_down": False},
                "backlinks_info": {"referring_domains": 12}, "rank_info": {"page_rank": 132}}}}

calls = []
def fake(endpoint, payload):
    calls.append((endpoint, dict(payload)))
    if endpoint.startswith("ranked_keywords"):
        assert payload["historical_serp_mode"] == "all" and payload["limit"] == 2
        everything = [item("a", "https://x.com/1", 1), item("b", "https://x.com/1", 4),
                      item("c", "https://x.com/2", 9, lost=True)]
        result = {"total_count": 3, "items": everything[payload["offset"]:payload["offset"] + 2]}
    else:
        assert payload["date_from"] == "2020-10-01"
        m = lambda y, mo, etv: {"year": y, "month": mo, "metrics": {"organic": {"etv": etv, "count": 7, "pos_1": 1, "pos_2_3": 2, "pos_4_10": 3}}}
        result = {"items": [m(2021, 2, 20.6), m(2020, 10, 10)]}
    return {"status_code": 20000, "cost": 0.05, "tasks": [{"status_code": 20000, "result": [result]}]}

out = pathlib.Path(tempfile.mkdtemp())
summary = p.pull("x.com", "auth", out, fake, page_size=2)
assert summary == {"domain": "x.com", "keyword_rows": 3, "reported_total": 3, "pages": 2, "lost": 1, "months": 2, "first_month": "2020-10"}, summary
assert [c[1].get("offset") for c in calls if c[0].startswith("ranked")] == [0, 2]
rows = list(csv.DictReader((out / "x.com" / "keywords.csv").open()))
assert len(rows) == 3 and rows[0]["url"] == "https://x.com/1" and rows[0]["referring_domains"] == "12"
assert rows[2]["is_lost"] == "True" and rows[0]["ai_overview_on_serp"] == "True" and rows[0]["serp_checked"] == "2026-09-12" and rows[0]["previous_check"] == ""
assert rows[0]["dated"] == "True" and rows[2]["dated"] == "False"
(out / "x.com" / "keywords.csv").write_text("gone")
assert p.reflatten("x.com", out) == 3                                       # rebuilt from the saved replies, no fetch
assert list(csv.DictReader((out / "x.com" / "keywords.csv").open())) == rows
hist = list(csv.DictReader((out / "x.com" / "history.csv").open()))
assert hist == [{"month": "2020-10", "etv": "10", "keywords": "7", "top3": "3", "top10": "6"},
                {"month": "2021-02", "etv": "21", "keywords": "7", "top3": "3", "top10": "6"}], hist
assert len(list((out / "raw" / "x.com").glob("*.json"))) == 3
# empty site must not loop forever or crash
empty = lambda e, pl: {"status_code": 20000, "cost": 0, "tasks": [{"status_code": 20000, "result": [{"total_count": 0, "items": None}]}]}
assert p.pull("y.com", "auth", out, empty)["keyword_rows"] == 0
print("ALL TESTS PASSED")
