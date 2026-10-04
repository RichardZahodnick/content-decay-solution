import csv, json, pathlib, tempfile, fetch_content as f

HTML = """<html><head><title> Partner Pay | Site </title><style>p{color:red}</style></head><body>
<nav><ul><li>Home</li><li>Blog</li></ul></nav><header><p>Call us today</p></header>
<h1>How Do Partners Get Paid?</h1><p>Partners share <b>profits</b>&amp; losses.</p>
<h2>What Is a Partner?</h2><p>A partner   owns part of the firm.</p><ul><li>Equity partners</li><li><p>Nested para</p> tail</li></ul>
<script>var x = "<p>not text</p>";</script><form><p>Your email</p></form>
<p></p><p>Subscribe to our newsletter</p><footer><p>Copyright</p></footer></body></html>"""
title, blocks = f.extract(HTML)
assert title == "Partner Pay | Site"
assert blocks == [("h1", "How Do Partners Get Paid?"), ("p", "Partners share profits& losses."), ("h2", "What Is a Partner?"),
                  ("p", "A partner owns part of the firm."), ("li", "Equity partners"), ("li", "Nested para tail"), ("p", "Subscribe to our newsletter")], blocks

U = lambda p: f"https://x.com{p}"
root = pathlib.Path(tempfile.mkdtemp()); folder = root / "x.com" / "analysis"; folder.mkdir(parents=True)
(folder / "pairs_judged.csv").write_text(f"page_a,page_b\n{U('/a/')},{U('/b/')}\n{U('/b/')},{U('/old/')}\n")
(folder / "pages.csv").write_text(f"url,status\n{U('/a/')},stable\n{U('/c/')},decayed\n{U('/d/')},watch\n{U('/e/')},stable\n{U('/bad/')},decayed\n")
(folder / "url_status.csv").write_text(f"url,status_code,redirects_to\n{U('/old/')},301,{U('/a/')}\n{U('/a/')},200,\n")
assert f.urls_to_fetch(folder) == [U("/a/"), U("/b/"), U("/c/"), U("/d/"), U("/bad/")]        # pairs first, then decayed; redirected and stable-unpaired skipped
page = lambda body: f"<html><title>T</title><body><p>Subscribe to our newsletter</p><h2>Related posts</h2>{body}</body></html>"
pages = {U("/a/"): page("<h2>What Is a Partner?</h2><p>A partner owns part of the firm and shares in its profits every year.</p><p>Only on A.</p>"),
         U("/b/"): page("<h2>What Is a Partner?</h2><p>A partner owns part of the firm and shares in its profits every year.</p><p>Only on B.</p>"),
         U("/c/"): page("<p>Page C text here.</p>"), U("/d/"): page("<p>Page D text here.</p>")}
def fake(url):
    if url not in pages: raise TimeoutError("slow")
    return pages[url]
content, failed = f.run("x.com", root, fake, pause=0)
assert failed == [(U("/bad/"), "TimeoutError")] and set(content) == set(pages)
a = content[U("/a/")]
assert a["paragraphs"] == ["A partner owns part of the firm and shares in its profits every year.", "Only on A."]   # newsletter line (on 4 of 4 pages) removed
assert a["headings"] == [["h2", "What Is a Partner?"]] and a["word_count"] == 17                                    # "Related posts" removed; shared-by-2 heading kept
assert json.loads((root / "x.com" / "content.json").read_text()) == content
print("ALL TESTS PASSED")
