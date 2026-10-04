#!/usr/bin/env python3
"""Sizing check: how much ranking data does DataForSEO hold for each candidate site?
This file is also the DataForSEO client the other steps use (load_auth and call), imported as `dfs`.

Usage:  python3 sizing_check.py example.com another-example.com
Reads the API login from ~/.openclaw/dataforseo.env (never from the command line).
Saves every raw API reply to ~/openclaw/data/sizing/ so nothing has to be pulled twice.
"""
import base64, json, os, pathlib, sys, urllib.request

API = "https://api.dataforseo.com/v3/dataforseo_labs/google/"
ENV_FILE = pathlib.Path.home() / ".openclaw" / "dataforseo.env"
OUT_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data") / "sizing"
LOCATION_CODE, LANGUAGE_CODE = 2840, "en"          # United States, English
total_cost = 0.0


def load_auth(env_file=ENV_FILE):
    values = {}
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    pair = f"{values['DATAFORSEO_LOGIN']}:{values['DATAFORSEO_PASSWORD']}"
    return "Basic " + base64.b64encode(pair.encode()).decode()


def call(endpoint, payload, auth, fetch=None):
    """POST one task; return its first result block. Stops loudly on any API error."""
    global total_cost
    if fetch is None:
        request = urllib.request.Request(
            API + endpoint, data=json.dumps([payload]).encode(),
            headers={"Authorization": auth, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            reply = json.load(response)
    else:
        reply = fetch(endpoint, payload)
    if reply.get("status_code") != 20000:
        sys.exit(f"API error on {endpoint}: {reply.get('status_code')} {reply.get('status_message')}")
    task = reply["tasks"][0]
    if task.get("status_code") != 20000:
        sys.exit(f"Task error on {endpoint}: {task.get('status_code')} {task.get('status_message')}")
    total_cost += float(reply.get("cost") or 0)
    return reply, (task.get("result") or [{}])[0] or {}


def organic(metrics):
    return (metrics or {}).get("organic") or {}


def size_domain(domain, auth, out_dir=OUT_DIR, fetch=None):
    base = {"target": domain, "location_code": LOCATION_CODE, "language_code": LANGUAGE_CODE}
    raw = {}

    raw["ranked_keywords"], keywords = call(
        "ranked_keywords/live", {**base, "limit": 1}, auth, fetch)
    raw["relevant_pages"], pages = call(
        "relevant_pages/live",
        {**base, "limit": 1000, "order_by": ["metrics.organic.count,desc"]}, auth, fetch)
    raw["historical_rank_overview"], history = call(
        "historical_rank_overview/live", base, auth, fetch)

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, reply in raw.items():
        (out_dir / f"{domain}__{name}.json").write_text(json.dumps(reply, indent=1))

    page_items = pages.get("items") or []
    top10 = lambda o: (o.get("pos_1") or 0) + (o.get("pos_2_3") or 0) + (o.get("pos_4_10") or 0)
    months = sorted(
        ((item["year"], item["month"], organic(item.get("metrics"))) for item in history.get("items") or []),
        key=lambda m: (m[0], m[1]))
    row = {
        "domain": domain,
        "keywords": keywords.get("total_count") or 0,
        "pages": pages.get("total_count") or 0,
        "pages_5plus_kw": sum(1 for p in page_items if (organic(p.get("metrics")).get("count") or 0) >= 5),
        "pages_top10": sum(1 for p in page_items if top10(organic(p.get("metrics"))) > 0),
        "pages_losing": sum(1 for p in page_items
                            if (organic(p.get("metrics")).get("is_down") or 0)
                            > (organic(p.get("metrics")).get("is_up") or 0)),
        "months": len(months), "first": "-", "peak": "-", "peak_etv": 0, "now_etv": 0, "vs_peak": "-",
    }
    if months:
        peak = max(months, key=lambda m: m[2].get("etv") or 0)
        now = months[-1]
        row.update(first=f"{months[0][0]}-{months[0][1]:02d}", peak=f"{peak[0]}-{peak[1]:02d}",
                   peak_etv=round(peak[2].get("etv") or 0), now_etv=round(now[2].get("etv") or 0))
        if row["peak_etv"]:
            row["vs_peak"] = f"{(row['now_etv'] - row['peak_etv']) / row['peak_etv']:+.0%}"
    return row


def report(rows):
    cols = [("domain", "Site"), ("keywords", "Keywords"), ("pages", "Pages ranking"),
            ("pages_5plus_kw", "Pages w/ 5+ kw"), ("pages_top10", "Pages in top 10"),
            ("pages_losing", "Pages losing"), ("months", "Months"), ("first", "Since"),
            ("peak", "Peak month"), ("peak_etv", "Peak traffic"), ("now_etv", "Traffic now"),
            ("vs_peak", "Vs peak")]
    widths = [max(len(label), *(len(str(r[key])) for r in rows)) for key, label in cols]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))
    print(line([label for _, label in cols]))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line([r[key] for key, _ in cols]))


if __name__ == "__main__":
    domains = sys.argv[1:] or sys.exit(__doc__)
    auth = load_auth()
    rows = [size_domain(d.replace("https://", "").replace("www.", "").strip("/"), auth) for d in domains]
    print()
    report(rows)
    print(f"\nAPI cost for this run: ${total_cost:.2f}   Raw replies saved in {OUT_DIR}")
    print('"Traffic" is DataForSEO\'s estimate from rankings, not real visits. '
          '"Pages losing" counts pages (of the top 1,000) with more keywords falling than rising.')
