#!/usr/bin/env python3
"""Check every page's live address: does it load, redirect, or return an error?

Usage:  python3 check_urls.py example.com
Why:    ranking data lags the live site. A page the data says is competing may already redirect
        somewhere else. This records what each URL does today so recommendations skip work already done.
Reads:  ~/openclaw/data/<site>/analysis/pages.csv
Writes: ~/openclaw/data/<site>/analysis/url_status.csv   (url, status_code, redirects_to, checked_at)
No API cost. It requests each page once from the site itself, one page every half second.
"""
import csv, datetime, os, pathlib, sys, time, urllib.error, urllib.request

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
PAUSE_SECONDS = 0.5


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                      # report the redirect instead of following it


def check(url, opener=None):
    """Returns (status_code, redirects_to). One request, redirects not followed."""
    opener = opener or urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, ""
    except urllib.error.HTTPError as error:
        target = error.headers.get("Location", "") if error.code in (301, 302, 303, 307, 308) else ""
        if target.startswith("/"):
            target = url.split("://", 1)[0] + "://" + url.split("://", 1)[1].split("/", 1)[0] + target
        return error.code, target
    except Exception as error:           # DNS failure, timeout, TLS problem
        return f"error: {type(error).__name__}", ""


def run(domain, data_dir=DATA_DIR, opener=None, pause=PAUSE_SECONDS):
    folder = data_dir / domain / "analysis"
    urls = [row["url"] for row in csv.DictReader((folder / "pages.csv").open())]
    now = datetime.datetime.now().isoformat(timespec="seconds")
    rows = []
    for number, url in enumerate(urls, 1):
        code, target = check(url, opener)
        rows.append({"url": url, "status_code": code, "redirects_to": target, "checked_at": now})
        print(f"\r  {number}/{len(urls)} checked", end="", flush=True)
        time.sleep(pause)
    print()
    with (folder / "url_status.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["url", "status_code", "redirects_to", "checked_at"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    for domain in sys.argv[1:] or sys.exit(__doc__):
        rows = run(domain)
        ok = sum(1 for r in rows if str(r["status_code"]) == "200")
        redirects = sum(1 for r in rows if r["redirects_to"])
        other = len(rows) - ok - redirects
        print(f"{domain}: {len(rows)} pages checked: {ok} load normally, {redirects} redirect, {other} other. "
              f"Saved in {DATA_DIR / domain / 'analysis' / 'url_status.csv'}")
