#!/usr/bin/env python3
"""Fetch the text of pages that compete or have decayed, so their content can be compared.

Usage:  python3 fetch_content.py example.com
Why:    titles and keywords can't show that two pages repeat the same paragraphs. This saves each
        page's headings and paragraphs so recommend.py can measure how much text two pages share.
Reads:  ~/openclaw/data/<site>/analysis/pairs_judged.csv, pages.csv, url_status.csv (if present)
Writes: ~/openclaw/data/<site>/content.json   {url: {title, headings, paragraphs, word_count}}
No API cost. One request per page to the site itself, one page every half second.
Text that repeats across many of the site's pages (menus, footers, sign-up boxes) is removed.
"""
import collections, csv, html.parser, json, os, pathlib, re, sys, time, urllib.request

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
SKIP_TAGS = {"script", "style", "nav", "header", "footer", "form", "aside", "noscript", "svg", "button", "select"}
BLOCK_TAGS = {"h1", "h2", "h3", "p", "li"}
BOILERPLATE_SHARE = 0.25     # a block on more than this share of pages (and at least 3 pages) is site furniture
PAUSE_SECONDS = 0.5

clean = lambda text: re.sub(r"\s+", " ", text).strip()
norm = lambda text: re.sub(r"[^a-z0-9 ]+", "", clean(text).lower())


class Extractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.block, self.buffer, self.in_title = 0, None, [], False
        self.title, self.blocks = "", []           # blocks: [(tag, text)]

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in BLOCK_TAGS and not self.skip and self.block is None:
            self.block, self.buffer = tag, []

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif tag == self.block:
            text = clean("".join(self.buffer))
            if text:
                self.blocks.append((tag, text))
            self.block = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif self.block and not self.skip:
            self.buffer.append(data)


def extract(page_html):
    parser = Extractor()
    parser.feed(page_html)
    return clean(parser.title), parser.blocks


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def urls_to_fetch(folder):
    urls = []
    def add(url):
        if url and url not in urls:
            urls.append(url)
    pairs = folder / "pairs_judged.csv"
    if pairs.exists():
        for row in csv.DictReader(pairs.open()):
            add(row["page_a"]); add(row["page_b"])
    for row in csv.DictReader((folder / "pages.csv").open()):
        if row.get("status") in ("decayed", "watch"):
            add(row["url"])
    status = folder / "url_status.csv"
    moved = {r["url"] for r in csv.DictReader(status.open()) if str(r["status_code"]) != "200"} if status.exists() else set()
    return [u for u in urls if u not in moved]


def run(domain, data_dir=DATA_DIR, fetch=download, pause=PAUSE_SECONDS):
    urls = urls_to_fetch(data_dir / domain / "analysis")
    raw, failed = {}, []
    for number, url in enumerate(urls, 1):
        try:
            raw[url] = extract(fetch(url))
        except Exception as error:
            failed.append((url, type(error).__name__))
        print(f"\r  {number}/{len(urls)} fetched", end="", flush=True)
        time.sleep(pause)
    print()
    seen_on = collections.Counter()
    for _, blocks in raw.values():
        for key in {norm(text) for _, text in blocks}:
            seen_on[key] += 1
    limit = max(3, BOILERPLATE_SHARE * len(raw))
    content = {}
    for url, (title, blocks) in raw.items():
        kept = [(tag, text) for tag, text in blocks if seen_on[norm(text)] < limit]
        paragraphs = [text for tag, text in kept if tag in ("p", "li")]
        content[url] = {"title": title, "headings": [[tag, text] for tag, text in kept if tag.startswith("h")],
                        "paragraphs": paragraphs, "word_count": sum(len(p.split()) for p in paragraphs)}
    (data_dir / domain / "content.json").write_text(json.dumps(content, indent=1))
    return content, failed


if __name__ == "__main__":
    for domain in sys.argv[1:] or sys.exit(__doc__):
        content, failed = run(domain)
        words = sorted(c["word_count"] for c in content.values())
        middle = words[len(words) // 2] if words else 0
        print(f"{domain}: {len(content)} pages saved (typical page {middle} words), {len(failed)} failed. "
              f"Saved in {DATA_DIR / domain / 'content.json'}")
        for url, why in failed:
            print(f"  failed: {url} ({why})")
