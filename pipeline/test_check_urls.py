import csv, email.message, io, pathlib, tempfile, urllib.error, check_urls as c

class FakeOpener:
    def open(self, request, timeout=None):
        url = request.full_url
        assert request.get_header("User-agent").startswith("Mozilla") and request.get_method() == "GET"
        headers = email.message.Message()
        if url.endswith("/ok/"):
            class R:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return R()
        if url.endswith("/moved/"):
            headers["Location"] = "https://x.com/ok/"; raise urllib.error.HTTPError(url, 301, "Moved", headers, io.BytesIO())
        if url.endswith("/relative/"):
            headers["Location"] = "/ok/"; raise urllib.error.HTTPError(url, 302, "Found", headers, io.BytesIO())
        if url.endswith("/missing/"):
            raise urllib.error.HTTPError(url, 404, "Not Found", headers, io.BytesIO())
        raise TimeoutError("slow")

o = FakeOpener()
assert c.check("https://x.com/ok/", o) == (200, "")
assert c.check("https://x.com/moved/", o) == (301, "https://x.com/ok/")
assert c.check("https://x.com/relative/", o) == (302, "https://x.com/ok/")       # relative Location made absolute
assert c.check("https://x.com/missing/", o) == (404, "")
assert c.check("https://x.com/slow/", o) == ("error: TimeoutError", "")
root = pathlib.Path(tempfile.mkdtemp()); folder = root / "x.com" / "analysis"; folder.mkdir(parents=True)
(folder / "pages.csv").write_text("url,title\nhttps://x.com/ok/,a\nhttps://x.com/moved/,b\nhttps://x.com/missing/,c\n")
rows = c.run("x.com", root, o, pause=0)
saved = list(csv.DictReader((folder / "url_status.csv").open()))
assert [(r["status_code"], r["redirects_to"]) for r in saved] == [("200", ""), ("301", "https://x.com/ok/"), ("404", "")] and len(rows) == 3
# the saved file is what recommend.py reads
import recommend
status = {s["url"]: s for s in saved}
assert recommend.live_problem("https://x.com/moved/", status) == "redirects to https://x.com/ok/"
assert recommend.live_problem("https://x.com/missing/", status) == "returns 404" and recommend.live_problem("https://x.com/ok/", status) == ""
assert recommend.live_problem("https://x.com/never-checked/", status) == ""
print("ALL TESTS PASSED")
