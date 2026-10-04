"""The example site (example/make_example.py) runs through the real pipeline and shows one of each kind of finding."""
import collections, csv, pathlib, sys, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "example"))
import make_example as ex
import build_report, run_site

data = pathlib.Path(tempfile.mkdtemp())
status = ex.build(data, say=lambda *_: None)
site, folder = data / ex.SITE, data / ex.SITE / "analysis"
read = lambda name: list(csv.DictReader((folder / name).open()))
assert status["ok"] and all(step["result"] in ("done", "skipped") for step in status["steps"])

# the decay definition: fell 30% or more AND at least 15 points worse than the site
pages = {p["url"].replace(ex.HOME, ""): p for p in read("pages.csv")}
assert pages["/blog/why-is-my-furnace-blowing-cold-air/"]["status"] == "decayed"
assert pages["/blog/heat-pump-vs-furnace/"]["status"] == "fell with the site"            # down 30%, but the site is down 19%
assert pages["/blog/what-size-furnace-do-i-need/"]["status"] == "growing"

# one pair for each rule
calls = {frozenset(c[k].replace(ex.HOME, "") for k in ("page_a", "page_b")): c["call"] for c in read("pair_calls.csv")}
pair = lambda a, b: calls[frozenset({a, b})]
assert pair("/blog/best-thermostat-settings-winter-2025/", "/blog/best-thermostat-settings-winter/") == "redirect duplicate"
assert pair("/blog/why-is-my-furnace-blowing-cold-air/", "/blog/furnace-blowing-cold-air-causes/") == "merge"
assert pair("/blog/heat-pump-vs-furnace/", "/blog/how-does-a-heat-pump-work/") == "differentiate"
assert pair("/furnace-repair-columbus/", "/furnace-repair-dayton/") == "keep both"       # location pages are never merged
assert pair("/services/furnace-repair/", "/furnace-repair-columbus/") == "keep both"     # 0.74 would merge two articles; a service page stays

# the page map typed the pages from the made-up sitemap and page code
types = {r["url"].replace(ex.HOME, ""): (r["page_type"], r["place"]) for r in read("page_map.csv")}
assert types["/furnace-repair-dayton/"] == ("location", "Dayton") and types["/"][0] == "homepage" and types["/blog/"][0] == "hub"
assert not [t for t, _ in types.values() if t == "unknown"]

# the work queue: every tier, and the two kinds of broken address
recs = read("recommendations.csv")
by_action = {r["action"].split(":")[0]: r for r in recs}
assert collections.Counter(r["tier"] for r in recs) == {"automatic candidate": 1, "queued fix": 2, "alert": 5, "no action": 1}
assert by_action["Redirect duplicate"]["page"].endswith("/blog/best-thermostat-settings-winter/")            # the address without the year is kept
assert by_action["Merge and redirect"]["page"].endswith("/blog/why-is-my-furnace-blowing-cold-air/")       # the stronger page is kept
assert by_action["Redirect a broken address to the page's new address"]["redirect_to"] == ex.HOME + "/blog/ac-not-cooling/"
assert by_action["Broken address with no redirect"]["redirect_to"] == ""
assert by_action["Already handled"]["tier"] == "no action" and "redirects to" in by_action["Already handled"]["evidence"]
assert {"Refresh", "Sharpen targeting", "Differentiate"} <= set(by_action)

# a search that names a place goes to that place's page
owners = {(a["search"], a["assign_to"].replace(ex.HOME, "")) for a in read("keyword_assignments.csv")}
assert ("furnace repair columbus", "/furnace-repair-columbus/") in owners and ("furnace repair dayton", "/furnace-repair-dayton/") in owners

# simulated data is labeled wherever a person reads the result, and a real site's report carries no such label
report, summary = (site / "report.html").read_text(), (site / "run_summary.md").read_text()
assert "Simulated data." in report and "data: simulated" in report.lower() and "**Simulated data.**" in summary
assert run_site.shown(site / "report.html") in summary and "example/data/" not in summary      # outside the repo, paths are not shortened to repo paths
(site / "SIMULATED.txt").unlink()
assert "imulated" not in build_report.build(ex.SITE, data).read_text()

# if the example has been built in this repo, its output shows no path from the machine that built it
saved = pathlib.Path(ex.HERE) / "data" / ex.SITE / "run_summary.md"
if saved.exists():
    assert "example/data/northside-hvac.example/report.html" in saved.read_text() and "/Users/" not in saved.read_text() and "/home/" not in saved.read_text()
print("ALL TESTS PASSED")
