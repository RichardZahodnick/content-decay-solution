import csv, json, pathlib, tempfile, time, run_site as rs, test_recommend
import sizing_check as dfs

# the site name is the only input: anything that is not a plain domain is refused
assert rs.clean_domain("https://www.Example.com/") == "example.com" and rs.clean_domain("seo.example.co.uk") == "seo.example.co.uk"
for bad in ("", "example", "example.com/blog", "example.com; rm -rf ~", "a b.com", "--fresh", "../etc.com", "x.com --fresh", "http://127.0.0.1", "-x.com"):
    try:
        rs.clean_domain(bad); raise AssertionError(bad)
    except rs.Refused:
        pass
home = str(rs.pathlib.Path.home())
assert rs.shown(home + "/openclaw/data/x.com/report.html") == "~/openclaw/data/x.com/report.html"
assert rs.shown(home + "/mnt/openclaw/data/x.com/report.html") == "~/openclaw/data/x.com/report.html" and rs.shown("/elsewhere/a") == "/elsewhere/a"
# cost estimate: 3,358 rows = 4 pages of keywords + per-row fees + the history call
assert rs.estimate_cost(3358) == round(4 * 0.012 + 3358 * 0.00012 + 0.12 + 72 * 0.0012, 2) == 0.66
assert rs.estimate_cost(50000) == rs.estimate_cost(10000) and rs.estimate_cost(0) == 0.22

root = pathlib.Path(tempfile.mkdtemp())
# spend log and the daily cap
assert rs.spent_today(root, "2026-10-02") == 0.0
rs.record_spend(root, "a.com", 0.66, "full pull", "2026-10-02"); rs.record_spend(root, "b.com", 1.5, "full pull", "2026-10-01")
assert rs.spent_today(root, "2026-10-02") == 0.66 and rs.spent_today(root, "2026-10-01") == 1.5
def api(total, cost=0.0101):
    def fetch(endpoint, payload):
        result = {"total_count": total, "items": []}
        return {"status_code": 20000, "cost": cost, "tasks": [{"status_code": 20000, "result": [result]}]}
    return fetch
def refused(**k):
    try:
        rs.pull_step("new.com", root, True, auth="x", **k); raise AssertionError("not refused")
    except rs.Refused as stop:
        return str(stop)
rs.MAX_SPEND_PER_RUN = 1.00
assert "about $1.53, above the $1.00 limit for one run" in refused(fetch=api(40000), today="2026-10-03")      # a pull stops at 10,000 rows, so $1.53 is the most one can cost
rs.MAX_SPEND_PER_RUN = 2.00
rs.record_spend(root, "c.com", 4.2, "full pull", "2026-10-04")
assert "would pass the $5.00 daily limit" in refused(fetch=api(9000), today="2026-10-04")
assert "has no ranking keywords" in refused(fetch=api(0), today="2026-10-05")
assert abs(rs.spent_today(root, "2026-10-04") - 4.2101) < 1e-9                    # the one-cent size check is logged even when the pull is refused
assert not (root / "new.com" / "keywords.csv").exists()
before = dfs.total_cost
result, note = rs.pull_step("new.com", root, True, auth="x", fetch=api(3), today="2026-10-06")
assert result == "done" and "cost $0.02" in note and (root / "new.com" / "keywords.csv").exists() and abs(rs.spent_today(root, "2026-10-06") - 0.0303) < 1e-9
result, note = rs.pull_step("new.com", root, False, auth="x", fetch=None)        # data on disk and no --fresh: nothing is spent, no API call is made
assert result == "skipped" and "already on disk" in note

# one run at a time; a stale or released lock does not block
lock = rs.take_lock(root, now=1000.0)
try:
    rs.take_lock(root, now=1000.0 + 59 * 60); raise AssertionError("lock ignored")
except rs.Refused as stop:
    assert "59 minutes ago" in str(stop)
rs.take_lock(root, now=1000.0 + 61 * 60); lock.write_text("free"); rs.take_lock(root, now=5.0); lock.unlink()

# Kev down: nothing starts
down = lambda body: (_ for _ in ()).throw(OSError("refused"))
up = lambda body: {"answers": {"q": {"noul": 0.9}}}
assert rs.kev_is_up(up) and not rs.kev_is_up(down)
try:
    rs.run("x.com", root, kev_send=down); raise AssertionError("ran without Kev")
except rs.Refused as stop:
    assert "Kev is not answering" in str(stop) and not (root / "run.lock").exists()

# step policy: an optional step may fail and the run carries on; a required step failing stops the rest
log = []
def ok(name):
    def step(domain, data_dir, **extra):
        log.append((name, extra)); return "done", f"{name} fine"
    return step
def boom(domain, data_dir, **extra):
    raise RuntimeError("site blocked us")
steps = [("pull rankings", "DataForSEO", ok("pull"), False), ("check live addresses", "the live site", boom, False), ("recommend", "nothing", ok("recommend"), True)]
status = rs.run("https://www.S.com/", root, steps=steps, kev_send=up, say=lambda *_: None)
assert status["site"] == "s.com" and status["ok"] and [s["result"] for s in status["steps"]] == ["done", "failed", "done"]
assert status["steps"][1]["note"] == "RuntimeError: site blocked us" and [n for n, _ in log] == ["pull", "recommend"]
saved = json.loads((root / "s.com" / "analysis" / "run_status.json").read_text())
assert saved["mode"] == "normal" and saved["finished"] and len(saved["steps"]) == 3 and not (root / "run.lock").exists()
text = (root / "s.com" / "run_summary.md").read_text()
assert "All steps completed." in text and "| check live addresses | the live site | failed |" in text and "## Result" not in text       # no analysis files: no numbers invented
steps = [("pull rankings", "DataForSEO", boom, False), ("recommend", "nothing", ok("recommend2"), True)]
status = rs.run("s.com", root, steps=steps, kev_send=up, say=lambda *_: None)
assert not status["ok"] and [s["result"] for s in status["steps"]] == ["failed", "not run"] and "did NOT complete" in (root / "s.com" / "run_summary.md").read_text()
def cap(domain, data_dir, **extra):
    raise rs.Refused("over the daily limit")
status = rs.run("s.com", root, steps=[("pull rankings", "DataForSEO", cap, False)], kev_send=up, say=lambda *_: None)
assert not status["ok"] and status["steps"][0]["result"] == "refused" and status["steps"][0]["note"] == "over the daily limit"
log.clear()
status = rs.run("s.com", root, offline=True, steps=[("pull rankings", "DataForSEO", ok("pull"), False), ("recommend", "nothing", ok("rec"), True)], kev_send=down, say=lambda *_: None)
assert status["ok"] and [s["result"] for s in status["steps"]] == ["skipped", "done"] and [n for n, _ in log] == ["rec"] and status["mode"] == "offline"

# the summary reads its numbers from the files: the location fixture from the rules tests
import test_report                                             # adds history and summary.json to that fixture
geo = test_recommend.geo
status = rs.run("g.com", geo, offline=True, steps=[s for s in rs.STEPS if s[0] in ("recommend", "build the report")], say=lambda *_: None)
assert status["ok"] and [s["result"] for s in status["steps"]] == ["done", "done"], status
text = (geo / "g.com" / "run_summary.md").read_text()
for expected in ("# Content decay check: g.com", "- 1 of 5 pages decayed on their own between Apr 2026 and Sep 2026. Together they went from 900 to 500 estimated visits a month.",
                 "- The whole site changed -10% over the same window.", "- 4 pairs of pages compete for the same searches: 4 where both pages have to stay (nothing to merge).",
                 "- 2 recommendations: 0 automatic, 0 queued for approval, 2 alerts for a person to decide.", "- Page types: 3 location, 1 page, 1 unknown.",
                 "1. [alert] Sharpen targeting: it competes with pages that have to stay: /seo/ (with /boston-seo/). Estimated visits a month 900 to 500.",
                 "| recommend | nothing | done |", "report.html", "A person approves every fix"):
    assert expected in text, expected
print("ALL TESTS PASSED")
