#!/usr/bin/env python3
"""Ask Kev which page each shared search fits best, for the pairs to be differentiated.

Usage:  python3 score_keyword_fit.py example.com
Needs:  Kev running on this Mac. No DataForSEO cost. Run recommend.py first.
Reads:  ~/openclaw/data/<site>/analysis/keyword_assignments.csv, pages.csv
Writes: ~/openclaw/data/<site>/analysis/keyword_fit.csv   (url, search, fit)
Then re-runs recommend.py so keyword_assignments.csv uses topical fit instead of today's ranking.

Why: giving a search to whichever page ranks higher today can entrench the wrong page. Kev is asked,
for each page separately, "would this page be a good result for this search?" This wording has not
been checked against hand labels yet.
"""
import csv, os, pathlib, sys
import judge_pairs, recommend

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
FIT_CRITERIA = {"true": "The page directly answers the search query", "false": "The page is about something else"}


def score_site(domain, data_dir=DATA_DIR, send=None):
    folder = data_dir / domain / "analysis"
    titles = {p["url"]: p["title"] for p in csv.DictReader((folder / "pages.csv").open())}
    needed = []
    for row in recommend.read(folder / "keyword_assignments.csv"):
        for url in (row["page_a"], row["page_b"]):
            if (url, row["search"]) not in needed:
                needed.append((url, row["search"]))
    fits = []
    for url, search in needed:
        fit, _ = judge_pairs.kev({"search_query": search, "page_title": titles.get(url, "")},
                                 "Would this page be a good result for this search query?", send, FIT_CRITERIA)
        fits.append({"url": url, "search": search, "fit": round(fit, 3)})
    with (folder / "keyword_fit.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["url", "search", "fit"])
        writer.writeheader()
        writer.writerows(fits)
    assignments = recommend.run(domain, data_dir)[2]
    return fits, assignments


if __name__ == "__main__":
    try:
        for domain in sys.argv[1:] or sys.exit(__doc__):
            fits, assignments = score_site(domain)
            by_fit = sum(1 for a in assignments if a["why"] == "better topical fit")
            print(f"{domain}: {len(fits)} Kev calls; {len(assignments)} shared searches assigned, "
                  f"{by_fit} by topical fit and {len(assignments) - by_fit} by ranking (fit too close to call)")
    except OSError as error:
        sys.exit(f"Could not reach Kev at {judge_pairs.KEV_URL} ({error}). Start it with:\n"
                 "  cd ~/kev && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009")
