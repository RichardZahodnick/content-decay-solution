import analyze_site as a

# --- search keys ---
assert a.search_key("SEO for Lawyers") == a.search_key("lawyers seo") == "lawyer seo"
assert a.search_key("business") == "business" and a.search_key("the") == "" and a.search_key(None) == ""

def row(kw, url, rank, vol, etv, prev=None, lost=False, rank_abs=None, core="", rd=0, pr=0, checked="2026-09-10"):
    return {"keyword": kw, "core_keyword": core, "search_volume": vol, "url": url, "title": "T " + url,
            "rank": rank, "rank_absolute": rank_abs if rank_abs is not None else rank,
            "previous_rank_absolute": "" if prev is None else prev, "is_lost": str(lost),
            "etv": etv, "referring_domains": rd, "page_rank": pr, "serp_checked": checked}

# click rates: position 1 = 30%, position 2 = 10%, position 10 = 2%  (position 6 is interpolated: 6%)
A, B, C, H = "https://x.com/a/", "https://x.com/b/", "https://x.com/c/", "https://x.com/"
rows = [
    row("alpha widgets", C, 1, 1000, 300, prev=1, rd=5, pr=50),      # C: stable 300 -> 300
    row("beta tools", C, 2, 1000, 100, prev=2),                       # C: stable 100 -> 100
    row("gamma kits", C, 10, 1000, 20, prev=10),                      # C: 20 -> 20
    # A held "lawyer seo" at #1 and lost it; B now ranks #10 for the same keyword -> URL swap
    row("lawyer seo", A, 1, 1000, 300, prev=1, lost=True),            # A: before 300, now 0
    row("seo for lawyers", A, 2, 500, 50, prev=1, rank_abs=4),        # A: offset 2 -> prev rank 1 (clamped) = 150 before, 50 now
    row("lawyer seo", B, 10, 1000, 20),                               # B: new keyword, 0 -> 20
    row("lawyers seo", B, 10, 500, 10, prev=12, rank_abs=10),         # B: prev rank 12 -> beyond known, uses rank-10 rate = 10 before
    row("lawyer seo", H, 2, 1000, 100, prev=2),                       # homepage also ranks for it
    row("seo lawyer", H, 2, 500, 50, prev=2),
    # an old loss (more than 150 days before the newest check): counted separately, not in "before"
    row("delta gear", C, 3, 9000, 900, prev=3, lost=True, checked="2026-02-01"),
    row("delta gear", B, 10, 9000, 180, checked="2026-09-01"),       # ...but the swap is still recorded
]
rate = a.click_rates(rows)
assert abs(rate(1) - 0.30) < 1e-9 and abs(rate(2) - 0.10) < 1e-9 and abs(rate(10) - 0.02) < 1e-9
assert abs(rate(6) - 0.06) < 1e-9 and abs(rate(50) - 0.02) < 1e-9 and abs(rate(0) - 0.30) < 1e-9

pages, pairs, clusters, summary = a.analyze(rows, "x.com")
by = {p["url"]: p for p in pages}
# page A: before 300 + 150 = 450, now 50 -> -88.9%
assert by[A]["traffic_before"] == 450.0 and by[A]["traffic_now"] == 50.0 and by[A]["change_pct"] == -0.889
assert by[A]["keywords_lost"] == 1 and by[A]["keywords_now"] == 1 and by[A]["keywords_before"] == 2
assert by[A]["top10_before"] == 2 and by[A]["top10_now"] == 1
assert by[C]["traffic_before"] == by[C]["traffic_now"] == 420.0 and by[C]["status"] == "stable"
assert by[C]["referring_domains"] == 5 and by[C]["page_rank"] == 50 and by[C]["top_keyword"] in ("alpha widgets", "beta tools", "gamma kits")
assert by[C]["keywords_before"] == 3 and by[C]["keywords_now"] == 3
assert by[C]["dated_share"] == ""                                 # this fixture has no "dated" column
dated_rows = [dict(r, dated=str(r["url"] == A)) for r in rows]
assert {p["url"]: p["dated_share"] for p in a.analyze(dated_rows, "x.com")[0]} == {A: 1.0, B: 0.0, C: 0.0, H: 0.0}
assert by[C]["keywords_lost"] == 0 and by[C]["keywords_lost_earlier"] == 1 and by[A]["keywords_lost_earlier"] == 0
assert summary["newest_check"] == "2026-09-10" and summary["window_start"] == "2026-04-13"
assert by[B]["traffic_before"] == 10.0 and by[B]["traffic_now"] == 210.0 and by[B]["keywords_new"] == 2 and by[B]["status"] == "growing"
# site: before 450+420+10+150 = 1030, now 50+420+210+150 = 830 -> -19.4%
assert summary["traffic_before"] == 1030 and summary["traffic_now"] == 830 and summary["site_change_pct"] == -0.194
# A is -89% vs site -19%: more than 15 points worse -> decayed
assert by[A]["status"] == "decayed", by[A]
assert pages[0]["url"] == A                      # sorted by biggest loss first
# pairs: A-B share the key "lawyer seo" once (both variants collapse to one key) + one swap
ab = next(p for p in pairs if {p["page_a"], p["page_b"]} == {A, B})
assert ab["shared_searches"] == 1 and ab["url_swaps"] == 1 and ab["swapped_volume"] == 1000 and not ab["involves_homepage"]
assert ab["_swaps"][0] == {"keyword": "lawyer seo", "volume": 1000, "held_by": A, "held_rank": 1, "now_by": B, "now_rank": 10}
ah = next(p for p in pairs if {p["page_a"], p["page_b"]} == {A, H})
assert ah["involves_homepage"] and ah["url_swaps"] == 1
# clusters: only A+B; the homepage must not join or bridge clusters; C is in none
bc = next(p for p in pairs if {p["page_a"], p["page_b"]} == {B, C})
assert bc["url_swaps"] == 1 and bc["_swaps"][0]["held_by"] == C and bc["_swaps"][0]["now_by"] == B
assert len(clusters) == 1 and set(clusters[0]["pages"]) == {A, B, C} and len(clusters[0]["url_swaps"]) == 2
assert by[A]["cluster"] == by[B]["cluster"] == by[C]["cluster"] == 1 and by[H]["cluster"] == ""

# --- status rules in isolation ---
S = a.status_for
assert S(5, 3, 0) == "too small to judge" and S(5, 50, 0) == "new or growing"
assert S(100, 60, 0.0) == "decayed" and S(100, 80, 0.0) == "watch" and S(100, 95, 0.0) == "stable" and S(100, 130, 0.0) == "growing"
assert S(100, 60, -0.35) == "fell with the site"          # down 40% while the site is down 35%
assert S(100, 71, 0.0) == "watch" and S(100, 70, 0.0) == "decayed"

# --- saving ---
import pathlib, tempfile, csv, json
out = a.save("x.com", pages, pairs, clusters, summary, pathlib.Path(tempfile.mkdtemp()))
saved = list(csv.DictReader((out / "pairs.csv").open()))
assert "_swaps" not in saved[0] and len(saved) == len(pairs)
assert json.loads((out / "summary.json").read_text())["thresholds"]["DROP_PCT"] == -0.3
assert a.analyze([], "x.com")[3]["pages"] == 0 and a.save("y.com", [], [], [], {}, out.parent.parent)
print("ALL TESTS PASSED")
