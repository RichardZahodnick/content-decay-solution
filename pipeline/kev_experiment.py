#!/usr/bin/env python3
"""Which way of asking Kev "are these two pages the same topic?" separates best?

Usage:  python3 kev_experiment.py
Runs several question wordings over page pairs whose answer is clear, prints a comparison, and saves every
probability to ~/openclaw/data/experiments/kev_same_topic.json. Needs Kev running locally. No DataForSEO cost.

Reads:  ~/openclaw/data/experiments/same_topic_pairs.csv   the pairs, picked by hand from a site already analyzed:
            expected,site,path_a,path_b
            same,example.com,/billing-software/,/billing-software-2025/
            different,example.com,/billing-software/,/office-chair-reviews/
            different (hard),example.com,/billing-software/,/how-to-write-an-invoice/
        "same" pairs should score high and every other pair low; "different (hard)" marks related topics that
        still should not be merged. The pairs are real pages of a real site, so the file is not in this repo.
        ~/openclaw/data/<site>/analysis/pages.csv and keywords.csv for each site named in the file.

The run that chose the wording in judge_pairs.py used 15 pairs from one site: 6 same, 7 different, 2 hard.
"""
import collections, csv, json, os, pathlib, sys, urllib.request

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
KEV_URL = os.environ.get("KEV_URL", "http://127.0.0.1:8009/v1/systemone")
PAIRS_FILE = "same_topic_pairs.csv"


def kev(state, question, send=None):
    body = {"model": "kev-latest", "state": state, "questions": {"q": {"type": "noul", **question}}}
    if send is None:
        request = urllib.request.Request(KEV_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.load(response)
    else:
        reply = send(body)
    value = ((reply.get("answers") or {}).get("q") or {}).get("noul")
    if not isinstance(value, (int, float)):
        raise SystemExit(f"Kev returned no usable answer: {json.dumps(reply)[:300]}")
    return float(value)


def text(page, searches=True):
    line = f"Title: {page['title']}"
    if searches and page["searches"]:
        line += " | Top searches: " + ", ".join(page["searches"][:5])
    return line


def nested(a, b, send):
    state = {"page_a": {"title": a["title"], "top_searches": a["searches"]},
             "page_b": {"title": b["title"], "top_searches": b["searches"]}}
    return kev(state, {"instructions": "Do page_a and page_b cover the same topic for the same reader, so that one "
                       "combined page could satisfy the searches that both pages rank for?",
                       "criteria": {"true": "Both pages answer the same question or cover the same subject for the same audience",
                                    "false": "The pages cover different subjects or serve different needs, even if some words overlap"}}, send)

def flat(a, b, send):
    return kev({"page_a": text(a), "page_b": text(b)},
               {"instructions": "Are Page A and Page B about the same subject?",
                "criteria": {"true": "They are about the same subject", "false": "They are about different subjects"}}, send)

def titles(a, b, send):
    return kev({"page_a": a["title"], "page_b": b["title"]},
               {"instructions": "Are these two article titles about the same subject?",
                "criteria": {"true": "They are about the same subject", "false": "They are about different subjects"}}, send)

def editor(a, b, send):
    return kev({"article_1": text(a), "article_2": text(b)},
               {"instructions": "Do these two articles overlap so much that a website should keep only one of them?",
                "criteria": {"true": "Yes, they cover the same subject and one article would be enough",
                             "false": "No, they cover different subjects and both are needed"}}, send)

def search_fit(a, b, send):
    """Would each page be a good result for the other page's main search? Average of both directions."""
    def one(source, target):
        query = source["searches"][0] if source["searches"] else source["title"]
        return kev({"search_query": query, "page_title": target["title"]},
                   {"instructions": "Would this page be a good result for this search query?",
                    "criteria": {"true": "The page directly answers the search query",
                                 "false": "The page is about something else"}}, send)
    return (one(a, b) + one(b, a)) / 2

VARIANTS = {"A nested": nested, "B flat text": flat, "C titles only": titles,
            "D editor: keep one?": editor, "E search fit": search_fit}


def load_labeled(data_dir=DATA_DIR):
    """[(expected, address of page a, address of page b)] from the pairs file."""
    with (data_dir / "experiments" / PAIRS_FILE).open() as handle:
        return [(row["expected"], f"https://{row['site']}{row['path_a']}", f"https://{row['site']}{row['path_b']}") for row in csv.DictReader(handle)]


def load_pages(sites, data_dir=DATA_DIR):
    pages, live = {}, collections.defaultdict(list)
    for site in sites:
        for p in csv.DictReader((data_dir / site / "analysis" / "pages.csv").open()):
            pages[p["url"]] = {"title": p["title"], "searches": []}
        for row in csv.DictReader((data_dir / site / "keywords.csv").open()):
            if row["is_lost"] != "True":
                live[row["url"]].append((float(row["etv"] or 0), row["keyword"]))
    for url, rows in live.items():
        pages[url]["searches"] = [kw for _, kw in sorted(rows, reverse=True)[:8]]
    return pages


def run(pages, labeled, send=None):
    results = []
    path = lambda url: "/" + url.split("://", 1)[-1].partition("/")[2]
    for expected, url_a, url_b in labeled:
        a, b = pages[url_a], pages[url_b]
        results.append({"expected": expected, "page_a": path(url_a), "page_b": path(url_b),
                        "scores": {name: round(fn(a, b, send), 3) for name, fn in VARIANTS.items()}})
    summary = {}
    for name in VARIANTS:
        same = [r["scores"][name] for r in results if r["expected"] == "same"]
        different = [r["scores"][name] for r in results if r["expected"] != "same"]
        ordered = sum(s > d for s in same for d in different) / (len(same) * len(different))
        summary[name] = {"lowest_same": min(same), "highest_different": max(different),
                         "gap": round(min(same) - max(different), 3), "pairs_ordered_correctly": round(ordered, 3)}
    return results, summary


if __name__ == "__main__":
    if not (DATA_DIR / "experiments" / PAIRS_FILE).exists():
        sys.exit(__doc__)
    labeled = load_labeled()
    try:
        results, summary = run(load_pages({url.split("/")[2] for _, a, b in labeled for url in (a, b)}), labeled)
    except OSError as error:
        sys.exit(f"Could not reach Kev at {KEV_URL} ({error}).")
    out = DATA_DIR / "experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "kev_same_topic.json").write_text(json.dumps({"results": results, "summary": summary}, indent=1))
    names = list(VARIANTS)
    print("expected           " + "  ".join(n[:1] for n in names) .replace("  ", "      ") + "   pair")
    for r in results:
        print(f"{r['expected']:17s} " + "  ".join(f"{r['scores'][n]:.2f}" for n in names) + f"   {r['page_a'][:28]} | {r['page_b'][:28]}")
    print("\nwording                 lowest same  highest different   gap    ordered correctly")
    for name, s in summary.items():
        print(f"{name:22s}  {s['lowest_same']:.2f}         {s['highest_different']:.2f}               {s['gap']:+.2f}   {s['pairs_ordered_correctly']:.0%}")
    print(f"\nA positive gap means every 'same' pair scored above every 'different' pair. Saved in {out}")
