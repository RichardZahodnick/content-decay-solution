#!/usr/bin/env python3
"""Turn the analysis into recommendations. No API calls, no cost.

Usage:  python3 recommend.py example.com
Reads (all under ~/openclaw/data/<site>/):
    keywords.csv, analysis/pages.csv, analysis/pairs_judged.csv
    analysis/url_status.csv    optional, from check_urls.py: which URLs redirect or are gone
    analysis/page_map.csv      optional, from map_pages.py: each page's type (article, service, location ...) and place
    page_signals.json          optional, from map_pages.py: the sitemap's address list, used to find where a broken page moved to
    content.json               optional, from fetch_content.py: page text, to measure shared text
    analysis/labels.csv        optional: a reviewer's hand labels, used only to score the rules
Writes (under analysis/):
    pair_calls.csv           every competing pair: merge / differentiate / keep both / separate, and why
    merge_plan.json          each merge group: the page to keep, the pages to redirect to it
    keyword_assignments.csv  for pairs to differentiate: which page should own each shared search
                             (by topical fit when analysis/keyword_fit.csv exists, from score_keyword_fit.py;
                             otherwise by which page ranks higher today)
    recommendations.csv      the work queue: one row per finding, with a tier and the evidence
    redirect_map.csv         every broken address that still ranks, with its new address when the sitemap has one
    briefs/                  one work order per merge group, per pair to differentiate and per "sharpen targeting"
                             finding (INDEX.md lists them)
    evaluation.json          agreement with the hand labels, when they exist

THE RULES (v4). For each pair of pages that compete for the same searches, in this order:
  1. One URL already redirects to the other -> "already redirected". It redirects somewhere else -> "old address".
     It no longer loads -> "page gone". (Needs url_status.csv. No merge decision is needed for these pairs.)
  2. Same page at two addresses, or same title apart from the year -> "redirect duplicate" (decided by code)
  3. Either page is not an article -> "keep both"; never merged. Each page's type comes from the page map
     (map_pages.py: the sitemap, the page's own code, its URL and Google's publish date, compared). Homepages, index
     pages, service pages, location pages, podcast and video pages, other post types, and pages whose type the clues
     disagree on are all kept. Only two articles can be merged.
     Without a page map the v3 test is used: URL patterns, then whether Google shows a publish date.
  4. Kev same-topic >= MERGE_KEV and the smaller page shares >= MERGE_OVERLAP of its searches -> "merge"
  5. Kev same-topic >= DIFF_KEV and the pages have swapped rankings >= DIFF_SWAPS times -> "differentiate"
  6. Otherwise -> "separate" (no action)
KEPT PAGES THAT COMPETE get "sharpen targeting": a decayed page that trades rankings with pages that have to stay,
and any two location pages that trade rankings. Location pages are never merged, whether they are for different
places or the same one. For the searches they share: a search that names a place belongs to that place's page;
a search that names no place belongs to the page that is not tied to a place.
BROKEN ADDRESSES. An address that returns an error (404 and the like), and that ranked at the last data check or
has sites linking to it, is not "handled": anyone who follows an old result or link gets an error page. The ranking
data can lag the live site by weeks, so after a redesign Google may already show the new address; the redirect is
still needed for links, bookmarks and whatever old results remain. Each one gets its own finding, whatever its decay status. When the
site's sitemap lists exactly one page with the same last part of the address (/hvac/a-post/ -> /blog/a-post/), the
fix is specific, a 301 redirect to that address, and it is a queued fix. Otherwise a person picks the destination.
This was added after the first site with a redesign and no redirects (41 of its 67 ranking addresses returned
404). It does not change any pair call, so the scores against hand labels are unaffected.
TIERS. automatic candidate: decided by code and easy to undo (redirect a duplicate address).
queued fix: the system proposes a specific fix and a person approves it (merge with a clear page to keep, prune).
alert: the system found a problem but a person decides the fix (differentiate, sharpen targeting, refresh, close-call merges).
Pairs to differentiate go to a strategist with a brief: deciding what each page is for is judgment work.

HISTORY (the full record is in docs/HUMAN_VS_SYSTEM.md). v2 was tuned on 38 hand labels for one site (9 of 10
merge calls right there). On a second site it had not seen, v2 proposed 15 merges and the reviewer agreed with
none: 12 involved city pages, a page type the first site does not have. v3 added the "only articles merge" rule,
using Google's publish date as the test for an article. That test was wrong for some pages (articles Google shows
undated, podcast pages it dates), so v4 replaces it with the page map and adds the location rules. v3 and v4 were
written after seeing both sites' labels, so their scores on those two are in-sample. v4 then ran unchanged on a
third site it had not seen and matched all 15 of the reviewer's calls.
"""
import collections, csv, json, os, pathlib, re, sys
import analyze_site, map_pages

DATA_DIR = pathlib.Path(os.environ.get("OPENCLAW_DATA") or pathlib.Path.home() / "openclaw" / "data")
RULES_VERSION = "v4"
MERGE_KEV, MERGE_OVERLAP = 0.70, 0.50
ARTICLE_SHARE = 0.50         # a page is an article if Google shows a publish date on at least this share of its results
DIFF_KEV, DIFF_SWAPS = 0.60, 2
CLOSE_CALL = 0.15            # winner margin below this: a person picks the page to keep
SHARED_TEXT_NOTE = 0.20      # mention word-for-word shared text in the evidence at or above this share
FIT_MARGIN = 0.10            # a search goes to the better-fitting page only if Kev's fit differs by this much
PROTECTED = [                # pages that are never merged away or merged into
    (r"^/$", "homepage"),
    (r"^/(blog|portfolio|services|about|contact|resources|podcast)/?$", "index page"),
    (r"/services?/|-services/?$", "service page"),
]
KIND_TEXT = {                # page types from the page map that are never merged, as "X is a ..."
    "homepage": "homepage", "hub": "index page", "service": "service page", "page": "standing page, not an article",
    "media": "podcast or video page", "other": "page of its own type, not an article",
    "unknown": "page whose type could not be confirmed, so it is left alone",
}
STRENGTH_WEIGHTS = {"referring_domains": 0.35, "traffic": 0.30, "keywords_now": 0.20, "page_rank": 0.15}

num = lambda value: float(value or 0)
MAIN_HOSTS = set()            # set per site by set_main_host(); pages on any other host are shown with their host


def path_of(url):
    """'/a-page/' for a page on the site's main host; 'sub.site.com/a-page/' for a page on a subdomain."""
    host, _, path = url.split("://", 1)[-1].partition("/")
    return "/" + path if not MAIN_HOSTS or host.lower() in MAIN_HOSTS else f"{host}/{path}"


def set_main_host(urls):
    """The host most of the site's pages are on (with and without www) is the one whose pages are shown as bare paths."""
    hosts = collections.Counter(u.split("://", 1)[-1].split("/", 1)[0].lower() for u in urls)
    MAIN_HOSTS.clear()
    if hosts:
        main = hosts.most_common(1)[0][0]
        MAIN_HOSTS.update({main, "www." + main, main[4:] if main.startswith("www.") else main})


def type_of(url, page_map):
    """(page type, place) from the page map; ('', '') when the page has no entry."""
    row = (page_map or {}).get(url)
    return (row["page_type"], row.get("place", "")) if row else ("", "")


def type_label(url, page_map):
    kind, place = type_of(url, page_map)
    return f"{kind} ({place})" if kind == "location" and place else kind


def protected_kind(url, pages=None, page_map=None):
    """Why this page is never merged, or '' if it is an article that can be."""
    kind, place = type_of(url, page_map)
    if kind == "article":
        return ""
    if kind == "location":
        return f"location page for {place}" if place else "location page"
    if kind:
        return KIND_TEXT[kind]
    for pattern, kind in PROTECTED:                 # no page map entry: the v3 test
        if re.search(pattern, path_of(url)):
            return kind
    share = (pages or {}).get(url, {}).get("dated_share", "")
    if share != "" and num(share) < ARTICLE_SHARE:
        return "page with no publish date in Google's results (a service, location or hub page, not an article)"
    return ""


def live_problem(url, status):
    """'' when the URL loads normally (or was never checked)."""
    row = status.get(url)
    if not row:
        return ""
    code = str(row.get("status_code") or "")
    if row.get("redirects_to"):
        return f"redirects to {row['redirects_to']}"
    if code.startswith(("4", "5")):
        return f"returns {code}"
    return ""


last_part = lambda url: [seg for seg in path_of_any(url).lower().split("/") if seg][-1:] or [""]
path_of_any = lambda url: "/" + url.split("://", 1)[-1].split("?")[0].split("#")[0].partition("/")[2]


def new_address(url, sitemap_urls):
    """Where a broken page seems to have moved: the one sitemap address that ends with the same name. '' if none or several."""
    name = last_part(url)[0]
    if not name:
        return ""
    own = map_pages.url_key(url)
    found = sorted({u for u in sitemap_urls if last_part(u)[0] == name and map_pages.url_key(u) != own})
    return found[0] if len(found) == 1 else ""


def is_broken(url, status):
    return live_problem(url, status).startswith("returns")


BROKEN_FIX = "Redirect a broken address to the page's new address"
BROKEN_ASK = "Broken address with no redirect: a person picks where it goes"

same_page = lambda x, y: re.sub(r"/+$", "", x.lower()) == re.sub(r"/+$", "", y.lower())


def call_for_pair(pair, status, pages=None, page_map=None):
    a, b = pair["page_a"], pair["page_b"]
    kev, overlap, swaps = num(pair["p_same_topic"]), num(pair["overlap_of_smaller_page"]), int(num(pair["url_swaps"]))
    for url, other in ((a, b), (b, a)):
        problem = live_problem(url, status)
        if problem.startswith("returns"):
            return "page gone", f"{path_of(url)} {problem}"
        if problem:
            target = status[url]["redirects_to"]
            if same_page(target, other):
                return "already redirected", f"{path_of(url)} already redirects to {path_of(other)}"
            same_site = target.split("://", 1)[-1].split("/", 1)[0] == url.split("://", 1)[-1].split("/", 1)[0]
            return "old address", f"{path_of(url)} is an old address that now redirects to {path_of(target) if same_site else 'another site'}"
    if pair["decided_by"].startswith("code"):
        return "redirect duplicate", pair["decided_by"].split(": ", 1)[-1]
    (kind_a, place_a), (kind_b, place_b) = type_of(a, page_map), type_of(b, page_map)
    if kind_a == kind_b == "location" and place_a and place_b:
        if place_a != place_b:
            return "keep both", f"location pages for different places ({place_a} and {place_b})"
        return "keep both", f"both are location pages for {place_a}"
    for url in (a, b):
        kind = protected_kind(url, pages, page_map)
        if kind:
            return "keep both", f"{path_of(url)} is a {kind}"
    if kev >= MERGE_KEV and overlap >= MERGE_OVERLAP:
        return "merge", f"two articles on the same topic ({kev:.2f}), and the smaller one shares {overlap:.0%} of its searches"
    if kev >= DIFF_KEV and swaps >= DIFF_SWAPS:
        return "differentiate", f"related topic ({kev:.2f}) and {swaps} searches have swapped between the pages"
    return "separate", f"topic match {kev:.2f}, {overlap:.0%} overlap, {swaps} swaps"


def shingles(paragraphs, size=5):
    out = set()
    for paragraph in paragraphs:
        words = re.sub(r"[^a-z0-9 ]+", "", paragraph.lower()).split()
        out.update(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))
    return out


def content_overlap(a, b, content):
    """How much of each page's text also appears on the other (runs of 5 words). None if either page wasn't fetched."""
    if a not in content or b not in content:
        return None
    sa, sb = shingles(content[a]["paragraphs"]), shingles(content[b]["paragraphs"])
    if not sa or not sb:
        return None
    both = len(sa & sb)
    headings_b = {h[1].lower() for h in content[b]["headings"]}
    return {"share_of_a": round(both / len(sa), 3), "share_of_b": round(both / len(sb), 3),
            "shared_headings": [h[1] for h in content[a]["headings"] if h[1].lower() in headings_b]}


def strength(urls, pages):
    """0-1 score per page within a group: links, traffic, keywords, page rank. Dated or malformed URLs are halved."""
    def metrics(url):
        p = pages.get(url, {})
        return {"referring_domains": num(p.get("referring_domains")), "page_rank": num(p.get("page_rank")),
                "keywords_now": num(p.get("keywords_now")),
                "traffic": max(num(p.get("traffic_before")), num(p.get("traffic_now")))}
    values = {url: metrics(url) for url in urls}
    scores = {}
    for url in urls:
        score = 0.0
        for name, weight in STRENGTH_WEIGHTS.items():
            top = max(v[name] for v in values.values())
            score += weight * (values[url][name] / top if top else 0)
        if re.search(r"(19|20)\d\d", path_of(url)) or "//" in path_of(url):
            score *= 0.5
        scores[url] = round(score, 3)
    return scores


def merge_groups(calls, pages):
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    joined = [c for c in calls if c["call"] in ("merge", "redirect duplicate")]
    for c in joined:
        parent[find(c["page_a"])] = find(c["page_b"])
    members = collections.defaultdict(set)
    for url in list(parent):
        members[find(url)].add(url)
    groups = []
    for urls in members.values():
        scores = strength(urls, pages)
        ranked = sorted(urls, key=lambda u: (-scores[u], u))
        inside = [c for c in joined if c["page_a"] in urls and c["page_b"] in urls]
        margin = round(scores[ranked[0]] - scores[ranked[1]], 3)
        groups.append({
            "keep": ranked[0], "redirect_to_it": ranked[1:], "strength": {u: scores[u] for u in ranked},
            "winner_margin": margin, "winner_is_clear": margin >= CLOSE_CALL,
            "all_duplicates": all(c["call"] == "redirect duplicate" for c in inside),
            "lowest_confidence": min(num(c["p_same_topic"]) for c in inside),
            "traffic_before": round(sum(num(pages.get(u, {}).get("traffic_before")) for u in urls), 1),
            "traffic_now": round(sum(num(pages.get(u, {}).get("traffic_now")) for u in urls), 1),
            "decayed_pages": [u for u in ranked if pages.get(u, {}).get("status") in ("decayed", "watch")],
            "pairs": [{"page_a": c["page_a"], "page_b": c["page_b"], "call": c["call"], "reason": c["reason"]} for c in inside]})
    groups.sort(key=lambda g: -g["traffic_before"])
    for number, group in enumerate(groups, 1):
        group["group"] = number
    return groups


def keyword_assignments(calls, rows, pages, fits=None, page_map=None, also=()):
    """Suggested owner for each search two pages share. Covers pairs to differentiate, plus the kept pairs in `also`.
    fits: {(url, search): 0-1} from Kev ("would this page be a good result for this search?"), when available."""
    fits, also = fits or {}, set(also)
    places = map_pages.load_places() if any(r["page_type"] == "location" for r in (page_map or {}).values()) else {}
    place_of = lambda url: type_of(url, page_map)[1] if type_of(url, page_map)[0] == "location" else ""
    by_page = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        key = analyze_site.search_key(row["keyword"])
        if key:
            by_page[row["url"]][key].append(row)
    best = lambda found: min(found, key=lambda r: (r["is_lost"] == "True", num(r["rank"])))
    out = []
    for c in calls:
        a, b = c["page_a"], c["page_b"]
        if c["call"] != "differentiate" and (a, b) not in also:
            continue
        scores = strength([a, b], pages)
        place_a, place_b = place_of(a), place_of(b)
        for key in sorted(set(by_page[a]) & set(by_page[b])):
            row_a, row_b = best(by_page[a][key]), best(by_page[b][key])
            live_a, live_b = row_a["is_lost"] != "True", row_b["is_lost"] != "True"
            fit_a, fit_b = fits.get((a, row_a["keyword"])), fits.get((b, row_a["keyword"]))
            named = map_pages.find_place(row_a["keyword"], places) if places else ""
            if named and (named == place_a) != (named == place_b):
                owner, why = (a if named == place_a else b), f"the search names {named}"
            elif not named and bool(place_a) != bool(place_b):
                owner, why = (b if place_a else a), "no place in the search, so it goes to the page not tied to a place"
            elif fit_a is not None and fit_b is not None and abs(fit_a - fit_b) >= FIT_MARGIN:
                owner, why = (a if fit_a > fit_b else b), "better topical fit"
            elif live_a != live_b:
                owner, why = (a if live_a else b), "the only page still ranking"
            elif num(row_a["rank"]) != num(row_b["rank"]):
                owner, why = (a if num(row_a["rank"]) < num(row_b["rank"]) else b), "ranks higher" if live_a else "ranked higher before both lost it"
            else:
                owner, why = (a if scores[a] >= scores[b] else b), "same rank; the stronger page"
            out.append({"page_a": a, "page_b": b, "search": row_a["keyword"],
                        "volume": int(max(num(row_a["search_volume"]), num(row_b["search_volume"]))),
                        "page_a_rank": f"{int(num(row_a['rank']))}{'' if live_a else ' (lost)'}",
                        "page_b_rank": f"{int(num(row_b['rank']))}{'' if live_b else ' (lost)'}",
                        "fit_page_a": "" if fit_a is None else round(fit_a, 2),
                        "fit_page_b": "" if fit_b is None else round(fit_b, 2),
                        "assign_to": owner, "why": why})
    out.sort(key=lambda r: (r["page_a"], r["page_b"], -r["volume"]))
    return out


def rivals_of(url, calls):
    """Kept pages this page trades rankings with: [(searches swapped, other page)], most swaps first."""
    return sorted(((int(num(c["url_swaps"])), c["page_b"] if c["page_a"] == url else c["page_a"]) for c in calls
                   if c["call"] == "keep both" and url in (c["page_a"], c["page_b"])
                   and int(num(c["url_swaps"])) >= 1 and num(c["p_same_topic"]) >= DIFF_KEV), reverse=True)


def sharpen_plan(calls, groups, pages, status, page_map=None):
    """Which kept pages get a "sharpen targeting" finding. Returns
    ({decayed page: its rivals}, [location-page pairs that trade rankings and are not already under a decayed page])."""
    covered = {u for g in groups for u in [g["keep"], *g["redirect_to_it"]]}
    covered |= {u for c in calls if c["call"] == "differentiate" for u in (c["page_a"], c["page_b"])}
    by_page = {}
    for url, page in pages.items():
        if page["status"] not in ("decayed", "watch") or url in covered or live_problem(url, status):
            continue
        if num(page["keywords_now"]) == 0 and not protected_kind(url, pages, page_map):
            continue                                   # ranks for nothing: it is pruned or redirected instead
        rivals = rivals_of(url, calls)
        if rivals:
            by_page[url] = rivals
    listed = {frozenset((url, other)) for url, rivals in by_page.items() for _, other in rivals}
    pairs = [c for c in calls if c["call"] == "keep both" and int(num(c["url_swaps"])) >= DIFF_SWAPS and num(c["p_same_topic"]) >= DIFF_KEV
             and type_of(c["page_a"], page_map)[0] == type_of(c["page_b"], page_map)[0] == "location"
             and frozenset((c["page_a"], c["page_b"])) not in listed]
    return by_page, pairs


def sharpen_pair_keys(calls, by_page, pairs):
    """The (page_a, page_b) pairs behind the sharpen findings, spelled the way pair_calls.csv spells them."""
    wanted = {frozenset((url, other)) for url, rivals in by_page.items() for _, other in rivals}
    wanted |= {frozenset((c["page_a"], c["page_b"])) for c in pairs}
    return [(c["page_a"], c["page_b"]) for c in calls if frozenset((c["page_a"], c["page_b"])) in wanted]


REC_FIELDS = ["id", "tier", "action", "page", "other_pages", "competes_with", "redirect_to", "evidence", "confidence", "traffic_before", "traffic_now", "brief"]


def broken_addresses(pages, status, sitemap_urls=()):
    """A finding for every address that returns an error while searches or links still point at it."""
    out = []
    for url, page in pages.items():
        if not is_broken(url, status):
            continue
        ranking, links = int(num(page.get("keywords_now"))), int(num(page.get("referring_domains")))
        if not ranking and not links:
            continue                                   # nothing points at it any more
        code = str(status[url]["status_code"])
        target = new_address(url, sitemap_urls)
        before, now = num(page.get("traffic_before")), num(page.get("traffic_now"))
        evidence = (f"returns {code}; ranked for {ranking} search{'' if ranking == 1 else 'es'} at the last data check"
                    + (f" ({int(num(page.get('top10_now')))} on page one)" if page.get("top10_now") not in (None, "") else "")
                    + f", about {now:.0f} est. visits a month then" + (f"; {links} site{'' if links == 1 else 's'} link to it" if links else ""))
        if target:
            evidence += f"; the sitemap lists a page with the same name at {path_of(target)}"
        else:
            evidence += "; the sitemap has no single page with the same name"
        out.append({"tier": "queued fix" if target else "alert", "action": BROKEN_FIX if target else BROKEN_ASK, "page": url, "other_pages": "",
                    "redirect_to": target, "evidence": evidence, "confidence": "", "traffic_before": round(before, 1), "traffic_now": round(now, 1),
                    "brief": "", "_weight": max(before, now)})
    return out


def recommendations(calls, groups, assignments, pages, rows, status, page_map=None, sitemap_urls=()):
    recs, covered = [], set()
    recs += broken_addresses(pages, status, sitemap_urls)
    covered.update(r["page"] for r in recs)
    for g in groups:
        covered.update([g["keep"], *g["redirect_to_it"]])
        duplicate = g["all_duplicates"]
        if duplicate:
            tier, action = "automatic candidate", "Redirect duplicate"
        elif g["winner_is_clear"]:
            tier, action = "queued fix", "Merge and redirect"
        else:
            tier, action = "alert", "Merge: a person picks the page to keep"
        evidence = f"{len(g['redirect_to_it']) + 1} pages on one topic; lowest pair confidence {g['lowest_confidence']:.2f}; winner margin {g['winner_margin']:.2f}"
        if g["decayed_pages"]:
            evidence += f"; decayed: {', '.join(path_of(u) for u in g['decayed_pages'])}"
        recs.append({"tier": tier, "action": action, "page": g["keep"],
                     "other_pages": " ; ".join(g["redirect_to_it"]), "evidence": evidence,
                     "confidence": g["lowest_confidence"], "traffic_before": g["traffic_before"], "traffic_now": g["traffic_now"],
                     "brief": f"merge-{g['group']}-{slug(g['keep'])}.md"})
    counts = collections.Counter((r["page_a"], r["page_b"]) for r in assignments)
    both = lambda a, b, key: round(num(pages[a][key]) + num(pages[b][key]), 1)
    for c in calls:
        if c["call"] == "differentiate":
            a, b = c["page_a"], c["page_b"]
            covered.update([a, b])
            recs.append({"tier": "alert", "action": "Differentiate: brief for a strategist",
                         "page": a, "other_pages": b,
                         "evidence": f"{c['reason']}; {counts[(a, b)]} shared searches with a suggested owner",
                         "confidence": num(c["p_same_topic"]),
                         "traffic_before": both(a, b, "traffic_before"), "traffic_now": both(a, b, "traffic_now"),
                         "brief": f"differentiate-{slug(a)}--{slug(b)}.md"})
    sharpen, location_pairs = sharpen_plan(calls, groups, pages, status, page_map)
    for c in location_pairs:
        a, b = c["page_a"], c["page_b"]
        recs.append({"tier": "alert", "action": "Sharpen targeting: location pages competing with each other",
                     "page": a, "other_pages": b,
                     "evidence": f"{c['reason']}; {int(num(c['url_swaps']))} searches have swapped between them; "
                                 f"{counts[(a, b)]} shared searches with a suggested owner",
                     "confidence": num(c["p_same_topic"]),
                     "traffic_before": both(a, b, "traffic_before"), "traffic_now": both(a, b, "traffic_now"),
                     "brief": f"sharpen-{slug(a)}--{slug(b)}.md"})
    lost = collections.defaultdict(list)
    for row in rows:
        if row["is_lost"] == "True":
            lost[row["url"]].append((num(row["search_volume"]), row["keyword"]))
    for url, page in pages.items():
        if page["status"] not in ("decayed", "watch") or url in covered:
            continue
        problem = live_problem(url, status)
        before, now = num(page["traffic_before"]), num(page["traffic_now"])
        top_lost = ", ".join(kw for _, kw in sorted(lost[url], reverse=True)[:3])
        base = f"{page['status']}: {before:.0f} -> {now:.0f} est. visits; lost {page['keywords_lost']} keyword{'' if str(page['keywords_lost']) == '1' else 's'}" + (f" (e.g. {top_lost})" if top_lost else "")
        ranks_for_nothing = num(page["keywords_now"]) == 0 and not protected_kind(url, pages, page_map)
        rivals = sharpen.get(url, [])
        competes_with = brief = ""
        if problem.startswith("returns"):
            tier, action, evidence = "no action", "Gone: nothing ranks or links to it any more", f"{path_of(url)} {problem} and nothing points at it"
        elif problem:
            tier, action, evidence = "no action", "Already handled: stale data", f"{path_of(url)} {problem}"
        elif ranks_for_nothing and num(page["referring_domains"]) == 0:
            tier, action, evidence = "queued fix", "Prune: remove or noindex", base + "; ranks for nothing now and no sites link to it"
        elif ranks_for_nothing:
            tier, action, evidence = "queued fix", "Redirect to the closest live page", base + f"; ranks for nothing now but {page['referring_domains']} sites still link to it"
        elif rivals:
            names = ", ".join(path_of(other) for _, other in rivals[:4]) + (f" and {len(rivals) - 4} more" if len(rivals) > 4 else "")
            tier, action = "alert", "Sharpen targeting: it competes with pages that have to stay"
            swapped = sum(n for n, _ in rivals)
            evidence = base + f"; {swapped} search{' has' if swapped == 1 else 'es have'} swapped between it and {len(rivals)} kept page{'s' if len(rivals) > 1 else ''}: {names}"
            local = sum(1 for _, other in rivals if type_of(other, page_map)[0] == "location")
            if local:
                evidence += f"; location pages among them: {local}"
            competes_with, brief = " ; ".join(other for _, other in rivals), f"sharpen-{slug(url)}.md"
        else:
            tier, action, evidence = "alert", "Refresh: needs a content review", base + "; no competing page found on this site"
        recs.append({"tier": tier, "action": action, "page": url, "other_pages": "", "competes_with": competes_with, "evidence": evidence,
                     "confidence": "", "traffic_before": round(before, 1), "traffic_now": round(now, 1), "brief": brief})
    order = {"automatic candidate": 0, "queued fix": 1, "alert": 2, "no action": 3}
    recs.sort(key=lambda r: (order[r["tier"]], -r.get("_weight", r["traffic_before"] - r["traffic_now"])))
    for number, rec in enumerate(recs, 1):
        rec["id"] = number
    return [{field: rec.get(field, "") for field in REC_FIELDS} for rec in recs]


slug = lambda url: re.sub(r"[^a-z0-9]+", "-", path_of(url).lower()).strip("-")[:40] or "home"


def page_table(urls, pages, page_map=None):
    cell = lambda u, k: str(pages.get(u, {}).get(k, "")).replace("|", "/")       # a | in a title would break the table
    visits = lambda u: f"{num(cell(u, 'traffic_before')):.0f} → {num(cell(u, 'traffic_now')):.0f}"
    lines = ["| | " + " | ".join(f"`{path_of(u)}`" for u in urls) + " |", "|---|" + "---|" * len(urls)]
    for label, value in (("Title", lambda u: cell(u, "title")), ("Est. visits a month, before → now", visits),
                         ("Keywords ranking now", lambda u: cell(u, "keywords_now")), ("Keywords lost", lambda u: cell(u, "keywords_lost")),
                         ("Sites linking to it", lambda u: cell(u, "referring_domains")), ("Decay status", lambda u: cell(u, "status")),
                         ("Page type", lambda u: type_label(u, page_map))):
        if label != "Page type" or page_map:
            lines.append(f"| {label} | " + " | ".join(value(u) for u in urls) + " |")
    return "\n".join(lines)


def own_searches(url, others, rows, limit=8):
    """Searches this page ranks for (top 30) that none of the other pages has on record."""
    taken = {analyze_site.search_key(r["keyword"]) for r in rows if r["url"] in others}
    mine = [r for r in rows if r["url"] == url and r["is_lost"] != "True" and num(r["rank"]) <= 30
            and analyze_site.search_key(r["keyword"]) not in taken]
    mine.sort(key=lambda r: -num(r["search_volume"]))
    return [f"- {r['keyword']} ({int(num(r['search_volume']))} searches a month, ranks #{int(num(r['rank']))})" for r in mine[:limit]]


def content_section(a, b, content):
    overlap = content_overlap(a, b, content)
    if overlap is None:
        return "## Page content\n\nPage text hasn't been fetched for both pages (run `fetch_content.py`).\n"
    lines = ["## Page content", "",
             f"- {overlap['share_of_a']:.0%} of the text on `{path_of(a)}` also appears on `{path_of(b)}`.",
             f"- {overlap['share_of_b']:.0%} of the text on `{path_of(b)}` also appears on `{path_of(a)}`."]
    if overlap["shared_headings"]:
        lines.append("- Headings on both pages: " + "; ".join(overlap["shared_headings"][:10]))
    for url in (a, b):
        outline = [h[1] for h in content[url]["headings"] if h[0] in ("h1", "h2")][:14]
        lines += ["", f"Outline of `{path_of(url)}` ({content[url]['word_count']} words):"] + [f"- {h}" for h in outline]
    return "\n".join(lines) + "\n"


def review_notes(a, b, labels):
    for label in labels:
        if {label["page_a"], label["page_b"]} == {a, b}:
            words = label.get("human_words") or ""
            notes = [n for n in (words if len(words) > 25 else "", label.get("human_notes_followup")) if n]   # a one-word label isn't a note
            if notes:
                return "## Notes from the hand review\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    return ""


GEO_STEPS = [
    "Each of these pages has to exist, so nothing is merged. The fix is to make each location page plainly about its own place.", "",
    "1. Put the place in the title, the main heading and the opening paragraph of its page.",
    "2. Name the neighborhoods, districts and nearby towns that page is meant to serve.",
    "3. Refer to local landmarks, institutions or rules where they matter to the reader.",
    "4. Use proof from that place: clients, results or reviews.",
    "5. Leave searches that name no place to the main page, and link each location page to it.",
    "6. Re-run this pipeline in four to six weeks and check whether the pages still swap rankings."]
GENERAL_STEPS = [
    "These pages have to stay, so nothing is merged. The fix is to make clear which searches each page is for.", "",
    "1. Decide which searches this page is for, using the suggested owners above as a starting point.",
    "2. Make the title, main heading and opening paragraph of each page match the searches it owns.",
    "3. Where a page covers a search another page owns, cut that part down and link to the owner.",
    "4. Re-run this pipeline in four to six weeks and check whether the pages still swap rankings."]


def sharpen_brief(page, rivals, joint, assignments, pages, page_map):
    """Work order for kept pages that trade rankings. joint: the finding is about the pair, not one decayed page."""
    p = pages.get(page, {})
    if joint:
        title = f"# Sharpen targeting: `{path_of(page)}` and `{path_of(rivals[0])}`"
        why = "these two location pages trade rankings with each other. Both have to exist, so they are not merged."
    else:
        title = f"# Sharpen targeting: `{path_of(page)}`"
        why = (f"this page went from {num(p.get('traffic_before')):.0f} to {num(p.get('traffic_now')):.0f} estimated visits a month, and it trades "
               f"rankings with {len(rivals)} page{'s' if len(rivals) > 1 else ''} that {'have' if len(rivals) > 1 else 'has'} to stay, so nothing can be merged.")
    text = [title, "", f"**Why this is here:** {why}",
            "**What needs deciding:** which searches each page is for. The suggested owners below are a starting point from the data, not a strategy.", "",
            "## The pages", "", page_table([page, *rivals[:5]], pages, page_map), ""]
    for rival in rivals:
        shared = [x for x in assignments if {x["page_a"], x["page_b"]} == {page, rival}]
        text += [f"## Searches shared with `{path_of(rival)}` ({len(shared)})", ""]
        if not shared:
            text += ["- None on record.", ""]
            continue
        rank = lambda x, url: x["page_a_rank"] if x["page_a"] == url else x["page_b_rank"]
        text += [f"| Search | Searches a month | `{path_of(page)}` ranks | `{path_of(rival)}` ranks | Suggested owner | Why |", "|---|---|---|---|---|---|"]
        text += [f"| {x['search']} | {x['volume']} | {rank(x, page)} | {rank(x, rival)} | `{path_of(x['assign_to'])}` | {x['why']} |" for x in shared[:20]]
        text += ([f"", f"{len(shared) - 20} more in keyword_assignments.csv."] if len(shared) > 20 else []) + [""]
    local = any(type_of(u, page_map)[0] == "location" for u in [page, *rivals])
    text += ["## What to change", "", *(GEO_STEPS if local else GENERAL_STEPS), ""]
    return "\n".join(text)


def write_briefs(folder, calls, groups, assignments, pages, rows, content, labels, recs=(), page_map=None):
    briefs = folder / "briefs"
    briefs.mkdir(exist_ok=True)
    index = []
    for g in groups:
        keep, others = g["keep"], g["redirect_to_it"]
        name = f"merge-{g['group']}-{slug(keep)}.md"
        kind = "Redirect duplicate" if g["all_duplicates"] else "Merge"
        text = [f"# {kind}: keep `{path_of(keep)}`, redirect {len(others)} page{'s' if len(others) > 1 else ''} into it", "",
                f"**Why this is here:** these pages cover one topic and compete for the same searches. "
                f"Together they went from {g['traffic_before']:.0f} to {g['traffic_now']:.0f} estimated visits a month.",
                f"**Lowest pair confidence:** {g['lowest_confidence']:.2f}. **Page to keep:** "
                + ("clear from the data." if g["winner_is_clear"] else "a close call; a person should pick."), "",
                "## The pages", "", page_table([keep, *others], pages, page_map), "",
                "## Redirects to set up (301)", ""] + [f"- `{path_of(u)}` → `{path_of(keep)}`" for u in others] + [""]
        for other in others:
            carry = own_searches(other, [keep], rows)
            text += [f"## Searches `{path_of(other)}` ranks for that the kept page doesn't", "",
                     *(carry or ["- None on record. Nothing ranking would be lost by redirecting it."]), ""]
            text += [content_section(keep, other, content), review_notes(keep, other, labels)]
        text += ["## Steps", "", "1. Move anything unique and useful from the redirected pages into the kept page.",
                 "2. Set up the 301 redirects above.", "3. Point internal links at the kept page.",
                 "4. Re-run this pipeline in four to six weeks and check the kept page's rankings.", ""]
        (briefs / name).write_text("\n".join(t for t in text if t is not None))
        index.append((kind, name, f"`{path_of(keep)}` ← " + ", ".join(f"`{path_of(u)}`" for u in others)))
    for c in calls:
        if c["call"] != "differentiate":
            continue
        a, b = c["page_a"], c["page_b"]
        name = f"differentiate-{slug(a)}--{slug(b)}.md"
        shared = [x for x in assignments if x["page_a"] == a and x["page_b"] == b]
        text = [f"# Differentiate: `{path_of(a)}` and `{path_of(b)}`", "",
                f"**Why this is here:** these pages compete for the same searches but look like they should stay as two pages ({c['reason']}).",
                "**What needs deciding:** what each page is for, and which page should rank for each shared search. "
                "The suggested owners below are a starting point from the data, not a strategy.", "",
                "## The pages", "", page_table([a, b], pages, page_map), "",
                f"## Searches both pages compete for ({len(shared)})", "",
                "| Search | Searches a month | A ranks | B ranks | Suggested owner | Why |", "|---|---|---|---|---|---|"]
        text += [f"| {x['search']} | {x['volume']} | {x['page_a_rank']} | {x['page_b_rank']} | `{path_of(x['assign_to'])}` | {x['why']} |" for x in shared]
        text += ["", f"## What only `{path_of(a)}` ranks for", "", *(own_searches(a, [b], rows) or ["- Nothing in the top 30."]), "",
                 f"## What only `{path_of(b)}` ranks for", "", *(own_searches(b, [a], rows) or ["- Nothing in the top 30."]), "",
                 content_section(a, b, content), review_notes(a, b, labels)]
        (briefs / name).write_text("\n".join(text))
        index.append(("Differentiate", name, f"`{path_of(a)}` and `{path_of(b)}`"))
    for rec in recs:
        if not rec["action"].startswith("Sharpen"):
            continue
        joint = bool(rec["other_pages"])
        rivals = [u for u in (rec["other_pages"] or rec["competes_with"]).split(" ; ") if u]
        (briefs / rec["brief"]).write_text(sharpen_brief(rec["page"], rivals, joint, assignments, pages, page_map))
        index.append(("Sharpen targeting", rec["brief"], f"`{path_of(rec['page'])}` and " + ", ".join(f"`{path_of(u)}`" for u in rivals[:4])
                      + (f" and {len(rivals) - 4} more" if len(rivals) > 4 else "")))
    current = {name for _, name, _ in index} | {"INDEX.md"}
    for old in briefs.glob("*.md"):
        if old.name not in current:
            try:
                old.unlink()
            except OSError:
                pass                      # can't delete here; INDEX.md lists the current briefs
    lines = ["# Briefs", "", "One work order per finding. This index lists the current ones.", "",
             "| Type | Pages | File |", "|---|---|---|"] + [f"| {kind} | {what} | `{name}` |" for kind, name, what in index]
    (briefs / "INDEX.md").write_text("\n".join(lines) + "\n")
    return [name for _, name, _ in index]


BUCKET = {"merge": "merge", "redirect duplicate": "merge", "already redirected": "merge", "already merged": "merge",
          "merge candidate": "merge", "differentiate": "differentiate"}


def evaluate(calls, labels, page_map_used=False):
    """Agreement with hand labels. 'lenient' also accepts the second option the labeler said was fine."""
    by_pair = {(c["page_a"], c["page_b"]): c for c in calls}
    out = {"pairs": len(labels), "rules_version": RULES_VERSION, "page_map_used": page_map_used}
    for name, system_of in (("rules", lambda c: c["call"]), ("kev_only", lambda c: c["kev_only_verdict"])):
        strict = lenient = tp = fp = fn = 0
        misses = []
        for label in labels:
            c = by_pair[(label["page_a"], label["page_b"])]
            system = BUCKET.get(system_of(c), "separate")
            human = BUCKET.get(label["human_call"], "separate")
            also = BUCKET.get(label["human_also_ok"], "separate") if label["human_also_ok"] else human
            strict += system == human
            lenient += system in (human, also)
            tp += system == "merge" and human == "merge"
            fp += system == "merge" and human != "merge"
            fn += system != "merge" and human == "merge"
            if system not in (human, also):
                misses.append({"pair": label["pair"], "page_a": path_of(label["page_a"]), "page_b": path_of(label["page_b"]),
                               "human": label["human_call"], "system": system_of(c)})
        out[name] = {"three_way_agreement_strict": round(strict / len(labels), 3),
                     "three_way_agreement_lenient": round(lenient / len(labels), 3),
                     "merge_precision": round(tp / (tp + fp), 3) if tp + fp else None,
                     "merge_recall": round(tp / (tp + fn), 3) if tp + fn else None,
                     "merge_true_positives": tp, "merge_false_positives": fp, "merge_missed": fn,
                     "disagreements": misses}
    return out


def read(path):
    return list(csv.DictReader(path.open())) if path.exists() else []


def write(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def run(domain, data_dir=DATA_DIR):
    folder = data_dir / domain / "analysis"
    pages = {p["url"]: p for p in read(folder / "pages.csv")}
    set_main_host(pages)
    rows = read(data_dir / domain / "keywords.csv")
    status = {s["url"]: s for s in read(folder / "url_status.csv")}
    content_file = data_dir / domain / "content.json"
    content = json.loads(content_file.read_text()) if content_file.exists() else {}
    page_map = {row["url"]: row for row in read(folder / "page_map.csv")}
    signals_file = data_dir / domain / "page_signals.json"
    sitemap_urls = [u for urls in (json.loads(signals_file.read_text()).get("sitemaps") or {}).values() for u in urls] if signals_file.exists() else []
    calls = []
    for pair in read(folder / "pairs_judged.csv"):
        call, reason = call_for_pair(pair, status, pages, page_map)
        shared_text = content_overlap(pair["page_a"], pair["page_b"], content)
        if shared_text and max(shared_text["share_of_a"], shared_text["share_of_b"]) >= SHARED_TEXT_NOTE:
            reason += f"; {max(shared_text['share_of_a'], shared_text['share_of_b']):.0%} of one page's text is word-for-word on the other"
        calls.append({"page_a": pair["page_a"], "page_b": pair["page_b"], "call": call, "reason": reason,
                      "type_a": type_label(pair["page_a"], page_map), "type_b": type_label(pair["page_b"], page_map),
                      "shared_text": "" if shared_text is None else max(shared_text["share_of_a"], shared_text["share_of_b"]),
                      "p_same_topic": pair["p_same_topic"], "overlap_of_smaller_page": pair["overlap_of_smaller_page"],
                      "url_swaps": pair["url_swaps"], "shared_volume": pair["shared_volume"],
                      "top_shared_searches": pair["top_shared_searches"], "kev_only_verdict": pair["verdict"]})
    groups = merge_groups(calls, pages)
    fits = {(f["url"], f["search"]): num(f["fit"]) for f in read(folder / "keyword_fit.csv")}
    also = sharpen_pair_keys(calls, *sharpen_plan(calls, groups, pages, status, page_map))
    assignments = keyword_assignments(calls, rows, pages, fits, page_map, also)
    recs = recommendations(calls, groups, assignments, pages, rows, status, page_map, sitemap_urls)
    broken = [{"old_address": r["page"], "new_address": r["redirect_to"], "how_found": "same page name in the sitemap" if r["redirect_to"] else "none found; a person picks",
               "status_code": status[r["page"]]["status_code"], "est_visits_now": r["traffic_now"], "keywords_now": pages[r["page"]].get("keywords_now", ""),
               "page_one_keywords": pages[r["page"]].get("top10_now", ""), "sites_linking": pages[r["page"]].get("referring_domains", "")}
              for r in recs if r["action"] in (BROKEN_FIX, BROKEN_ASK)]
    if broken:
        write(folder / "redirect_map.csv", broken)
    write(folder / "pair_calls.csv", calls)
    write(folder / "keyword_assignments.csv", assignments)
    write(folder / "recommendations.csv", recs)
    (folder / "merge_plan.json").write_text(json.dumps(groups, indent=1))
    labels = read(folder / "labels.csv")
    write_briefs(folder, calls, groups, assignments, pages, rows, content, labels, recs, page_map)
    evaluation = evaluate(calls, labels, bool(page_map)) if labels else None
    if evaluation:
        (folder / "evaluation.json").write_text(json.dumps(evaluation, indent=1))
    return calls, groups, assignments, recs, evaluation, bool(status)


if __name__ == "__main__":
    for domain in sys.argv[1:] or sys.exit(__doc__):
        calls, groups, assignments, recs, evaluation, checked = run(domain)
        print(f"{domain}: {dict(collections.Counter(c['call'] for c in calls))}")
        print(f"  {len(groups)} merge groups, {len(assignments)} keyword assignments, {len(recs)} recommendations: "
              f"{dict(collections.Counter(r['tier'] for r in recs))}")
        if not checked:
            print("  Live URL check not run yet (check_urls.py): redirects already in place are not accounted for.")
        if not (DATA_DIR / domain / "analysis" / "page_map.csv").exists():
            print("  Page map not built yet (map_pages.py): page types fall back to URL patterns and Google's publish date.")
        if evaluation:
            for name in ("kev_only", "rules"):
                e = evaluation[name]
                print(f"  vs hand labels, {name if name == 'kev_only' else 'rules ' + RULES_VERSION}: merge precision {e['merge_precision']}, recall {e['merge_recall']}, "
                      f"three-way agreement {e['three_way_agreement_strict']:.0%} strict / {e['three_way_agreement_lenient']:.0%} lenient")
