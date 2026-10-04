import pathlib, tempfile, sizing_check as s

def fake(endpoint, payload):
    assert payload["target"] == "example.com" and payload["location_code"] == 2840
    if endpoint.startswith("ranked_keywords"):
        result = {"total_count": 4321, "items": []}
    elif endpoint.startswith("relevant_pages"):
        mk = lambda c, p1, up, down: {"page_address": "x", "metrics": {"organic": {"count": c, "pos_1": p1, "pos_2_3": 0, "pos_4_10": 0, "is_up": up, "is_down": down}}}
        result = {"total_count": 3, "items": [mk(40, 2, 1, 5), mk(6, 0, 3, 1), mk(1, 0, 0, 0)]}
    else:
        m = lambda y, mo, etv: {"year": y, "month": mo, "metrics": {"organic": {"etv": etv, "count": 10}}}
        result = {"items": [m(2025, 3, 500.4), m(2024, 11, 1000.2), m(2026, 9, 400.0)]}
    return {"status_code": 20000, "cost": 0.1, "tasks": [{"status_code": 20000, "result": [result]}]}

out = pathlib.Path(tempfile.mkdtemp())
row = s.size_domain("example.com", "x", out, fake)
assert row["keywords"] == 4321 and row["pages"] == 3, row
assert row["pages_5plus_kw"] == 2 and row["pages_top10"] == 1 and row["pages_losing"] == 1, row
assert (row["first"], row["peak"], row["peak_etv"], row["now_etv"], row["vs_peak"]) == ("2024-11", "2024-11", 1000, 400, "-60%"), row
assert len(list(out.glob("example.com__*.json"))) == 3
assert abs(s.total_cost - 0.3) < 1e-9
# empty history and null result must not crash
empty = lambda e, p: {"status_code": 20000, "cost": 0, "tasks": [{"status_code": 20000, "result": None}]}
row2 = s.size_domain("example.com", "x", out, empty)
assert row2["keywords"] == 0 and row2["vs_peak"] == "-", row2
# a task-level error must stop the run
bad = lambda e, p: {"status_code": 20000, "tasks": [{"status_code": 40501, "status_message": "Invalid Field"}]}
try:
    s.size_domain("example.com", "x", out, bad); raise AssertionError("should have exited")
except SystemExit as e:
    assert "40501" in str(e)
# auth file parsing
envf = out / "e.env"; envf.write_text("# c\nDATAFORSEO_LOGIN=a@b.com\nDATAFORSEO_PASSWORD=p=w\n")
import base64; assert base64.b64decode(s.load_auth(envf).split()[1]).decode() == "a@b.com:p=w"
s.report([row, row2]); print("ALL TESTS PASSED")
