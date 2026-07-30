# Usage analytics

AusMT records **anonymous, aggregate** usage of the served data (how much is downloaded, which
datasets, from which countries, and how many portal visits) for research-infrastructure reporting
(AuScope) and custodian conversations ("your survey was downloaded *N* times from *M* countries").

It is deliberately **not** ad-tech. There are no cookies, no cross-site tracking, and no per-user
identity. Only aggregate counts are ever stored.

## What is measured

| Metric | Source |
| --- | --- |
| Downloads by survey / station / format | Server access-log paths (`/data/edi`, `/data/xml`, `/data/bundles`, and `/data/releases/<tag>/bundles` for a cut release) resolved through the build's `manifest.json` reverse map. A release bundle matches by filename, so the frozen citable copy counts alongside the live one and keeps its own row. |
| Download **volume** by survey and dataset | The response size the access log already records, summed per survey and per artifact. A whole-survey bundle counts toward its own survey. |
| Single-station file vs whole-survey bundle | Whether the manifest resolved the path to a per-station artifact or a survey package. |
| **Countries per survey** | How many distinct countries downloaded a given survey. Only the count is reported: a named survey beside a named country is a small enough cell to identify one group. |
| Portal visits | One `catalogue.json` fetch per single-page-app boot, the only server-observable visit signal. |
| API requests | Fetches of the three documented machine-readable entry points the portal itself never fetches (`/data/products/manifest.json`, `/data/mtcat.json`, `/data/mtcat.schema.json`). This is a **path class**, and it is an upper bound: the discovery-document link sits in the page footer, so a person can click it. The schema is the `$id` the catalogue document declares, so every validator that resolves it lands here. |
| Distinct networks per day | How many distinct **masked** networks (a /24 or /48) were seen that day. A privacy-safe reach proxy: the addresses exist only in memory while the day is folded, and only the count is stored. One network can be an entire institution, so it is reach, not people. |
| Peak networks per month | The largest of that month's daily network counts, kept with the month so the reach figure outlives the 92-day daily window and can appear in a quarterly report. |
| Requests by country | The **masked** client address resolved to a country (see below). Downloads, visits and API requests all count, so the country total is exactly the counted requests. |
| Australian traffic by **state** | For requests that resolve to Australia only, a second-level lookup of the same masked address to a state or territory (NSW, VIC, QLD, SA, WA, TAS, NT, ACT). Reported both as a request count and as a split into downloads, visits, API requests and volume. Optional, and **state is the finest grain** (see below). |
| Client class | Each request's user-agent resolves to crawler, scripted or browser. It is read while the day is folded and never stored (see below). |
| Daily time series | Downloads, volume, formats, visits, API requests and networks folded per calendar day (UTC). |
| Calendar-month rollups | The same figures accumulated per month as each day folds, for quarterly and year-over-year reporting. |

### How a download is counted

A download is counted **once per day, per masked network, per file**, and a request counts whether the
server returned the whole file (status 200) or a range of it (206).

Both rules exist because one download action does not produce one log line. A browser saving a file
issues the request, sees the attachment header, cancels, and hands the transfer to its download
manager, which requests it again: two lines, one download. A resumed or ranged transfer writes one
line per range. Counting lines therefore over-counted the headline figure, and admitting only status
200 hid ranged transfers entirely, which mattered most for the largest artifacts served.

The **bytes of every request still sum**, so the volume covers what was actually served. Portal visits
and API requests are not de-duplicated: each single-page-app boot and each API fetch is a separate use.

### Clients

The user-agent is read while a day is folded, for classification only, and never stored.

- **Crawlers** (search-engine indexers, link previewers, scanners, uptime probes) are excluded from
  every figure.
- **Scripted** clients are counted, and their share of downloads is reported separately. This covers
  `curl`, `wget`, `python-requests` and the other documented HTTP clients, and anything that sends no
  user-agent at all. These are the clients the [API reference](../interoperability/api-reference.md)
  hands people, so they represent programmatic scientific use rather than robots.
- **Browsers** are everything else.

### What is not measured

Per-station and per-survey **page views** are **not** counted, because they cannot be measured from
server logs: the portal is a single-page application that loads the whole catalogue once and renders
every station and survey view in the browser, making **zero** additional server requests per
navigation. This screen therefore reports *downloads* (a real server request) and *whole-portal
visits*, not page views. User identification, sessions, and funnels are never collected.

## Privacy design

The public privacy promise (cookieless, no personal data) is a feature of this design, not an
obstacle to it. Research-infrastructure analytics need aggregates, never identities.

- **IP addresses are masked at the edge.** The web server truncates every client address *at write
  time* (IPv4 to a /24, IPv6 to a /48), so a full address never touches disk. Address-bearing
  headers (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `Referer`) and credentials (`Cookie`,
  `Authorization`) are dropped from the log entirely.
- **Only aggregates are retained.** The daily aggregator folds the log into cumulative counts; the
  published `stats.json` contains **no address** (masked or otherwise) and **no user-agent string**,
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

Each month also records how much of itself each breakdown covers: how many days were folded into it,
how many of those predate the detailed dimensions, how many were folded under the current counting
rules, and how many contributed a country. Those four figures travel in the monthly export, so a
partial month is visible in the file and not only in the prose beside it.

**Nothing is backfilled.** Only days that were actually folded exist, and a breakdown added later
starts from the day it was added; the raw logs that could reconstruct earlier days are long since
rotated away. A month whose days predate a given breakdown is flagged on screen rather than shown as a
complete figure, and older days carry no network count at all: absent, not zero. Where a month has no
detailed days at all, the cell reads *"not measured"* rather than a zero, because a zero would state a
measurement that was never taken.

Breakdowns were not all added at once, so a month can be complete for one and empty for another. The
screen names the months each breakdown does not reach, and the exports leave that cell **empty**
rather than writing a zero into it.

## Australian traffic by state, and why not by city

Australia is the reporting audience for this infrastructure, so the country row alone is too coarse:
"how much of this is used inside Australia, and where" is a question a funding report has to answer.
Beneath the AU row the screen can therefore show a breakdown by **state or territory**, as a request
count and as a split of those same requests into downloads, visits, API requests and volume.

**The breakdown stops at state, deliberately.** Two properties of the pipeline make a finer grain
unreportable:

- **A masked prefix cannot place a request in a city.** The address is truncated to a /24 (IPv4) or
  /48 (IPv6) *before it is written to disk*. Mobile carriers and CGNAT pools routinely serve an entire
  state from one such prefix, so a city column would be confidently wrong far too often to report.
- **A city cell would be quasi-identifying.** The Australian magnetotelluric research community is
  small. "Three downloads from Hobart" names a research group as effectively as naming it would. A
  state-level cell does not.

There is no city dimension anywhere in the pipeline: the city and coordinate columns of the source
dataset are read only to be discarded. For the same reason state counts exist at the **monthly and
cumulative grains only**. A state count for one named day would be the finest-grained cell in the
file, small enough to point at a particular group in a community this size.

Two reconciliation properties hold, and are visible on the screen. The **request count** column
**always reconciles with its parent**: an Australian request whose prefix the state table does not
cover lands in its own *"Not in the state table"* row, never dropped, so the state rows plus that row
add up to the AU figure exactly. And the forward-only rule above gets its own row (*"Counted before
state data existed"*) rather than being folded silently into the states.

The download, visit, API and volume columns beside it began later than the request count, so a state
counted before they existed reads *"not measured"* there. They break the same requests down further;
they are not a second measurement, and the exact-total promise stays with the request column alone.

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
