# Usage analytics

AusMT records **anonymous, aggregate** usage of the served data — how much is downloaded, which
datasets, from which countries, and how many portal visits — for research-infrastructure reporting
(AuScope) and custodian conversations ("your survey was downloaded *N* times from *M* countries").

It is deliberately **not** ad-tech. There are no cookies, no cross-site tracking, and no per-user
identity. Only aggregate counts are ever stored.

## What is measured

| Metric | Source |
| --- | --- |
| Downloads by survey / station / format | Server access-log paths (`/data/edi`, `/data/xml`, `/data/bundles`) resolved through the build's `manifest.json` reverse map. |
| Download **volume** by survey and dataset | The response size the access log already records, summed per survey and per artifact. A whole-survey bundle counts toward its own survey. |
| Single-station file vs whole-survey bundle | Whether the manifest resolved the path to a per-station artifact or a survey package. |
| Portal visits | One `catalogue.json` fetch per single-page-app boot — the only server-observable visit signal. |
| API requests | Fetches of the two documented machine-readable entry points the portal itself never fetches (`/data/products/manifest.json`, `/data/mtcat.json`). This is a **path class**, not a user-agent test, and it is an upper bound: the discovery-document link sits in the page footer, so a person can click it. |
| Distinct networks per day | How many distinct **masked** networks (a /24 or /48) were seen that day. A privacy-safe reach proxy: the addresses exist only in memory while the day is folded, and only the count is stored. One network can be an entire institution, so it is reach, not people. |
| Downloads & visits by country | The **masked** client address resolved to a country (see below). |
| Australian traffic by **state** | For requests that resolve to Australia only, a second-level lookup of the same masked address to a state or territory (NSW, VIC, QLD, SA, WA, TAS, NT, ACT). Optional, and **state is the finest grain** (see below). |
| Daily time series | Downloads, volume, formats, visits, API requests and networks folded per calendar day (UTC). |
| Calendar-month rollups | The same figures accumulated per month as each day folds, for quarterly and year-over-year reporting. |

### What is *not* measured — honestly

Per-station and per-survey **page views** are **not** counted, because they cannot be measured from
server logs: the portal is a single-page application that loads the whole catalogue once and renders
every station and survey view in the browser, making **zero** additional server requests per
navigation. This screen therefore reports *downloads* (a real server request) and *whole-portal
visits*, not page views. User identification, sessions, and funnels are never collected.

## Privacy design

The public privacy promise — cookieless, no personal data — is a feature of this design, not an
obstacle to it. Research-infrastructure analytics need aggregates, never identities.

- **IP addresses are masked at the edge.** The web server truncates every client address *at write
  time* — IPv4 to a /24, IPv6 to a /48 — so a full address never touches disk. Address-bearing
  headers (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `Referer`) and credentials (`Cookie`,
  `Authorization`) are dropped from the log entirely.
- **Only aggregates are retained.** The daily aggregator folds the log into cumulative counts; the
  published `stats.json` contains **no address** (masked or otherwise) and **no user-agent string** —
  only counts and a daily series.
- **Raw logs are short-lived.** The access log is rotated with a ~7-day retention; the tail exists
  only for debugging and is not the database. Nothing about that rotation changed when the reporting
  detail grew: every breakdown is derived from the log the server already wrote.

## Retention of the aggregates

Retention applies to *counts*, never to the log. Two different lifetimes, deliberately:

| Record | Kept for | Why |
| --- | --- | --- |
| Raw access log (masked) | ~7 days | Debugging only. It is not the database. |
| Daily aggregate rows | 92 days (one quarter) | Enough for a rolling operational view without accumulating fine-grained history. |
| Monthly rollup rows | Indefinitely | Tiny pure-count records with no address, path or identity in them. They are what makes quarterly and year-over-year reporting possible. |

Each calendar month is accumulated *as its days fold*, so expiring a daily row never loses the month
it belonged to. Reports can be exported as CSV: monthly totals, and one row per month and survey.

### No backfill

Only days that were actually folded exist. When the detailed breakdown was added, existing months were
seeded from the daily rows already held (downloads and visits, marked as partial) and nothing earlier
was invented. A month whose days predate a given breakdown is flagged on screen rather than shown as a
complete figure, and older days carry no network count at all: absent, not zero. The same rule governs
the Australian state breakdown: days folded before the state table existed carry no state data, that
gap is shown as its own row rather than hidden, and nothing earlier is reconstructed.

## Australian traffic by state, and why not by city

Australia is the reporting audience for this infrastructure, so the country row alone is too coarse:
"how much of this is used inside Australia, and where" is a question a funding report has to answer.
Beneath the AU row the screen can therefore show a breakdown by **state or territory**: New South
Wales, Victoria, Queensland, South Australia, Western Australia, Tasmania, the Northern Territory and
the Australian Capital Territory.

**The breakdown stops at state, deliberately.** This is a settled design decision, not an oversight
waiting to be improved:

- **A masked prefix cannot place a request in a city.** The address is truncated to a /24 (IPv4) or
  /48 (IPv6) *before it is written to disk*. Mobile carriers and CGNAT pools routinely serve an entire
  state from one such prefix, so a city column would be confidently wrong far too often to report.
- **A city cell would be quasi-identifying.** The Australian magnetotelluric research community is
  small. "Three downloads from Hobart" names a research group as effectively as naming it would. A
  state-level cell does not.

State is the finest grain that is *both* defensible from a /24 *and* non-identifying at this
community's scale. There is no city dimension anywhere in the pipeline: the city and coordinate
columns of the source dataset are read only to be discarded.

For the same reason, state counts are recorded at the **monthly and cumulative grains only**. A state
count for a single named day would be the finest-grained cell in the file, small enough to point at a
particular group in a community this size, so daily-by-state is deliberately not recorded at all.

Two further honesty properties hold, and are visible on the screen:

- **The breakdown always reconciles with its parent.** An Australian request whose prefix the state
  table does not cover is counted in its own *"Not in the state table"* row, never dropped. The state
  rows plus that row always add up to the AU country figure exactly.
- **It is forward-only.** Days folded before the state table was in place carry no state data and are
  never backfilled, because the raw logs that could tell us are long since rotated away. That residue is
  shown on its own row (*"Counted before state data existed"*) rather than being folded silently into
  the states, or omitted so that the states appear to account for everything.

The state table is optional. Where it is absent the screen shows no state section at all, because
eight zeroes would read as "no traffic from Victoria" when the truth is "not measured".

## Geolocation data attribution

Country resolution uses the **IP to Country Lite** database by **DB-IP** (<https://db-ip.com>), and
the Australian state table is derived from **DB-IP**'s **IP to City Lite** database. Both are made
available under the **Creative Commons Attribution 4.0 International (CC-BY-4.0)** licence.

> This product includes IP to Country Lite and IP to City Lite data created by DB-IP.com, available
> from <https://db-ip.com>, licensed under
> [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

Both datasets are monthly CSVs of IP ranges read directly by a small standard-library lookup. AusMT
uses no MaxMind/GeoIP tooling and holds no licence key. Country attribution from a /24-masked address
is correct in the overwhelming majority of cases; a small amount of wrong-country noise at range
boundaries is acceptable for aggregate reporting. If the country CSV is absent or out of date, country
simply resolves to `unknown` and every other metric is unaffected.

The City Lite CSV is **never retained**. It is read once by a preparation script that distils an
Australia-only `start_ip,end_ip,state_code` table of a few megabytes; the download is then deleted.
The derived table carries the DB-IP attribution in its own header, because a file outlives the
terminal it was made in.

## Operating it

The aggregator runs as a daily host timer and the workbench **Analytics** screen (under *Operations*)
renders the result. Installing the timer, placing/refreshing the DB-IP Country CSV, and (optionally)
rebuilding the Australian state table are one-time / monthly operator chores documented in the
deployment runbook (`deploy/README.md` → "Usage analytics").
