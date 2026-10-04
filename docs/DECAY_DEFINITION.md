# What "decayed" means (version 1)

This is the working definition the pipeline uses. The thresholds are settings at the top of
`pipeline/analyze_site.py`, and every run records the values it used in `analysis/summary.json`.

## The definition

A page is **decayed** when all three are true:

| Rule | Threshold | Why |
|---|---|---|
| It mattered | At least 10 estimated visits a month at the previous check | Tiny pages swing wildly; flagging them wastes the SEO team's time |
| It fell | Estimated traffic down 30% or more since the previous check | A clear drop, not normal week-to-week movement |
| It fell on its own | Its change is at least 15 points worse than the whole site's change | Separates "this page has a problem" from "the whole site, or the whole market, moved" |

Other statuses the pipeline assigns:

| Status | Meaning |
|---|---|
| watch | Down 15–30%, and at least 15 points worse than the site |
| fell with the site | Down 30% or more, but no worse than the site overall |
| stable | Between −15% and +15% (or down less than 30% in line with the site) |
| growing | Up 15% or more |
| new or growing | Under 10 visits before, 10 or more now |
| too small to judge | Under 10 visits before and now |

## How the numbers are calculated

- **Estimated traffic** for a keyword is its monthly search volume multiplied by the click-through
  rate for the position the page holds. The click-through rates are DataForSEO's, measured from the
  site's own data (position 1 is about 30%, position 2 about 16%, position 10 about 1%).
- **Now** is the page's traffic at each keyword's latest check.
- **Before** is the same calculation at each keyword's previous check. Keywords the page has since
  lost count at the position they last held.
- **The window** is roughly the last five months. Keywords lost more than 150 days before the newest
  check are older losses; they are counted separately and left out of the comparison.
- **The site's change** is the same before-and-now calculation summed across every page.

## Known limits

- These are estimates from rankings. There is no Search Console data, so no real clicks or impressions.
- Each keyword is checked on its own schedule, so the window is not identical for every keyword
  (most keywords were re-checked 7 to 16 weeks apart; the median is about 10 weeks).
- A keyword with no earlier record counts as pure gain. This overstates growth and makes the decay
  flags conservative: a flagged page lost traffic even after full credit for every new keyword.
- The thresholds (10 visits, 30%, 15 points) are starting values. They should be tuned against pages
  an SEO team has already judged by hand.
