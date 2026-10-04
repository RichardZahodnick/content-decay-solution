#!/usr/bin/env python3
"""Build the content-decay report for a site: one HTML page, no network needed to view it.

Usage:  python3 build_report.py example.com        then open ~/openclaw/data/example.com/report.html
Reads:  ~/openclaw/data/<site>/history.csv and analysis/ (summary.json, pages.csv, recommendations.csv,
        pair_calls.csv, merge_plan.json, keyword_assignments.csv; page_map.csv, evaluation.json and review.json if present)
Writes: ~/openclaw/data/<site>/report.html
If ~/openclaw/data/<site>/SIMULATED.txt exists, its text is shown at the top of the report and in the footer, so made-up
data (the example site) can never be mistaken for a real site's.
No API calls, no cost. Run recommend.py first.
"""
import collections, csv, datetime, html, json, os, pathlib, sys
import recommend

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
esc = lambda value: html.escape(str(value), quote=True)
num = recommend.num
path_of = lambda url: recommend.path_of(url)       # looked up each time: it depends on the site's main host
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_name(key, long=False):
    """'2026-09' or '2026-09-22' -> 'Sep 2026' (long: 'late September 2026' style is left to the caller)."""
    year, month = key[:4], int(key[5:7])
    return f"{MONTHS[month - 1]} {year}"


def nice_ticks(top):
    """Three or four round y-axis values that cover 0..top."""
    if top <= 0:
        return [0, 1]
    raw = top / 4
    magnitude = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 1
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    ticks, value = [], 0
    while value < top + step * 0.999:
        ticks.append(int(value) if float(value).is_integer() else value)
        value += step
    return ticks


def line_chart(chart_id, title, months, values, window=None, height=230, label_peak=True):
    """One series, one axis. Static SVG; the script at the bottom of the page adds the hover readout."""
    width, left, right, top, bottom = 1000, 58, 22, 30, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    ticks = nice_ticks(max(values) if values else 1)
    y_max = ticks[-1] or 1
    x = lambda i: left + (plot_w * i / max(1, len(values) - 1))
    y = lambda v: top + plot_h * (1 - v / y_max)
    parts = [f'<svg class="chart" id="{chart_id}" viewBox="0 0 {width} {height}" role="img" tabindex="0" '
             f'aria-label="{esc(title)}. Use the left and right arrow keys to read each month.">']
    if window:
        inside = [i for i, m in enumerate(months) if window[0][:7] <= m <= window[1][:7]]
        if inside:
            x0, x1 = x(inside[0]), x(inside[-1])
            parts.append(f'<rect class="window" x="{x0:.1f}" y="{top}" width="{max(2, x1 - x0):.1f}" height="{plot_h}"/>')
            parts.append(f'<text class="tick" x="{x1:.1f}" y="{top - 8}" text-anchor="end">page comparison window</text>')
    for tick in ticks:
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/>')
        parts.append(f'<text class="tick num" x="{left - 8}" y="{y(tick) + 4:.1f}" text-anchor="end">{tick:,}</text>')
    for i, month in enumerate(months):
        if month.endswith("-01"):
            parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - 8}" text-anchor="middle">{month[:4]}</text>')
    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    if values:
        parts.append(f'<polygon class="area" points="{left},{y(0):.1f} {points} {x(len(values) - 1):.1f},{y(0):.1f}"/>')
        parts.append(f'<polyline class="line" points="{points}"/>')
        last = len(values) - 1
        peak = max(range(len(values)), key=lambda i: values[i])
        marks = [(last, "end")] + ([(peak, "end" if peak > len(values) * 0.5 else "start")] if label_peak and peak != last else [])
        for index, anchor in marks:
            px, py = x(index), y(values[index])
            parts.append(f'<circle class="dot" cx="{px:.1f}" cy="{py:.1f}" r="5"/>')
            is_peak = index == peak and index != last
            tx = px - 10 if anchor == "end" else px + 10
            falling_into_it = not is_peak and index == last and values[max(0, last - 3)] > values[last] and py + 22 < top + plot_h
            ty = py + 4 if is_peak else py + 22 if falling_into_it else py - 14      # below the line when the line comes down to the last point
            label = f"{'Peak ' if is_peak else ''}{values[index]:,} in {month_name(months[index])}"
            parts.append(f'<text class="label" x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{esc(label)}</text>')
    parts.append(f'<line class="cross" x1="0" x2="0" y1="{top}" y2="{top + plot_h}" visibility="hidden"/>')
    parts.append(f'<circle class="dot hover" r="5" visibility="hidden"/>')
    parts.append("</svg>")
    geometry = {"left": left, "plotW": plot_w, "top": top, "plotH": plot_h, "yMax": y_max, "width": width}
    return "".join(parts), geometry


def bar_pair(before, now, scale):
    """Before and now as two thin bars on one baseline; the numbers sit beside them as text."""
    w = lambda v: max(1.5, 150 * v / scale) if v > 0 else 0
    return (f'<svg class="pair" viewBox="0 0 150 22" aria-hidden="true">'
            f'<rect class="bar before" x="0" y="2" height="7" width="{w(before):.1f}" rx="2"><title>Before: {before:,.0f}</title></rect>'
            f'<rect class="bar now" x="0" y="13" height="7" width="{w(now):.1f}" rx="2"><title>Now: {now:,.0f}</title></rect></svg>')


def page_link(url):
    return f'<a class="path" href="{esc(url)}">{esc(path_of(url))}</a>'


def rec_details(rec, groups, assignments, pages):
    url, others = rec["page"], [u for u in rec["other_pages"].split(" ; ") if u]
    out = [f'<p class="evidence">{esc(rec["evidence"][0].upper() + rec["evidence"][1:])}.</p>']
    group = next((g for g in groups if g["keep"] == url and set(g["redirect_to_it"]) == set(others)), None)
    if group:
        rows = "".join(
            f'<tr><td>{page_link(u)}</td><td>{"Keep" if u == url else "Redirect to the kept page"}</td>'
            f'<td class="num">{num(pages[u]["traffic_before"]):,.0f} to {num(pages[u]["traffic_now"]):,.0f}</td>'
            f'<td class="num">{esc(pages[u]["keywords_now"])}</td><td class="num">{esc(pages[u]["referring_domains"])}</td>'
            f'<td class="num">{group["strength"][u]:.2f}</td></tr>' for u in [url, *others])
        out.append('<div class="scroll"><table><thead><tr><th>Page</th><th>What to do</th><th class="num">Est. visits a month</th>'
                   '<th class="num">Keywords now</th><th class="num">Sites linking</th><th class="num">Strength</th></tr></thead>'
                   f'<tbody>{rows}</tbody></table></div>')
    rivals = [u for u in (rec.get("competes_with") or "").split(" ; ") if u]
    if rivals:
        count = lambda rival: sum(1 for a in assignments if {a["page_a"], a["page_b"]} == {url, rival})
        out.append('<p class="note">Competes with: ' + "; ".join(f'{page_link(u)} ({count(u)} shared search{"" if count(u) == 1 else "es"})' for u in rivals) + '.</p>')
    shared = [a for a in assignments if a["page_a"] == url and others and a["page_b"] == others[0]]
    if shared:
        rows = "".join(
            f'<tr><td>{esc(a["search"])}</td><td class="num">{int(num(a["volume"])):,}</td><td class="num">{esc(a["page_a_rank"])}</td>'
            f'<td class="num">{esc(a["page_b_rank"])}</td><td>{page_link(a["assign_to"])}</td><td>{esc(a["why"])}</td></tr>' for a in shared[:12])
        more = f'<p class="note">{len(shared) - 12} more in keyword_assignments.csv.</p>' if len(shared) > 12 else ""
        out.append(f'<p class="note">Page 1 is {page_link(url)}. Page 2 is {page_link(others[0])}.</p>'
                   f'<div class="scroll"><table><thead><tr><th>Search both pages compete for</th><th class="num">Searches a month</th>'
                   f'<th class="num">Page 1 ranks</th><th class="num">Page 2 ranks</th>'
                   f'<th>Suggested owner</th><th>Why</th></tr></thead><tbody>{rows}</tbody></table></div>{more}')
    if rec.get("brief"):
        out.append(f'<p class="note">Work order with the full evidence: <a class="path" href="analysis/briefs/{esc(rec["brief"])}">analysis/briefs/{esc(rec["brief"])}</a></p>')
    return "".join(out)


def broken_block(rows, scale):
    """One queue row for all the broken addresses in a tier, with the redirect list inside."""
    fix = rows[0]["action"] == recommend.BROKEN_FIX
    before, now = sum(num(r["traffic_before"]) for r in rows), sum(num(r["traffic_now"]) for r in rows)
    n = len(rows)
    title = (f"Redirect {n} broken address{'es' if n > 1 else ''} to the page's new address" if fix else
             f"{n} broken address{'es' if n > 1 else ''} with no redirect: a person picks where {'it goes' if n == 1 else 'they go'}")
    what = ("Each address returns an error and has no redirect. The sitemap lists the same page at a new address." if fix else
            "Each address returns an error and has no redirect. The sitemap has no single page with the same name.")
    body = "".join(
        f'<tr><td>{page_link(r["page"])}</td>' + (f'<td>{page_link(r["redirect_to"])}</td>' if fix else "") +
        f'<td class="num">{num(r["traffic_now"]):,.0f}</td><td>{esc(r["evidence"].split("; ")[0] + "; " + r["evidence"].split("; ")[1])}</td></tr>' for r in rows)
    head = '<th>Broken address</th>' + ('<th>Redirect it to</th>' if fix else '') + '<th class="num">Est. visits a month now</th><th>Evidence</th>'
    return (f'<li><details><summary><span class="what"><strong>{esc(title)}</strong><span class="pages">{esc(what)}</span></span>'
            f'<span class="traffic">{bar_pair(before, now, scale)}<span class="num">{before:,.0f} to {now:,.0f}</span></span></summary>'
            f'<div class="detail"><div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            '<p class="note">Each address ranked at the last data check or has sites linking to it. Ranking data can lag the live site by weeks, '
            'so Google may already show the new address. The redirect is still needed for links, bookmarks and any old results that remain. '
            'The same list is saved as analysis/redirect_map.csv.</p></div></details></li>')


def queue_section(recs, groups, assignments, pages, calls):
    tiers = [("automatic candidate", "Automatic", "Decided by code and easy to undo, such as redirecting a duplicate address."),
             ("queued fix", "Queued fixes", "The system proposes a specific fix. A person approves it before anything changes."),
             ("alert", "Alerts", "The system found the problem. A person decides the fix.")]
    broken_actions = (recommend.BROKEN_FIX, recommend.BROKEN_ASK)
    totals = [sum(num(r[k]) for r in recs if r["tier"] == t and r["action"] == a) for t in ("queued fix", "alert") for a in broken_actions for k in ("traffic_before", "traffic_now")]
    scale = max([num(r["traffic_before"]) for r in recs] + [num(r["traffic_now"]) for r in recs] + totals + [1])
    out = []
    for key, heading, blurb in tiers:
        rows = [r for r in recs if r["tier"] == key]
        out.append(f'<section class="tier"><h3>{heading} <span class="count">{len(rows)}</span></h3><p class="note">{blurb}</p>')
        if not rows:
            out.append('<p class="empty">Nothing in this tier on this run.</p></section>')
            continue
        out.append('<ul class="queue">')
        for action in broken_actions:
            group = [r for r in rows if r["action"] == action]
            if group:
                out.append(broken_block(group, scale))
        for r in rows:
            if r["action"] in broken_actions:
                continue
            others = [u for u in r["other_pages"].split(" ; ") if u]
            if r["action"].startswith(("Differentiate", "Sharpen")) and others:
                target = page_link(r["page"]) + " and " + page_link(others[0])
            elif others:
                target = f'Keep {page_link(r["page"])}. Redirect into it: ' + ", ".join(page_link(u) for u in others)
            else:
                target = page_link(r["page"])
            before, now = num(r["traffic_before"]), num(r["traffic_now"])
            out.append(
                f'<li><details><summary><span class="what"><strong>{esc(r["action"])}</strong><span class="pages">{target}</span></span>'
                f'<span class="traffic">{bar_pair(before, now, scale)}<span class="num">{before:,.0f} to {now:,.0f}</span></span></summary>'
                f'<div class="detail">{rec_details(r, groups, assignments, pages)}</div></details></li>')
        out.append("</ul></section>")
    handled = [c for c in calls if c["call"] in ("already redirected", "old address")] + \
              [{"reason": r["evidence"]} for r in recs if r["tier"] == "no action"]
    kept = [c for c in calls if c["call"] == "keep both" and num(c["url_swaps"]) >= 2 and num(c["p_same_topic"]) >= recommend.DIFF_KEV]
    if kept:
        kept.sort(key=lambda c: -num(c["url_swaps"]))
        items = "".join(f'<li>{page_link(c["page_a"])} and {page_link(c["page_b"])}: {int(num(c["url_swaps"]))} searches swapped. '
                        f'{esc(c["reason"][0].upper() + c["reason"][1:])}.</li>' for c in kept)
        out.append(f'<section class="tier"><h3>Kept pages that compete <span class="count">{len(kept)}</span></h3>'
                   '<p class="note">These pages trade rankings with each other, but at least one of them has to exist, so nothing is merged. '
                   'A pair with a decayed page, or two location pages, also has a "sharpen targeting" alert above.</p>'
                   f'<ul class="plain">{items}</ul></section>')
    if handled:
        seen, items = set(), []
        for c in handled:
            if c["reason"] not in seen:
                seen.add(c["reason"])
                items.append(f'<li>{esc(c["reason"])}</li>')
        out.append(f'<section class="tier"><h3>Already handled <span class="count">{len(items)}</span></h3>'
                   '<p class="note">The ranking data showed a problem, and the live site shows it is already fixed. No work needed.</p>'
                   f'<ul class="plain">{"".join(items)}</ul></section>')
    return "".join(out)


TYPE_NAMES = {"article": "Article", "page": "Standing page", "location": "Location page", "service": "Service page", "hub": "Index page",
              "homepage": "Homepage", "media": "Podcast or video", "other": "Other post type", "unknown": "Unknown (never merged)"}


def page_map_section(page_map):
    if not page_map:
        return ('<h3>What kind of page each one is</h3><p class="note">The page map has not been built for this site (map_pages.py), '
                'so page types fall back to URL patterns and whether Google shows a publish date.</p>')
    counts = collections.Counter(row["page_type"] for row in page_map.values())
    sure = collections.Counter(row["page_type"] for row in page_map.values() if row["confidence"] == "confirmed")
    rows = "".join(f'<tr><td>{esc(TYPE_NAMES.get(kind, kind))}</td><td class="num">{n}</td><td class="num">{sure[kind]}</td></tr>' for kind, n in counts.most_common())
    unknown = [row for row in page_map.values() if row["page_type"] == "unknown"]
    extra = ""
    if unknown:
        items = "".join(f'<li>{page_link(row["url"])}: {esc(row["note"] or row["confidence"])}</li>' for row in unknown[:12])
        more = f'<li>{len(unknown) - 12} more in page_map.csv</li>' if len(unknown) > 12 else ""
        extra = f'<p class="note">Pages left as unknown:</p><ul class="plain">{items}{more}</ul>'
    if all(row["sitemap_says"] == "no sitemap found" and not row["page_code_says"] for row in page_map.values()):
        extra += ('<p class="note">The live site has not been read for this run, so these types come from the URL and Google\'s publish date only. '
                  'Run map_pages.py to add the sitemap and the pages\' own code.</p>')
    return ('<h3>What kind of page each one is</h3><p>Only two articles can be merged, so every page is typed first. Four clues are compared: '
            'the sitemap that lists the page, the page\'s own code, its URL, and whether Google shows a publish date. '
            'When the clues disagree the page is left as unknown and is never merged.</p>'
            '<div class="scroll"><table class="narrow"><thead><tr><th>Type</th><th class="num">Pages</th><th class="num">Two or more clues agree</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>{extra}')


def pages_table(pages, recs, page_map=None):
    action = {}
    for r in recs:
        for url in [r["page"], *[u for u in r["other_pages"].split(" ; ") if u]]:
            action.setdefault(url, r["action"])
    flagged = [p for p in pages.values() if p["status"] in ("decayed", "watch", "fell with the site")]
    flagged.sort(key=lambda p: num(p["traffic_change"]))
    kind = lambda url: f'<td>{esc(TYPE_NAMES.get(recommend.type_of(url, page_map)[0], ""))}</td>' if page_map else ""
    rows = "".join(
        f'<tr><td>{page_link(p["url"])}</td>{kind(p["url"])}<td><span class="status s-{esc(p["status"].split()[0])}">{esc(p["status"])}</span></td>'
        f'<td class="num">{num(p["traffic_before"]):,.0f}</td><td class="num">{num(p["traffic_now"]):,.0f}</td>'
        f'<td class="num">{num(p["change_pct"]):+.0%}</td><td class="num">{esc(p["top10_before"])} to {esc(p["top10_now"])}</td>'
        f'<td class="num">{esc(p["referring_domains"])}</td><td>{esc(action.get(p["url"], "Monitor"))}</td></tr>' for p in flagged)
    return ('<table class="wide"><thead><tr><th>Page</th>' + ('<th>Type</th>' if page_map else '') + '<th>Status</th><th class="num">Before</th><th class="num">Now</th>'
            '<th class="num">Change</th><th class="num">Top-10 keywords</th><th class="num">Sites linking</th><th>Recommendation</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>') if rows else '<p class="empty">No pages were flagged on this run.</p>'


def evaluation_section(evaluation, review):
    if not evaluation:
        return ""
    k, v = evaluation["kev_only"], evaluation["rules"]
    version = esc(evaluation.get("rules_version", ""))
    row = lambda label, f: f'<tr><td>{label}</td><td class="num">{f(k)}</td><td class="num">{f(v)}</td></tr>'
    merges = lambda e: (f'{e["merge_true_positives"]} of {e["merge_true_positives"] + e["merge_false_positives"]}'
                        if e["merge_true_positives"] + e["merge_false_positives"] else "none proposed")
    found = lambda e: (f'{e["merge_true_positives"]} of {e["merge_true_positives"] + e["merge_missed"]}'
                       if e["merge_true_positives"] + e["merge_missed"] else "the reviewer found none")
    agree = lambda e: f'{e["three_way_agreement_strict"]:.0%}'
    misses = "".join(f'<li>{esc(d["page_a"])} and {esc(d["page_b"])}: reviewer said {esc(d["human"])}, system said {esc(d["system"])}</li>'
                     for d in v["disagreements"])
    lead = f'{evaluation["pairs"]} competing pairs were labeled by hand, without seeing the system\'s answers'
    if review:
        lead += f' ({esc(review.get("reviewer", "a reviewer"))}, about {esc(review.get("minutes", "?"))} minutes)'
    extra = "".join(f"<li>{esc(point)}</li>" for point in (review or {}).get("reviewer_caught", []))
    return (f'<section><h2>Checked against a person</h2><p>{lead}. The table compares those labels with the decision model on its own, '
            'and with the rules that add keyword overlap, protected pages and the live-site check.</p>'
            f'<div class="scroll"><table class="narrow"><thead><tr><th></th><th class="num">Decision model alone</th><th class="num">Rules {version}</th></tr></thead><tbody>'
            + row("Merge calls the reviewer agreed with", merges) + row("Reviewer's merges the system found", found)
            + row("Agreement on merge, differentiate or separate", agree) + '</tbody></table></div>'
            f'<p class="note">{esc((review or {}).get("note") or "These rules were written after seeing these labels, so the numbers are in-sample and will be lower on a new site.")}</p>'
            + (f'<h3>What the reviewer caught that the first version missed</h3><ul class="plain">{extra}</ul>' if extra else "")
            + (f'<h3>Where the system still disagrees</h3><ul class="plain">{misses}</ul>' if misses else "") + '</section>')


CSS = """
:root{color-scheme:light;--plane:#f3f5f8;--surface:#fcfcfb;--ink:#0f1722;--ink2:#465160;--muted:#76808d;--hair:#dde2e8;--axis:#c2c9d2;
--series:#2a78d6;--deemph:#b4bcc7;--critical:#d03b3b;--warning:#b87a00;--neutral:#76808d;--wash:rgba(42,120,214,.10);--band:rgba(15,23,34,.045)}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--plane:#0e1116;--surface:#171b21;--ink:#f3f5f8;--ink2:#c2c9d2;--muted:#8a94a1;
--hair:#262c35;--axis:#3a424d;--series:#3987e5;--deemph:#56606d;--critical:#e66767;--warning:#fab219;--neutral:#8a94a1;--wash:rgba(57,135,229,.14);--band:rgba(255,255,255,.05)}}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);font:15px/1.55 "Avenir Next","Segoe UI",system-ui,sans-serif}
main{max-width:1080px;margin:0 auto;padding:48px 28px 96px}
header .site{font-size:15px;color:var(--ink2);margin:0 0 20px}
h1{font-size:34px;line-height:1.18;font-weight:600;letter-spacing:-.01em;margin:0 0 14px;max-width:24em;text-wrap:balance}
header .sub{font-size:17px;color:var(--ink2);max-width:46em;margin:0}
.banner{border:1px solid var(--warning);border-left-width:5px;border-radius:4px;padding:10px 14px;margin:0 0 22px;max-width:none;background:var(--surface)}
h2{font-size:22px;font-weight:600;margin:64px 0 6px}
h3{font-size:16px;font-weight:600;margin:28px 0 2px}
p{max-width:70ch;margin:8px 0}
.note{color:var(--ink2);font-size:14px}
.empty{color:var(--muted)}
a{color:inherit}
.path{text-decoration:underline;text-decoration-color:var(--axis);text-underline-offset:3px;overflow-wrap:anywhere}
.path:hover{text-decoration-color:var(--ink)}
.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
figure{margin:28px 0 0;background:var(--surface);border:1px solid var(--hair);border-radius:6px;padding:18px 18px 8px;position:relative}
figcaption{font-weight:600;margin-bottom:2px}
figcaption span{font-weight:400;color:var(--ink2)}
.chart{display:block;width:100%;height:auto;outline-offset:4px}
.chart .grid{stroke:var(--hair);stroke-width:1}
.chart .tick{fill:var(--muted);font-size:12px}
.chart .label{fill:var(--ink);font-size:13px;font-weight:600;paint-order:stroke;stroke:var(--surface);stroke-width:5px;stroke-linejoin:round}
.chart .line{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.chart .area{fill:var(--wash)}
.chart .window{fill:var(--band)}
.chart .dot{fill:var(--series);stroke:var(--surface);stroke-width:2}
.chart .cross{stroke:var(--axis);stroke-width:1}
.tip{position:absolute;pointer-events:none;background:var(--ink);color:var(--plane);border-radius:4px;padding:6px 9px;font-size:13px;line-height:1.3;white-space:nowrap;transform:translate(-50%,-100%);visibility:hidden}
.tip b{display:block;font-size:15px}
details.table{margin:4px 0 10px}
details.table summary{cursor:pointer;color:var(--ink2);font-size:14px}
table{border-collapse:collapse;margin:14px 0;font-size:14px;width:100%}
th{text-align:left;font-weight:600;color:var(--ink2);border-bottom:1px solid var(--axis);padding:6px 14px 6px 0;vertical-align:bottom}
th.num{text-align:right}
td{border-bottom:1px solid var(--hair);padding:7px 14px 7px 0;vertical-align:top}
tr:last-child td{border-bottom:0}
table.narrow{width:auto;min-width:min(100%,560px)}
table.narrow td,table.narrow th{padding-right:28px}
.scroll{overflow-x:auto}
.tier h3{font-size:18px;margin-top:36px}
.count{display:inline-block;min-width:26px;text-align:center;border:1px solid var(--axis);border-radius:13px;font-size:13px;font-weight:600;padding:0 8px;margin-left:6px;color:var(--ink2)}
.queue{list-style:none;margin:12px 0 0;padding:0;border-top:1px solid var(--axis)}
.queue li{border-bottom:1px solid var(--hair)}
.queue summary{display:flex;gap:24px;align-items:center;justify-content:space-between;padding:12px 4px;cursor:pointer;list-style:none}
.queue summary::-webkit-details-marker{display:none}
.queue summary::before{content:"";flex:none;width:7px;height:7px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);margin:0 2px 0 4px;transition:transform .15s}
.queue details[open] summary::before{transform:rotate(45deg)}
.queue summary:hover{background:var(--band)}
.what{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.pages{color:var(--ink2);font-size:14px}
.traffic{display:flex;align-items:center;gap:12px;flex:none}
.traffic .num{min-width:7.5em;color:var(--ink2);font-size:14px}
.pair{width:150px;height:22px;flex:none}
.bar.before{fill:var(--deemph)}
.bar.now{fill:var(--series)}
.detail{padding:2px 4px 18px 26px}
.evidence{color:var(--ink2)}
.legend{display:flex;gap:18px;font-size:13px;color:var(--ink2);margin:10px 0 0;justify-content:flex-end}
.legend i{display:inline-block;width:18px;height:7px;border-radius:2px;margin-right:6px;vertical-align:middle}
.plain{padding-left:18px;max-width:80ch}
.plain li{margin:4px 0}
.status{white-space:nowrap}
.status::before{content:"";display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:var(--neutral)}
.s-decayed::before{background:var(--critical);border-radius:1px;transform:rotate(45deg)}
.s-watch::before{background:var(--warning);border-radius:1px}
.rules{counter-reset:rule;list-style:none;padding:0;max-width:74ch}
.rules li{counter-increment:rule;padding:6px 0 6px 34px;position:relative}
.rules li::before{content:counter(rule);position:absolute;left:0;top:6px;width:22px;height:22px;border:1px solid var(--axis);border-radius:50%;text-align:center;font-size:12px;line-height:20px;color:var(--ink2)}
footer{margin-top:72px;border-top:1px solid var(--axis);padding-top:18px;color:var(--ink2);font-size:14px}
@media (max-width:720px){main{padding:28px 16px 64px}h1{font-size:26px}.queue summary{flex-wrap:wrap;gap:8px}.what{flex-basis:calc(100% - 40px)}.traffic{margin-left:26px}.detail{padding-left:4px}figure{padding:12px 8px 4px}.scroll table{min-width:520px}}
@media (prefers-reduced-motion:reduce){.queue summary::before{transition:none}}
"""

SCRIPT = """
for (const spec of CHARTS) {
  const svg = document.getElementById(spec.id), tip = document.getElementById(spec.id + '-tip');
  const cross = svg.querySelector('.cross'), dot = svg.querySelector('.dot.hover'), g = spec.geometry;
  let current = spec.values.length - 1;
  const show = (i) => {
    current = Math.max(0, Math.min(spec.values.length - 1, i));
    const x = g.left + g.plotW * current / Math.max(1, spec.values.length - 1);
    const y = g.top + g.plotH * (1 - spec.values[current] / g.yMax);
    cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
    dot.setAttribute('cx', x); dot.setAttribute('cy', y); dot.setAttribute('visibility', 'visible');
    const box = svg.getBoundingClientRect(), scale = box.width / g.width;
    tip.replaceChildren();
    const value = document.createElement('b'); value.textContent = spec.values[current].toLocaleString('en-US');
    tip.append(value, document.createTextNode(spec.months[current]));
    tip.style.left = (svg.offsetLeft + x * scale) + 'px'; tip.style.top = (svg.offsetTop + y * scale - 12) + 'px';
    tip.style.visibility = 'visible';
  };
  const hide = () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); tip.style.visibility = 'hidden'; };
  svg.addEventListener('pointermove', (e) => {
    const box = svg.getBoundingClientRect(), x = (e.clientX - box.left) * g.width / box.width;
    show(Math.round((x - g.left) / g.plotW * (spec.values.length - 1)));
  });
  svg.addEventListener('pointerleave', hide);
  svg.addEventListener('focus', () => show(current));
  svg.addEventListener('blur', hide);
  svg.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { show(current - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { show(current + 1); e.preventDefault(); }
  });
}
"""


def simulated_note(site_folder):
    """The text of SIMULATED.txt in a site's data folder; '' for a real site."""
    marker = site_folder / "SIMULATED.txt"
    return " ".join(marker.read_text().split()) if marker.exists() else ""


def build(domain, data_dir=DATA_DIR, today=None):
    site, folder = data_dir / domain, data_dir / domain / "analysis"
    read = recommend.read
    load = lambda name: json.loads((folder / name).read_text()) if (folder / name).exists() else None
    summary = load("summary.json")
    history = read(site / "history.csv")
    pages = {p["url"]: p for p in read(folder / "pages.csv")}
    recommend.set_main_host(pages)
    recs, calls = read(folder / "recommendations.csv"), read(folder / "pair_calls.csv")
    groups, assignments = load("merge_plan.json") or [], read(folder / "keyword_assignments.csv")
    evaluation, review = load("evaluation.json"), load("review.json")
    page_map = {row["url"]: row for row in read(folder / "page_map.csv")}
    today = today or datetime.date.today().isoformat()
    simulated = simulated_note(site)

    counts = summary["status_counts"]
    decayed, watch = counts.get("decayed", 0), counts.get("watch", 0)
    tier = collections.Counter(r["tier"] for r in recs)
    window = (summary["window_start"], summary["newest_check"])
    lost = sum(num(p["traffic_before"]) - num(p["traffic_now"]) for p in pages.values() if p["status"] == "decayed")
    headline = (f"{decayed} of {summary['pages']} pages lost ground on their own between "
                f"{month_name(window[0])} and {month_name(window[1])}.") if decayed else \
               f"No pages decayed on their own between {month_name(window[0])} and {month_name(window[1])}."
    direction = "down" if summary["site_change_pct"] < 0 else "up"
    broken = sum(1 for r in recs if r["action"] in (recommend.BROKEN_FIX, recommend.BROKEN_ASK))
    sub = (f"Together those pages went from an estimated {sum(num(p['traffic_before']) for p in pages.values() if p['status'] == 'decayed'):,.0f} "
           f"visits a month to {sum(num(p['traffic_now']) for p in pages.values() if p['status'] == 'decayed'):,.0f}. " if decayed else "") + \
          (f"The site as a whole is {direction} {abs(summary['site_change_pct']):.0%} over the same window, and each page is judged against that. "
           f"{len(recs) - tier.get('no action', 0)} recommendations follow: {tier.get('automatic candidate', 0)} automatic, {tier.get('queued fix', 0)} queued for approval "
           f"and {tier.get('alert', 0)} that need a person's decision."
           + (f" {broken} old addresses return an error page and have no redirect." if broken else ""))

    months = [h["month"] for h in history]
    charts, figures = [], []
    for chart_id, title, column, peak in (("traffic", "Estimated visits a month from search", "etv", True),
                                          ("top10", "Keywords ranking on page one", "top10", True)):
        values = [int(num(h[column])) for h in history]
        svg, geometry = line_chart(chart_id, title, months, values, window, 250 if chart_id == "traffic" else 190, peak)
        charts.append({"id": chart_id, "values": values, "months": [month_name(m) for m in months], "geometry": geometry})
        table = "".join(f'<tr><td>{esc(month_name(m))}</td><td class="num">{v:,}</td></tr>' for m, v in zip(months, values))
        figures.append(f'<figure><figcaption>{esc(title)} <span>whole site, {esc(month_name(months[0]))} to {esc(month_name(months[-1]))}</span></figcaption>'
                       f'{svg}<div class="tip" id="{chart_id}-tip"></div>'
                       f'<details class="table"><summary>Show the monthly numbers</summary><div class="scroll"><table><thead><tr><th>Month</th>'
                       f'<th class="num">{esc(title)}</th></tr></thead><tbody>{table}</tbody></table></div></details></figure>')

    t = summary["thresholds"]
    rules = (f'<ol class="rules"><li><strong>It mattered.</strong> At least {t["MIN_TRAFFIC_BEFORE"]:.0f} estimated visits a month at the previous check.</li>'
             f'<li><strong>It fell.</strong> Estimated traffic is down {abs(t["DROP_PCT"]):.0%} or more since then.</li>'
             f'<li><strong>It fell on its own.</strong> Its drop is at least {t["RELATIVE_GAP"] * 100:.0f} points worse than the whole site\'s change.</li></ol>')
    pair_rules = (
        '<ol class="rules"><li>A page that already redirects is marked as already handled. A page that no longer loads cannot be merged; it gets its own "broken address" finding.</li>'
        '<li>The same page at two addresses, or the same title apart from the year, is a duplicate to redirect.</li>'
        '<li>Only two articles can be merged. Homepages, index pages, service pages, location pages, podcast and video pages, and pages whose type is unknown are kept.</li>'
        f'<li>Two articles on the same topic (decision model {recommend.MERGE_KEV:.2f} or higher) with at least {recommend.MERGE_OVERLAP:.0%} of the smaller one\'s searches shared: merge.</li>'
        f'<li>Related topic ({recommend.DIFF_KEV:.2f} or higher) and at least {recommend.DIFF_SWAPS} searches swapped between the pages: differentiate.</li>'
        '<li>Otherwise the pages stay separate and nothing is recommended.</li></ol>'
        '<p>Kept pages that trade rankings get a "sharpen targeting" alert: a decayed page that competes with pages that have to stay, and any two location pages that compete. '
        'For the searches they share, a search that names a place goes to that place\'s page, and a search that names no place goes to the page that is not tied to a place.</p>')
    call_counts = collections.Counter(c["call"] for c in calls)
    pairs_line = (f'{len(calls)} pairs of pages compete for the same searches: ' +
                  ", ".join(f"{n} {name}" for name, n in call_counts.most_common()) + ".") if calls else "No pages on this site compete for the same searches."

    body = f"""<main>
<header><p class="site">Content decay report for <strong>{esc(domain)}</strong>, built {esc(today)}</p>
{f'<p class="banner"><strong>Simulated data.</strong> {esc(simulated)}</p>' if simulated else ''}
<h1>{esc(headline)}</h1><p class="sub">{esc(sub)}</p></header>
{''.join(figures)}
<p class="note">Visits are estimated from rankings (search volume multiplied by the click-through rate for each position), not measured.
The shaded band is the window used to compare each page with its previous check.</p>

<section><h2>The work queue</h2>
<p>Each row is one finding. Open a row for the evidence. The bars compare estimated visits a month before and now.</p>
<div class="legend"><span><i style="background:var(--deemph)"></i>Before</span><span><i style="background:var(--series)"></i>Now</span></div>
{queue_section(recs, groups, assignments, pages, calls)}</section>

<section><h2>Pages that lost ground</h2>
<p>{decayed} decayed, {watch} to watch, and {counts.get('fell with the site', 0)} that fell no faster than the site. {esc(pairs_line)}</p>
<div class="scroll">{pages_table(pages, recs, page_map)}</div></section>

<section><h2>How a page counts as decayed</h2><p>All three must be true:</p>{rules}
<h3>How competing pages are sorted</h3><p>For each pair, the first rule that applies decides:</p>{pair_rules}
{page_map_section(page_map)}</section>

{evaluation_section(evaluation, review)}

<footer><p>Data: {'simulated, in the shape of DataForSEO rankings for Google US' if simulated else 'DataForSEO rankings for Google US'}, {summary['keyword_rows']:,} keyword rows across {summary['pages']} pages, latest check {esc(window[1])}.
There is no Search Console data, so nothing here is a measured click. A keyword with no earlier record counts as a gain, which makes the decay flags conservative.
"Refresh" means the page needs a content review; the data cannot say what to change.</p></footer>
</main>"""
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Content decay: {esc(domain)}</title><style>{CSS}</style></head><body>{body}'
            f'<script>const CHARTS = {json.dumps(charts)};{SCRIPT}</script></body></html>')
    out = site / "report.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    for domain in sys.argv[1:] or sys.exit(__doc__):
        print(f"{domain}: report saved. Open it with:  open {build(domain)}")
