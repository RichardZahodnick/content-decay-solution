# The system against a person

The job to be done: for each pair of pages on a site that compete for the same searches, decide whether to
**merge** them, **differentiate** them, or leave them **separate**. A reviewer labeled every pair on three
sites by hand, without seeing the system's answers. This page records how each version of the system scored.

The sites are real and are not named here. Their reports are not published either, because a report lists a
company's weak pages.

| Site | What it is | Used for |
|---|---|---|
| A | A marketing agency for law firms; 144 ranking pages | Labeled (38 pairs). The rules were first tuned here |
| B | A second marketing agency for law firms; 67 ranking pages | Labeled (37 pairs). First unseen-site test |
| C | A heating and cooling company; 65 ranking pages | Labeled (15 pairs). Second unseen-site test |
| D | A marketing agency for home-service companies; 101 ranking pages | Not labeled. Used to check the page map |
| E | A heating and cooling company partway through a redesign; 67 ranking pages | Not labeled. First run on a site nobody had looked at |

## Results

| | Site A (38 pairs) | Site B (37 pairs) | Site C (15 pairs) |
|---|---|---|---|
| **What the reviewer decided** | 9 merge, 8 differentiate, 21 separate | 0 merge, 37 separate (17 "differentiate if possible") | 2 merge, 13 separate (6 "differentiate if possible") |
| **Decision model alone** | 8 of 17 merge calls right; 60% agreement | 0 of 17 merge calls right; 54% agreement | 2 of 5 merge calls right; 80% agreement |
| **Rules v2** | 9 of 10 merge calls right; 79% agreement *(tuned on these labels)* | **0 of 15 merge calls right; 51% agreement** *(unseen site)* | not run |
| **Rules v3** | 8 of 9 merge calls right; 76% agreement *(tuned)* | No merges proposed; 100% agreement *(tuned)* | not run |
| **Rules v4** | 8 of 9 merge calls right; 76% agreement *(tuned)* | No merges proposed; 100% agreement *(tuned)* | **2 of 2 merge calls right; both of the reviewer's merges found; 100% agreement** *(unseen site)* |

"Agreement" is the share of pairs where the system's call matched the reviewer's first choice among merge,
differentiate and separate.

**Only the two bold results are honest out-of-sample numbers.** In both, the system's answers were saved before
the reviewer labeled anything. The first is a failure (rules v2). The second is a pass (rules v4), on a small
test: 15 pairs, 2 of them merges. Every other rules score was measured on labels the rules had already been
tuned on.

## What each round taught

**Round 1: the decision model alone.** A small local model (Kev) scored how closely two pages match in topic.
It ordered pairs sensibly but "same subject" turned out not to mean "should merge". Fewer than half its merge
calls were right.

**Round 2: the first hand review (Site A, about 30 minutes).** The reviewer did three things the system
had not:
- Checked the live site. Two pairs already redirected; the ranking data had not caught up.
- Kept pages that have to exist for business reasons: the homepage, the service page, the pillar pages.
- Merged only when the smaller page had little search footprint of its own.

Rules v2 encoded those: a live URL check, protected pages, and a keyword-overlap test beside the topic score.

**Round 3: the unseen site (Site B).** Rules v2 ran unchanged, and its answers were saved before
any labels existed. It proposed 15 merges. The reviewer agreed with none. Twelve of the 15 involved a city page
(the same service offered in one city against the same service in another). Site A has no city pages, so
nothing in v2 knew they exist. City pages share generic searches with each other and with the main service
page, which looked to the rules like duplication.

Rules v3 added one principle: **only two articles can be merged.** A page counted as an article when Google
showed a publish date beside it in search results. A decayed page that competes with a kept page got a
"sharpen targeting" alert naming its rivals.

**Round 4: checking how v3 told articles from other pages.** The score did not change, but the test behind it
was weak. On Site B the site's own sitemap and page code mark 13 pages as blog posts; Google
shows a publish date on only 3 of them. v3 would have treated the other 10 as standing pages, so its "no merges
proposed" on that site was partly because it could not see most of the articles. On Site D Google dates
all 45 podcast pages, so v3 would have treated them as mergeable articles.

Rules v4 replace that test with a **page map** built before any pair is judged. Four clues are compared for
each page: the sitemap that lists it, the page's own code, its URL, and Google's publish date. A page is typed
"unknown", and never merged, when the clues disagree on whether it is an article. Across the three sites checked at that point, 308
of 312 pages had two or more clues in agreement, and none was left unknown. v4 also adds the reviewer's rule
for location pages: they are never merged, and when two of them trade rankings the alert says to make each one
more specific to its place.

v4 gives the same calls as v3 on all 75 labeled pairs. What changed is that the page types now come from the
sites themselves, so the same score rests on firmer ground.

**Round 5: a second unseen site, in a different market (Site C).** A heating and cooling company's
site with 34 ranking blog posts, town pages and service pages. Rules v4 ran unchanged through the one-command
runner (under three minutes, $0.39 of ranking data), and its answers were saved before any labels existed. The
reviewer labeled all 15 competing pairs blind in 18 minutes. The system matched all 15: it proposed the same two
merges the reviewer chose and kept everything else apart. The decision model alone would have proposed five
merges, three of them wrong (two pairs of service pages and one pair of related articles).

The reviewer still caught three things the system did not:
- A subdomain that ranks for the brand name loads as a blank page. The system kept it as a homepage and did
  not flag it.
- Three heating-problem articles overlap closely enough to need differentiating. The system left them as
  separate because they had swapped only one search, below its bar of two.
- Six town pages were typed as ordinary standing pages, not location pages, because the places list stops at
  cities of 100,000 people. They were still kept and not merged, but they would miss the location advice.

None of the three has been fixed. Changing the rules to match one more site's labels would turn the only clean
test into another tuned score.

**Round 6: a site nobody had looked at (Site E).** The first site run from start to finish through the agent,
with no earlier look at its data. It had been redesigned by a new company, and the old addresses had not been
redirected: of 67 addresses with rankings, 41 returned an error, 15 redirected and 11 loaded. The first report
filed the broken ones under "already handled", which was wrong. The rule was changed: an address that returns an
error while searches or links still point at it gets its own finding, with the page's new address when the
sitemap lists exactly one page with the same name. 35 addresses got a finding; 27 had a match and 8 needed a
person to choose.

A hand check then corrected the system's wording. Google was already showing the new address for the largest of
those pages, because the ranking data was weeks older than the live site. The finding now says "ranked at the
last data check", and the report explains that the redirect is still needed for links and old results. The
broken addresses themselves were confirmed by hand: every one checked returned an error.

This round changed no pair call, so the scores above are unaffected. It was not a scored test.

## What this says about the product

- **A person still decides.** Merges are queued for approval, so the 15 wrong merges on the unseen site would
  have been rejected in review, not carried out. That is the reason for the tier.
- **The system's reliable value so far is finding and packaging.** It finds the decayed pages and the competing
  pairs out of thousands of keyword rows in seconds, and hands a person the evidence. Deciding the fix is where
  it is weakest.
- **"Differentiate" is the hard call for people too.** The reviewer gave a second option on 33 of the 90 pairs. Those pairs go
  to a strategist with a brief.
- **Every new site type can break the rules.** Two sites produced three rounds of changes. The third labeled
  site passed, but one pass on 15 pairs is a start, not proof. Each new site should be checked the same way: save
  the answers first, then have a person label them.
- **When the system cannot tell, it does nothing.** The page map's "unknown" type and the "keep both" call are
  the defaults, because a wrong merge costs more than a missed one.

## What the comparison does not show

- The reviewer's time was recorded for two sites (about 30 minutes for 38 pairs and 18 minutes for 15 pairs).
  That time excludes finding the decayed pages and the competing pairs, which the system does first.
- The unseen-site pass rests on 15 pairs and 2 merges. A site with more overlapping articles would test the
  merge rule harder.
- One reviewer labeled all three sites, and that reviewer's earlier labels shaped the rules. The reviewer is also
  the person who built the system. There is no second opinion to measure how much two specialists would agree
  with each other.
- Whether acting on these recommendations improves rankings has not been tested.
- The page map has been run on five WordPress sites that all use the same sitemap plugin. Sites on other
  platforms fall back to fewer clues, and that path has only been checked with made-up test pages.
- The "sharpen targeting" findings have not been scored against the reviewer. The reviewer's "differentiate if
  possible" notes on Site B were loose, and the findings were not tuned to them.
- The ranking data is as of each keyword's last check, which can be weeks old. Round 6 showed what that hides.
