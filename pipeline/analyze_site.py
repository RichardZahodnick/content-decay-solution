#!/usr/bin/env python3
"""Decay scoring and cannibalization candidates for one site. No API calls, no cost.

Usage:  python3 analyze_site.py example.com
Reads:  ~/openclaw/data/<site>/keywords.csv   (from pull_site.py)
Writes: ~/openclaw/data/<site>/analysis/pages.csv     one row per page, with decay status
        ~/openclaw/data/<site>/analysis/pairs.csv     page pairs that compete for the same searches
        ~/openclaw/data/<site>/analysis/clusters.json groups of competing pages
        ~/openclaw/data/<site>/analysis/summary.json  site totals and the thresholds used

DEFINITION OF "DECAYED" (v1). A page is decayed when all three are true:
  1. It mattered:        estimated traffic at the previous check >= MIN_TRAFFIC_BEFORE visits/month
  2. It fell:            estimated traffic is down by DROP_PCT or more since the previous check
  3. It fell on its own: its change is at least RELATIVE_GAP points worse than the whole site's change
"Estimated traffic" = search volume x click-through rate for the ranking position (DataForSEO's
model). The comparison window is each keyword's previous check to its latest check (about 10 weeks).
Keywords lost more than WINDOW_DAYS before the newest check are older losses: they are counted
separately (keywords_lost_earlier) and left out of the before/now comparison.
"""
import collections, csv, datetime, json, os, pathlib, re, statistics, sys

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
MIN_TRAFFIC_BEFORE = 10.0   # visits/month; below this a page is "too small to judge"
DROP_PCT = -0.30            # decayed: down 30% or more
WATCH_PCT = -0.15           # watch: down 15-30%
RELATIVE_GAP = 0.15         # and at least 15 points worse than the site as a whole
GROW_PCT = 0.15
WINDOW_DAYS = 150           # losses older than this are outside the comparison window
MIN_SHARED_SEARCHES = 2     # a pair needs this many shared searches (or one URL swap) to count
STOPWORDS = {"a", "an", "the", "for", "of", "to", "in", "on", "and", "or", "is", "are", "do", "does",
             "how", "what", "my", "your", "with", "at", "by", "from", "vs", "i", "you", "it"}

num = lambda value: float(value or 0)
yes = lambda value: str(value) == "True"


def search_key(text):
    """'SEO for lawyers' and 'lawyers seo' become the same key: 'lawyer seo'."""
    words = []
    for word in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return " ".join(sorted(set(words)))


def click_rates(rows):
    """Click-through rate by position, measured from the site's own live rows."""
    samples = collections.defaultdict(list)
    for row in rows:
        if not yes(row["is_lost"]) and num(row["search_volume"]) > 0 and num(row["etv"]) > 0:
            samples[int(num(row["rank"]))].append(num(row["etv"]) / num(row["search_volume"]))
    known = {position: statistics.median(values) for position, values in samples.items()}

    def rate(position):
        if not known:
            return 0.0
        position = max(1, int(position))
        if position in known:
            return known[position]
        lower = [p for p in known if p < position]
        higher = [p for p in known if p > position]
        if lower and higher:                       # between two known positions: interpolate
            a, b = max(lower), min(higher)
            return known[a] + (known[b] - known[a]) * (position - a) / (b - a)
        return known[max(lower)] if lower else known[min(higher)]
    return rate


def traffic_before_and_now(row, rate):
    """Estimated monthly visits from one keyword at the previous check and at the latest check."""
    now = 0.0 if yes(row["is_lost"]) else num(row["etv"])
    if yes(row["is_lost"]):
        return num(row["etv"]), now, int(num(row["rank"]))          # last position it held
    if not row["previous_rank_absolute"]:
        return 0.0, now, None                                        # new keyword
    offset = int(num(row["rank_absolute"])) - int(num(row["rank"]))  # SERP features above the result
    previous = max(1, int(num(row["previous_rank_absolute"])) - offset)
    return num(row["search_volume"]) * rate(previous), now, previous


def status_for(before, now, site_change):
    if before < MIN_TRAFFIC_BEFORE:
        return "new or growing" if now >= MIN_TRAFFIC_BEFORE else "too small to judge"
    change = now / before - 1
    if change <= DROP_PCT and change <= site_change - RELATIVE_GAP:
        return "decayed"
    if change <= WATCH_PCT and change <= site_change - RELATIVE_GAP:
        return "watch"
    if change <= DROP_PCT:
        return "fell with the site"
    return "growing" if change >= GROW_PCT else "stable"


def analyze(rows, domain):
    rate = click_rates(rows)
    has_dates = bool(rows) and "dated" in rows[0]
    dates = [row.get("serp_checked") for row in rows if row.get("serp_checked")]
    newest = max(dates) if dates else ""
    cutoff = (datetime.date.fromisoformat(newest) - datetime.timedelta(days=WINDOW_DAYS)).isoformat() if newest else ""
    pages = collections.defaultdict(lambda: {
        "title": "", "keywords_now": 0, "keywords_before": 0, "keywords_lost": 0, "keywords_lost_earlier": 0, "keywords_new": 0,
        "top10_now": 0, "top10_before": 0, "traffic_now": 0.0, "traffic_before": 0.0,
        "referring_domains": 0, "page_rank": 0, "top_keyword": "", "_top_volume": -1.0, "_rows": 0, "_dated": 0})
    keys = collections.defaultdict(lambda: collections.defaultdict(list))   # search key -> url -> rows
    exact = collections.defaultdict(dict)                                   # keyword -> url -> row

    for row in rows:
        url, page = row["url"], pages[row["url"]]
        before, now, previous = traffic_before_and_now(row, rate)
        lost = yes(row["is_lost"])
        page["title"] = row["title"] or page["title"]
        page["_rows"] += 1
        page["_dated"] += yes(row.get("dated"))
        page["referring_domains"] = max(page["referring_domains"], int(num(row["referring_domains"])))
        page["page_rank"] = max(page["page_rank"], int(num(row["page_rank"])))
        for key in {search_key(row["keyword"]), search_key(row["core_keyword"])} - {""}:
            keys[key][url].append(row)
        exact[row["keyword"]][url] = row
        if lost and cutoff and (row.get("serp_checked") or cutoff) < cutoff:
            page["keywords_lost_earlier"] += 1                       # outside the comparison window
            continue
        page["traffic_before"] += before
        page["traffic_now"] += now
        page["keywords_lost"] += lost
        page["keywords_new"] += (not lost and previous is None)
        page["keywords_now"] += not lost
        page["keywords_before"] += previous is not None
        page["top10_now"] += (not lost and num(row["rank"]) <= 10)
        page["top10_before"] += (previous is not None and previous <= 10)
        if not lost and num(row["search_volume"]) > page["_top_volume"] and num(row["rank"]) <= 20:
            page["_top_volume"], page["top_keyword"] = num(row["search_volume"]), row["keyword"]

    total_before = sum(p["traffic_before"] for p in pages.values())
    total_now = sum(p["traffic_now"] for p in pages.values())
    site_change = (total_now / total_before - 1) if total_before else 0.0

    # --- pairs of pages that compete for the same searches ---
    pairs = collections.defaultdict(lambda: {"searches": {}, "swaps": []})
    for key, by_url in keys.items():
        urls = sorted(by_url)
        volume = max(num(r["search_volume"]) for rs in by_url.values() for r in rs)
        for i, a in enumerate(urls):
            for b in urls[i + 1:]:
                pairs[(a, b)]["searches"][key] = volume
    for keyword, by_url in exact.items():
        urls = sorted(by_url)
        for i, a in enumerate(urls):
            for b in urls[i + 1:]:
                if yes(by_url[a]["is_lost"]) != yes(by_url[b]["is_lost"]):
                    loser, winner = (a, b) if yes(by_url[a]["is_lost"]) else (b, a)
                    pairs[(a, b)]["swaps"].append({
                        "keyword": keyword, "volume": int(num(by_url[a]["search_volume"])),
                        "held_by": loser, "held_rank": int(num(by_url[loser]["rank"])),
                        "now_by": winner, "now_rank": int(num(by_url[winner]["rank"]))})
    page_keys = collections.defaultdict(set)
    for key, by_url in keys.items():
        for url in by_url:
            page_keys[url].add(key)

    home = {f"https://{domain}/", f"https://www.{domain}/"}
    pair_rows = []
    for (a, b), info in pairs.items():
        shared = len(info["searches"])
        if shared < MIN_SHARED_SEARCHES and not info["swaps"]:
            continue
        top = sorted(info["searches"].items(), key=lambda kv: -kv[1])[:5]
        pair_rows.append({
            "page_a": a, "page_b": b, "shared_searches": shared,
            "shared_volume": int(sum(info["searches"].values())),
            "overlap_of_smaller_page": round(shared / max(1, min(len(page_keys[a]), len(page_keys[b]))), 2),
            "url_swaps": len(info["swaps"]),
            "swapped_volume": sum(s["volume"] for s in info["swaps"]),
            "involves_homepage": a in home or b in home,
            "top_shared_searches": "; ".join(f"{k} ({int(v)})" for k, v in top),
            "_swaps": info["swaps"]})
    pair_rows.sort(key=lambda p: (-p["url_swaps"], -p["shared_volume"]))

    # --- clusters: connected groups of competing pages (homepage links don't join groups) ---
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for p in pair_rows:
        if not p["involves_homepage"]:
            parent[find(p["page_a"])] = find(p["page_b"])
    groups = collections.defaultdict(set)
    for url in list(parent):
        groups[find(url)].add(url)
    in_cluster = {}
    clusters = []
    for number, members in enumerate(sorted(groups.values(), key=lambda g: -sum(pages[u]["traffic_before"] for u in g)), 1):
        for url in members:
            in_cluster[url] = number
        inside = [p for p in pair_rows if p["page_a"] in members and p["page_b"] in members]
        clusters.append({
            "cluster": number, "pages": sorted(members, key=lambda u: -pages[u]["traffic_now"]),
            "shared_volume": sum(p["shared_volume"] for p in inside),
            "url_swaps": [s for p in inside for s in p["_swaps"]]})

    page_rows = []
    for url, page in pages.items():
        before, now = page["traffic_before"], page["traffic_now"]
        page_rows.append({
            "url": url, "title": page["title"], "status": status_for(before, now, site_change),
            "traffic_before": round(before, 1), "traffic_now": round(now, 1),
            "traffic_change": round(now - before, 1),
            "change_pct": round(now / before - 1, 3) if before else "",
            "keywords_before": page["keywords_before"], "keywords_now": page["keywords_now"],
            "keywords_lost": page["keywords_lost"], "keywords_lost_earlier": page["keywords_lost_earlier"], "keywords_new": page["keywords_new"],
            "top10_before": page["top10_before"], "top10_now": page["top10_now"],
            "referring_domains": page["referring_domains"], "page_rank": page["page_rank"],
            "cluster": in_cluster.get(url, ""), "top_keyword": page["top_keyword"],
            # share of this page's search results that Google shows with a publish date; "" if the data lacks the field
            "dated_share": round(page["_dated"] / page["_rows"], 2) if has_dates else ""})
    page_rows.sort(key=lambda p: p["traffic_change"])

    counts = collections.Counter(p["status"] for p in page_rows)
    summary = {
        "site": domain, "pages": len(page_rows), "keyword_rows": len(rows),
        "traffic_before": round(total_before), "traffic_now": round(total_now),
        "site_change_pct": round(site_change, 3), "newest_check": newest, "window_start": cutoff, "status_counts": dict(counts),
        "competing_pairs": len(pair_rows), "clusters": len(clusters),
        "pages_in_clusters": len(in_cluster),
        "thresholds": {"MIN_TRAFFIC_BEFORE": MIN_TRAFFIC_BEFORE, "DROP_PCT": DROP_PCT,
                       "WATCH_PCT": WATCH_PCT, "RELATIVE_GAP": RELATIVE_GAP, "WINDOW_DAYS": WINDOW_DAYS,
                       "MIN_SHARED_SEARCHES": MIN_SHARED_SEARCHES}}
    return page_rows, pair_rows, clusters, summary


def save(domain, page_rows, pair_rows, clusters, summary, data_dir=DATA_DIR):
    out = data_dir / domain / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    def write(name, rows):
        columns = [c for c in rows[0] if not c.startswith("_")] if rows else []
        with (out / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    write("pages.csv", page_rows)
    write("pairs.csv", pair_rows)
    (out / "clusters.json").write_text(json.dumps(clusters, indent=1))
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return out


if __name__ == "__main__":
    for domain in sys.argv[1:] or sys.exit(__doc__):
        rows = list(csv.DictReader((DATA_DIR / domain / "keywords.csv").open()))
        result = analyze(rows, domain)
        out = save(domain, *result)
        s = result[3]
        print(f"{domain}: site traffic {s['traffic_before']} -> {s['traffic_now']} ({s['site_change_pct']:+.0%}); "
              f"{s['status_counts']}; {s['competing_pairs']} competing pairs in {s['clusters']} clusters. Saved in {out}")
