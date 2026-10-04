#!/usr/bin/env python3
"""Full data pull for one or more sites: every ranked keyword (with the page that
ranks for it) and the full monthly history DataForSEO holds.

Usage:  python3 pull_site.py example.com another-example.com
        python3 pull_site.py --reflatten example.com     rebuild keywords.csv from the saved replies (no API call, no cost)
Output: ~/openclaw/data/raw/<site>/   raw API replies (kept so nothing is paid for twice)
        ~/openclaw/data/<site>/keywords.csv   one row per keyword + ranking page
        ~/openclaw/data/<site>/history.csv    one row per month, whole site
"""
import csv, json, os, pathlib, sys
import sizing_check as dfs

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
PAGE_SIZE, MAX_ITEMS, HISTORY_FROM = 1000, 10000, "2020-10-01"

KEYWORD_COLUMNS = [
    "keyword", "core_keyword", "search_volume", "intent", "difficulty", "url", "title",
    "rank", "rank_absolute", "previous_rank_absolute", "is_new", "is_up", "is_down", "is_lost",
    "etv", "referring_domains", "page_rank", "ai_overview_on_serp", "serp_checked", "previous_check", "dated"]


def flatten(item):
    data = item.get("keyword_data") or {}
    element = item.get("ranked_serp_element") or {}
    serp = element.get("serp_item") or {}
    changes = serp.get("rank_changes") or {}
    return {
        "keyword": data.get("keyword"),
        "core_keyword": (data.get("keyword_properties") or {}).get("core_keyword"),
        "search_volume": (data.get("keyword_info") or {}).get("search_volume"),
        "intent": (data.get("search_intent_info") or {}).get("main_intent"),
        "difficulty": (data.get("keyword_properties") or {}).get("keyword_difficulty"),
        "url": serp.get("url"), "title": serp.get("title"),
        "rank": serp.get("rank_group"), "rank_absolute": serp.get("rank_absolute"),
        "previous_rank_absolute": changes.get("previous_rank_absolute"),
        "is_new": changes.get("is_new"), "is_up": changes.get("is_up"), "is_down": changes.get("is_down"),
        "is_lost": element.get("is_lost"),
        "etv": serp.get("etv"),
        "referring_domains": (serp.get("backlinks_info") or {}).get("referring_domains"),
        "page_rank": (serp.get("rank_info") or {}).get("page_rank"),
        "ai_overview_on_serp": "ai_overview" in (element.get("serp_item_types") or []),
        "serp_checked": (element.get("last_updated_time") or "")[:10],
        "previous_check": (element.get("previous_updated_time") or "")[:10],
        "dated": bool(serp.get("pre_snippet")),      # Google shows a publish date beside the result: a sign of an article
    }


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def pull(domain, auth, data_dir=DATA_DIR, fetch=None, page_size=PAGE_SIZE):
    base = {"target": domain, "location_code": dfs.LOCATION_CODE, "language_code": dfs.LANGUAGE_CODE}
    raw_dir = data_dir / "raw" / domain
    raw_dir.mkdir(parents=True, exist_ok=True)

    items, offset, total = [], 0, None
    while total is None or (offset < total and offset < MAX_ITEMS):
        reply, result = dfs.call("ranked_keywords/live", {
            **base, "limit": page_size, "offset": offset, "historical_serp_mode": "all",
            "order_by": ["keyword_data.keyword_info.search_volume,desc"]}, auth, fetch)
        (raw_dir / f"ranked_keywords_{offset:05d}.json").write_text(json.dumps(reply))
        batch = result.get("items") or []
        total = result.get("total_count") or 0
        items.extend(batch)
        offset += page_size
        if not batch:
            break
    rows = [flatten(item) for item in items]
    write_csv(data_dir / domain / "keywords.csv", KEYWORD_COLUMNS, rows)

    reply, history = dfs.call("historical_rank_overview/live", {**base, "date_from": HISTORY_FROM}, auth, fetch)
    (raw_dir / "historical_rank_overview.json").write_text(json.dumps(reply))
    months = []
    for item in sorted(history.get("items") or [], key=lambda i: (i["year"], i["month"])):
        organic = dfs.organic(item.get("metrics"))
        months.append({"month": f"{item['year']}-{item['month']:02d}", "etv": round(organic.get("etv") or 0),
                       "keywords": organic.get("count") or 0,
                       "top3": (organic.get("pos_1") or 0) + (organic.get("pos_2_3") or 0),
                       "top10": (organic.get("pos_1") or 0) + (organic.get("pos_2_3") or 0) + (organic.get("pos_4_10") or 0)})
    write_csv(data_dir / domain / "history.csv", ["month", "etv", "keywords", "top3", "top10"], months)

    urls = {row["url"] for row in rows if row["url"]}
    return {"domain": domain, "keyword_rows": len(rows), "reported_total": total, "pages": len(urls),
            "lost": sum(1 for row in rows if row["is_lost"]), "months": len(months),
            "first_month": months[0]["month"] if months else "-"}


def reflatten(domain, data_dir=DATA_DIR):
    """Rebuild keywords.csv from the raw replies already on disk."""
    items = []
    for path in sorted((data_dir / "raw" / domain).glob("ranked_keywords_*.json")):
        items.extend(((json.loads(path.read_text())["tasks"][0].get("result") or [{}])[0] or {}).get("items") or [])
    rows = [flatten(item) for item in items]
    write_csv(data_dir / domain / "keywords.csv", KEYWORD_COLUMNS, rows)
    return len(rows)


if __name__ == "__main__":
    domains = sys.argv[1:] or sys.exit(__doc__)
    if domains[0] == "--reflatten":
        for domain in domains[1:]:
            print(f"{domain}: keywords.csv rebuilt from saved replies, {reflatten(domain)} rows. No API cost.")
        sys.exit(0)
    auth = dfs.load_auth()
    for domain in domains:
        s = pull(domain.replace("https://", "").replace("www.", "").strip("/"), auth)
        flag = "" if s["keyword_rows"] == s["reported_total"] else "   <-- row count differs from the API total (the pull stops at 10,000 keywords)"
        print(f"{s['domain']}: {s['keyword_rows']} keyword rows (API total {s['reported_total']}), "
              f"{s['pages']} pages, {s['lost']} lost keywords, {s['months']} months of history from {s['first_month']}{flag}")
    print(f"\nAPI cost for this run: ${dfs.total_cost:.2f}   Files saved under {DATA_DIR}")
