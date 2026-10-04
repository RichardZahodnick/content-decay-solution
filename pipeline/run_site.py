#!/usr/bin/env python3
"""Run the whole content-decay check for one site, start to finish, with one command.

Usage:  python3 run_site.py example.com             use the ranking data already on disk if there is any
        python3 run_site.py --fresh example.com     pull the rankings again from DataForSEO (costs money)
        python3 run_site.py --offline example.com   only the steps that need nothing: analyze, page map, recommend, report
Needs:  Kev running on this Mac. The DataForSEO login in ~/.openclaw/dataforseo.env (only when it pulls).
Writes: everything the single steps write, plus
        ~/openclaw/data/<site>/run_summary.md            the result in plain words; every number is read from the files
        ~/openclaw/data/<site>/analysis/run_status.json  each step: done, skipped or failed, and how long it took
        ~/openclaw/data/spend_log.csv                    every DataForSEO spend, used for the daily cap

THE STEPS, IN ORDER
  1 pull rankings (DataForSEO)   2 find decayed pages and competing pairs   3 judge the pairs (Kev)
  4 check live addresses         5 map page types                           6 fetch page text
  7 recommend                    8 score keyword fit (Kev)                  9 build the report
Steps 4 to 6 and 8 add evidence but are optional: if one fails, the run carries on and the summary says so.
If step 1, 2, 3, 7 or 9 fails, the run stops.

SAFETY
  - It takes one site name and nothing else. Anything that is not a plain domain name is refused before any step runs.
  - It checks that Kev answers before it spends anything.
  - Before a pull it asks DataForSEO how many keywords the site has (about one cent), estimates the cost, and refuses
    if that is above MAX_SPEND_PER_RUN or would take today's total above MAX_SPEND_PER_DAY.
  - One run at a time.
"""
import collections, csv, datetime, json, math, os, pathlib, re, sys, time

import analyze_site, build_report, check_urls, fetch_content, judge_pairs, map_pages, pull_site, recommend, score_keyword_fit
import sizing_check as dfs

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
MAX_SPEND_PER_RUN = 2.00      # US dollars
MAX_SPEND_PER_DAY = 5.00
LOCK_MINUTES = 60             # a lock older than this is treated as left over from a crashed run
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
OPTIONAL = {"check live addresses", "map page types", "fetch page text", "score keyword fit"}


REPO = pathlib.Path(__file__).resolve().parent.parent


def shown(path):
    """A path as the person would type it: ~/openclaw/data/... (also when this runs through a mounted copy of the folder).
    A path inside this repo (the example site) is shown from the repo's top folder: example/data/..."""
    try:
        return str(pathlib.Path(path).resolve().relative_to(REPO))
    except ValueError:
        pass
    text = str(path).replace(str(pathlib.Path.home()), "~", 1)
    return text.replace("~/mnt/openclaw/", "~/openclaw/", 1)


CALL_WORDS = {   # the pair calls, said so that nobody has to know the labels
    "keep both": "where both pages have to stay (nothing to merge)", "merge": "to merge into one page", "differentiate": "to differentiate",
    "separate": "that are fine as they are", "redirect duplicate": "that are duplicates to redirect", "already redirected": "already redirected on the live site",
    "old address": "involving an old address that already redirects", "page gone": "where one page no longer loads"}


class Refused(Exception):
    """The run was not started, or was stopped, for a reason the person should read."""


def clean_domain(text):
    """'https://www.Example.com/' -> 'example.com'. Refuses anything that is not a plain domain name."""
    name = re.sub(r"^www\.", "", re.sub(r"^https?://", "", (text or "").strip().lower())).rstrip("/")
    if not DOMAIN.match(name):
        raise Refused(f"'{text}' is not a plain site name. Give one domain, for example: example.com")
    return name


def estimate_cost(keyword_count):
    """Rough DataForSEO cost of a full pull, in dollars: keyword pages of 1,000, per-row fees, and the history call."""
    rows = min(keyword_count, pull_site.MAX_ITEMS)
    return round(max(1, math.ceil(rows / pull_site.PAGE_SIZE)) * 0.012 + rows * 0.00012 + 0.12 + 72 * 0.0012, 2)


def spent_today(data_dir, today=None):
    log, today = data_dir / "spend_log.csv", today or datetime.date.today().isoformat()
    return round(sum(float(r["usd"]) for r in csv.DictReader(log.open()) if r["date"] == today), 4) if log.exists() else 0.0


def record_spend(data_dir, domain, usd, what, today=None):
    log = data_dir / "spend_log.csv"
    new = not log.exists()
    with log.open("a", newline="") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["date", "site", "usd", "what"])
        writer.writerow([today or datetime.date.today().isoformat(), domain, f"{usd:.4f}", what])


def take_lock(data_dir, now=None):
    lock, now = data_dir / "run.lock", now or time.time()
    if lock.exists():
        held = lock.read_text().strip()
        if held and held != "free" and now - float(held.split()[0]) < LOCK_MINUTES * 60:
            raise Refused(f"Another run started {int((now - float(held.split()[0])) / 60)} minutes ago and has not finished. Wait for it, "
                          f"or if it crashed, wait until it is {LOCK_MINUTES} minutes old.")
    lock.write_text(f"{now} {os.getpid()}")
    return lock


def kev_is_up(send=None):
    try:
        judge_pairs.kev({"page_a": "Dog training tips", "page_b": "How to train a dog"}, "Are these two article titles about the same subject?", send)
        return True
    except (OSError, SystemExit):
        return False


def pull_step(domain, data_dir, fresh, today=None, fetch=None, auth=None):
    keywords = data_dir / domain / "keywords.csv"
    if keywords.exists() and not fresh:
        pulled = datetime.date.fromtimestamp(keywords.stat().st_mtime).isoformat()
        return "skipped", f"used the ranking data already on disk (saved {pulled}); add --fresh to pull again"
    auth = auth or dfs.load_auth()
    before = dfs.total_cost
    _, size = dfs.call("ranked_keywords/live", {"target": domain, "location_code": dfs.LOCATION_CODE, "language_code": dfs.LANGUAGE_CODE, "limit": 1}, auth, fetch)
    count = size.get("total_count") or 0
    record_spend(data_dir, domain, dfs.total_cost - before, "size check", today)
    if not count:
        raise Refused(f"DataForSEO has no ranking keywords for {domain}. Check the spelling of the site name.")
    estimate, already = estimate_cost(count), spent_today(data_dir, today)
    if estimate > MAX_SPEND_PER_RUN:
        raise Refused(f"{domain} has {count:,} keywords; a pull would cost about ${estimate:.2f}, above the ${MAX_SPEND_PER_RUN:.2f} limit for one run.")
    if already + estimate > MAX_SPEND_PER_DAY:
        raise Refused(f"${already:.2f} has been spent today; a pull of about ${estimate:.2f} would pass the ${MAX_SPEND_PER_DAY:.2f} daily limit.")
    before = dfs.total_cost
    try:
        result = pull_site.pull(domain, auth, data_dir, fetch)
    finally:                                  # a pull that fails part-way has still cost money
        cost = dfs.total_cost - before
        record_spend(data_dir, domain, cost, "full pull", today)
    return "done", f"{result['keyword_rows']:,} keyword rows across {result['pages']} pages; cost ${cost:.2f}"


def analyze_step(domain, data_dir):
    rows = list(csv.DictReader((data_dir / domain / "keywords.csv").open()))
    result = analyze_site.analyze(rows, domain)
    analyze_site.save(domain, *result, data_dir=data_dir)
    summary = result[3]
    return "done", f"{summary['status_counts'].get('decayed', 0)} decayed pages, {summary['competing_pairs']} competing pairs"


def judge_step(domain, data_dir, send=None):
    judged, _, calls = judge_pairs.judge_site(domain, data_dir, send)
    return "done", f"{len(judged)} pairs judged with {calls} Kev calls"


def urls_step(domain, data_dir):
    rows = check_urls.run(domain, data_dir)
    return "done", f"{len(rows)} addresses checked, {sum(1 for r in rows if r['redirects_to'])} redirect"


def map_step(domain, data_dir, offline=False):
    signals = None if offline else map_pages.fetch_signals(domain, data_dir)
    rows = map_pages.build_map(domain, data_dir)
    unknown = sum(1 for r in rows if r["page_type"] == "unknown")
    note = f"{len(rows)} pages typed, {unknown} left as unknown"
    if signals is None and not (data_dir / domain / "page_signals.json").exists():
        note += "; no saved clues from the live site, so only the URL and Google's publish date were used"
    return "done", note


def content_step(domain, data_dir):
    content, failed = fetch_content.run(domain, data_dir)
    return "done", f"{len(content)} pages' text saved, {len(failed)} failed"


def recommend_step(domain, data_dir):
    _, groups, _, recs, _, _ = recommend.run(domain, data_dir)
    return "done", f"{len(recs)} recommendations, {len(groups)} merge groups"


def fit_step(domain, data_dir, send=None):
    fits, _ = score_keyword_fit.score_site(domain, data_dir, send)
    return "done", f"{len(fits)} Kev calls"


def report_step(domain, data_dir):
    return "done", shown(build_report.build(domain, data_dir))


STEPS = [   # (name, needs, function, runs in --offline mode)
    ("pull rankings", "DataForSEO", pull_step, False),
    ("find decayed pages and competing pairs", "nothing", analyze_step, True),
    ("judge the pairs", "Kev", judge_step, False),
    ("check live addresses", "the live site", urls_step, False),
    ("map page types", "the live site", map_step, True),
    ("fetch page text", "the live site", content_step, False),
    ("recommend", "nothing", recommend_step, True),
    ("score keyword fit", "Kev", fit_step, False),
    ("build the report", "nothing", report_step, True),
]


def write_summary(domain, data_dir, status):
    """run_summary.md: the result in plain words. Every number comes from a file a step wrote, never from memory."""
    site, folder = data_dir / domain, data_dir / domain / "analysis"
    read = recommend.read
    load = lambda name: json.loads((folder / name).read_text()) if (folder / name).exists() else None
    summary, pages = load("summary.json"), read(folder / "pages.csv")
    recs, calls, page_map = read(folder / "recommendations.csv"), read(folder / "pair_calls.csv"), read(folder / "page_map.csv")
    num, path_of = recommend.num, recommend.path_of
    recommend.set_main_host([p["url"] for p in pages])
    lines = [f"# Content decay check: {domain}", "",
             f"Run finished {status['finished']}. " + ("All steps completed." if status["ok"] else "The run did NOT complete: see the steps below."), ""]
    if build_report.simulated_note(site):
        lines += [f"**Simulated data.** {build_report.simulated_note(site)}", ""]
    if summary and status["ok"]:
        decayed = [p for p in pages if p["status"] == "decayed"]
        month = lambda key: build_report.month_name(key)
        tiers = collections.Counter(r["tier"] for r in recs)
        lines += ["## Result", "",
                  f"- {len(decayed)} of {summary['pages']} pages decayed on their own between {month(summary['window_start'])} and {month(summary['newest_check'])}."
                  + (f" Together they went from {sum(num(p['traffic_before']) for p in decayed):,.0f} to {sum(num(p['traffic_now']) for p in decayed):,.0f} estimated visits a month." if decayed else ""),
                  f"- The whole site changed {summary['site_change_pct']:+.0%} over the same window.",
                  (f"- {len(calls)} pairs of pages compete for the same searches: " + ", ".join(f"{n} {CALL_WORDS.get(name, name)}" for name, n in collections.Counter(c["call"] for c in calls).most_common()) + ".")
                  if calls else "- No pages compete for the same searches.",
                  f"- {len(recs) - tiers.get('no action', 0)} recommendations: {tiers.get('automatic candidate', 0)} automatic, {tiers.get('queued fix', 0)} queued for approval, "
                  f"{tiers.get('alert', 0)} alerts for a person to decide."]
        broken = [r for r in recs if r["action"] in (recommend.BROKEN_FIX, recommend.BROKEN_ASK)]
        if broken:
            with_target = sum(1 for r in broken if r.get("redirect_to"))
            lines.append(f"- {len(broken)} old addresses return an error page and have no redirect. At the last data check they held about "
                         f"{sum(num(r['traffic_now']) for r in broken):,.0f} estimated visits a month; Google may already show their new addresses. "
                         f"The sitemap shows a new address for {with_target} of them; the list is in redirect_map.csv.")
        if page_map:
            types = collections.Counter(r["page_type"] for r in page_map)
            lines.append("- Page types: " + ", ".join(f"{n} {kind}" for kind, n in types.most_common()) + ". Only two articles can be merged; unknown pages are never merged.")
        work = [r for r in recs if r["tier"] != "no action" and r["action"] != recommend.BROKEN_FIX][:5]      # the redirects are summed up in the line above
        if work:
            lines += ["", "## Top of the work queue", ""]
            for r in work:
                others = [path_of(u) for u in (r["other_pages"] or r.get("competes_with") or "").split(" ; ") if u]
                lines.append(f"{r['id']}. [{r['tier']}] {r['action']}: {path_of(r['page'])}" + (f" (with {', '.join(others[:3])})" if others else "")
                             + f". Estimated visits a month {num(r['traffic_before']):,.0f} to {num(r['traffic_now']):,.0f}.")
    lines += ["", "## Steps", "", "| Step | Needs | Result | Seconds | Note |", "|---|---|---|---|---|"]
    lines += [f"| {s['step']} | {s['needs']} | {s['result']} | {s['seconds']} | {s['note']} |" for s in status["steps"]]
    lines += ["", "## Files", "", f"- Report: {shown(site / 'report.html')}", f"- Work orders: {shown(folder / 'briefs' / 'INDEX.md')}",
              f"- The queue as a table: {shown(folder / 'recommendations.csv')}", "",
              "Visits are estimated from rankings, not measured. A person approves every fix before anything changes on the site."]
    (site / "run_summary.md").write_text("\n".join(lines) + "\n")
    return site / "run_summary.md"


def run(domain, data_dir=DATA_DIR, fresh=False, offline=False, steps=None, kev_send=None, say=print):
    domain = clean_domain(domain)
    if not offline and not kev_is_up(kev_send):
        raise Refused("Kev is not answering, so nothing was started. Start it in another Terminal window with:\n"
                      "  cd ~/kev && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009")
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = take_lock(data_dir)
    status = {"site": domain, "started": datetime.datetime.now().isoformat(timespec="seconds"), "mode": "offline" if offline else "fresh" if fresh else "normal",
              "steps": [], "ok": True}
    try:
        for name, needs, action, runs_offline in steps or STEPS:
            entry = {"step": name, "needs": needs, "result": "", "seconds": 0, "note": ""}
            status["steps"].append(entry)
            if offline and not runs_offline:
                entry.update(result="skipped", note="offline mode")
                continue
            if not status["ok"]:
                entry.update(result="not run", note="an earlier step failed")
                continue
            say(f"[{len(status['steps'])}/{len(steps or STEPS)}] {name} ...")
            began = time.time()
            try:
                extra = {}
                if action is pull_step:
                    extra = {"fresh": fresh}
                elif action is map_step and offline:
                    extra = {"offline": True}
                elif action in (judge_step, fit_step) and kev_send:
                    extra = {"send": kev_send}
                entry["result"], entry["note"] = action(domain, data_dir, **extra)
            except Refused as stop:
                entry.update(result="refused", note=str(stop))
                status["ok"] = False
            except (Exception, SystemExit) as error:
                entry.update(result="failed", note=f"{type(error).__name__}: {error}"[:300])
                if name not in OPTIONAL:
                    status["ok"] = False
            entry["seconds"] = round(time.time() - began, 1)
            say(f"      {entry['result']}: {entry['note']}")
    finally:
        status["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        folder = data_dir / domain / "analysis"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "run_status.json").write_text(json.dumps(status, indent=1))
        status["summary_file"] = str(write_summary(domain, data_dir, status))
        try:
            lock.unlink()
        except OSError:
            lock.write_text("free")       # this machine can't delete here; mark the lock as released instead
    return status


if __name__ == "__main__":
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    names = [a for a in args if not a.startswith("--")]
    if len(names) != 1 or flags - {"--fresh", "--offline"} or flags == {"--fresh", "--offline"}:
        sys.exit(__doc__)
    try:
        status = run(names[0], fresh="--fresh" in flags, offline="--offline" in flags)
    except Refused as stop:
        sys.exit(f"Not started: {stop}")
    print(f"\n{'Finished' if status['ok'] else 'STOPPED'}. Summary: {shown(status['summary_file'])}")
    if status["ok"]:
        print(f"Open the report with:  open {shown(DATA_DIR / status['site'] / 'report.html')}")
    sys.exit(0 if status["ok"] else 1)
