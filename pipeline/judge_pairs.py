#!/usr/bin/env python3
"""Ask Kev whether each pair of competing pages really covers the same topic.

Usage:  python3 judge_pairs.py --selftest          check Kev on pairs with known answers first
        python3 judge_pairs.py example.com          judge every competing pair for a site
Needs:  Kev running on this Mac (http://127.0.0.1:8009). No DataForSEO cost.
Reads:  ~/openclaw/data/<site>/analysis/pairs.csv, pages.csv and ~/openclaw/data/<site>/keywords.csv
Writes: ~/openclaw/data/<site>/analysis/pairs_judged.csv   every pair with Kev's probabilities
        ~/openclaw/data/<site>/analysis/merge_groups.json  groups rebuilt from pairs Kev confirmed
        ~/openclaw/data/<site>/analysis/kev_log.jsonl      every request and reply, for audit

Keyword overlap alone over-groups (billing software and billable hours share words but are
different topics). Kev's same-topic probability decides which pairs stay together.

How the question is asked was chosen by experiment (kev_experiment.py, 15 pairs with clear
answers). Kev is asked twice per pair and the two probabilities are averaged:
  - with_searches: each page's title plus its top searches. Separates well, but leans towards
    "same" when two pages share searches, which every competing pair does.
  - titles_only:   the two titles alone. Not swayed by shared searches.
The thresholds below are starting values from those 15 pairs and need a larger hand-labeled set.
"""
import collections, csv, json, os, pathlib, re, sys, urllib.request

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
KEV_URL = os.environ.get("KEV_URL", "http://127.0.0.1:8009/v1/systemone")
SAME_TOPIC = 0.75     # at or above: merge candidate
UNSURE = 0.45         # between UNSURE and SAME_TOPIC: needs a person to review
TOP_SEARCHES = 8

SUBJECT_CRITERIA = {"true": "They are about the same subject", "false": "They are about different subjects"}


def kev(state, instructions, send=None, criteria=SUBJECT_CRITERIA):
    body = {"model": "kev-latest", "state": state,
            "questions": {"q": {"type": "noul", "instructions": instructions, "criteria": criteria}}}
    if send is None:
        request = urllib.request.Request(KEV_URL, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            reply = json.load(response)
    else:
        reply = send(body)
    value = ((reply.get("answers") or {}).get("q") or {}).get("noul")
    if not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise SystemExit(f"Kev returned no usable answer: {json.dumps(reply)[:300]}")
    return float(value), {"request": body, "reply": reply}


def describe(page):
    line = f"Title: {page['title']}"
    if page["top_searches"]:
        line += " | Top searches: " + ", ".join(page["top_searches"][:5])
    return line


def ask_kev(a, b, send=None):
    """Two differently worded questions, averaged. Returns the probabilities and both raw exchanges."""
    with_searches, log_1 = kev({"page_a": describe(a), "page_b": describe(b)},
                               "Are Page A and Page B about the same subject?", send)
    titles_only, log_2 = kev({"page_a": a["title"], "page_b": b["title"]},
                             "Are these two article titles about the same subject?", send)
    return {"same_topic": (with_searches + titles_only) / 2,
            "with_searches": with_searches, "titles_only": titles_only}, [log_1, log_2]


def same_address(a, b):
    """/a-guide/ and /a-guide// are one page at two addresses: decided by code, not Kev."""
    clean = lambda u: re.sub(r"/+", "/", u.split("://", 1)[-1].lower()).rstrip("/")
    return clean(a) == clean(b)


def same_title_apart_from_year(a, b):
    """'...Best Options in 2026' and '...Best Options in 2025' are one article republished: decided by code."""
    clean = lambda t: re.sub(r"[^a-z]+", " ", (t or "").lower()).strip()
    return bool(clean(a)) and clean(a) == clean(b)


def verdict_for(probability):
    if probability >= SAME_TOPIC:
        return "merge candidate"
    return "needs review" if probability >= UNSURE else "keep separate"


def page_state(url, pages, top):
    return {"title": pages.get(url, {}).get("title", ""), "top_searches": top.get(url, [])}


def judge_site(domain, data_dir=DATA_DIR, send=None):
    folder = data_dir / domain / "analysis"
    pairs = list(csv.DictReader((folder / "pairs.csv").open()))
    pages = {p["url"]: p for p in csv.DictReader((folder / "pages.csv").open())}
    live = collections.defaultdict(list)
    for row in csv.DictReader((data_dir / domain / "keywords.csv").open()):
        if row["is_lost"] != "True":
            live[row["url"]].append((float(row["etv"] or 0), row["keyword"]))
    top = {url: [kw for _, kw in sorted(rows, reverse=True)[:TOP_SEARCHES]] for url, rows in live.items()}

    judged, log = [], []
    for pair in pairs:
        a, b = pair["page_a"], pair["page_b"]
        state_a, state_b = page_state(a, pages, top), page_state(b, pages, top)
        certain = {"same_topic": 1.0, "with_searches": "", "titles_only": ""}
        if same_address(a, b):
            probabilities, source = certain, "code: same page, two addresses"
        elif same_title_apart_from_year(state_a["title"], state_b["title"]):
            probabilities, source = certain, "code: same title apart from the year"
        else:
            probabilities, exchanges = ask_kev(state_a, state_b, send)
            log.extend({"page_a": a, "page_b": b, **exchange} for exchange in exchanges)
            source = "kev"
        homepage = pair["involves_homepage"] == "True"
        verdict = verdict_for(probabilities["same_topic"])
        if homepage and verdict == "merge candidate":
            verdict = "needs review"            # never auto-suggest merging into or out of the homepage
        rounded = lambda v: round(v, 3) if isinstance(v, float) else v
        judged.append({**pair, "p_same_topic": rounded(probabilities["same_topic"]),
                       "p_with_searches": rounded(probabilities["with_searches"]),
                       "p_titles_only": rounded(probabilities["titles_only"]),
                       "verdict": verdict, "decided_by": source})

    # groups: pages joined by pairs Kev confirmed as the same topic (homepage never joins)
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for p in judged:
        if p["verdict"] == "merge candidate":
            parent[find(p["page_a"])] = find(p["page_b"])
    members = collections.defaultdict(set)
    for url in list(parent):
        members[find(url)].add(url)
    traffic = lambda u: float(pages.get(u, {}).get("traffic_before") or 0)
    groups = []
    for number, urls in enumerate(sorted(members.values(), key=lambda g: -sum(traffic(u) for u in g)), 1):
        inside = [p for p in judged if p["page_a"] in urls and p["page_b"] in urls and p["verdict"] == "merge candidate"]
        groups.append({"group": number, "pages": sorted(urls, key=lambda u: -traffic(u)),
                       "lowest_pair_confidence": min(p["p_same_topic"] for p in inside),
                       "pairs": [{"page_a": p["page_a"], "page_b": p["page_b"], "p_same_topic": p["p_same_topic"], "decided_by": p["decided_by"]} for p in inside]})

    with (folder / "pairs_judged.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(judged[0]) if judged else [])
        writer.writeheader()
        writer.writerows(judged)
    (folder / "merge_groups.json").write_text(json.dumps(groups, indent=1))
    (folder / "kev_log.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in log))
    return judged, groups, len(log)


SELFTEST = [   # made-up pairs where the right answer is not in doubt
    ("same", "Best Free Budgeting Apps", ["free budgeting apps", "budgeting app"],
             "The 7 Best Free Budgeting Apps for Beginners", ["best free budgeting apps", "budget apps for beginners"]),
    ("same", "How to Fix a Leaky Faucet: A Beginner's Guide", ["fix leaky faucet", "leaky faucet repair"],
             "Leaky Faucet Repair: Step-by-Step Instructions", ["how to repair a leaking faucet", "faucet repair steps"]),
    ("different", "The Best Accounting Software for Small Businesses", ["small business accounting software", "accounting software"],
                  "How Many Hours Do Nurses Work?", ["how many hours do nurses work", "nurse work hours"]),
    ("different", "How Restaurant Owners Get Paid", ["restaurant owner salary", "how do restaurant owners get paid"],
                  "How to Choose a Restaurant Name", ["restaurant name ideas", "naming a restaurant"]),
    ("different", "The Best Gifts for Teachers", ["gifts for teachers", "teacher gift ideas"],
                  "Email Marketing for Restaurants: The Complete Guide", ["email marketing for restaurants", "restaurant email marketing"]),
]


def selftest(send=None):
    print("Kev self-test: pairs with known answers\n")
    passed = 0
    for expected, title_a, searches_a, title_b, searches_b in SELFTEST:
        p = ask_kev({"title": title_a, "top_searches": searches_a},
                    {"title": title_b, "top_searches": searches_b}, send)[0]["same_topic"]
        ok = (p >= SAME_TOPIC) if expected == "same" else (p < UNSURE)
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  expected {expected:9s} same-topic {p:.2f}   {title_a[:38]}  |  {title_b[:38]}")
    print(f"\n{passed} of {len(SELFTEST)} passed. Merge candidate at {SAME_TOPIC:.2f} or above; keep separate below {UNSURE:.2f}.")
    return passed == len(SELFTEST)


if __name__ == "__main__":
    args = sys.argv[1:] or sys.exit(__doc__)
    try:
        if args == ["--selftest"]:
            sys.exit(0 if selftest() else 1)
        for domain in args:
            judged, groups, calls = judge_site(domain)
            counts = collections.Counter(p["verdict"] for p in judged)
            print(f"{domain}: {len(judged)} pairs judged ({calls} Kev calls): {dict(counts)}; "
                  f"{len(groups)} merge groups. Saved in {DATA_DIR / domain / 'analysis'}")
    except OSError as error:
        sys.exit(f"Could not reach Kev at {KEV_URL} ({error}). Start it with:\n"
                 "  cd ~/kev && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009")
