# Usage analytics

AusMT records anonymous, aggregate usage of the served data (how much is downloaded, which datasets,
from which countries, how many portal visits) for research-infrastructure reporting to AuScope and for
custodian conversations. There are no cookies, no cross-site tracking and no per-user identity. Only
aggregate counts are stored.

## What is measured

| Metric | Source |
| --- | --- |
| Downloads by survey, station and format | Access-log paths (`/data/edi`, `/data/xml`, `/data/bundles`, `/data/releases/<tag>/bundles`) resolved through the build's `manifest.json`. A release bundle matches by filename and keeps its own row. |
| Download volume | The response size the log records, summed per survey and per artifact. |
| Single-station file vs whole-survey bundle | Whether the manifest resolved the path to a per-station artifact or a survey package, globally and per survey. |
| Countries per survey | How many distinct countries downloaded a survey. Only the count: a named survey beside a named country is a small enough cell to identify a group. |
| Portal visits | One `catalogue.json` fetch per single-page-app boot. |
| API requests | Fetches of the four documented machine-readable entry points, `/data/products/manifest.json`, `/data/mtcat.json`, `/data/mtcat.schema.json` and `/data/stations.geojson`, which the portal itself never fetches. An upper bound (a person can click the footer link), counted as documents: a document served both at the data root and under `/data/products/` is one entry point, and both of its published paths count. |
| Distinct networks per day, peak per month | Masked networks (/24 or /48) seen that day; addresses exist only in memory while the day is folded. One network can be an institution. |
| Requests by country, Australian requests by state | The masked address resolved to a country, and for Australia to a state or territory, as a request count and a split into downloads, visits, API requests and volume. State is the finest grain. |
| Client class | The user-agent resolves to crawler, scripted or browser while the day is folded and is never stored. Crawlers are excluded from every figure; scripted clients (`curl`, `wget`, `python-requests`, no user-agent) are counted and their share reported separately. |
| Bulk map exports vs single downloads | The file requests a map export was going to make anyway carry a query flag (`sel=bulk`). Reported as a file count and as an export-event proxy (distinct masked networks per day). |
| Downloads by collection | The `collection_id` of the survey, from the served catalogue document. |
| Time-series hand-offs to NCI THREDDS | The `/go/ts/<survey>/<station>/<level>` redirect the front door answers with the archive's own file URL, counted per survey, product level and destination archive. These are **requests, not completed transfers**: AusMT hands the reader off and never sees whether a byte moved, so nothing here can say a file was downloaded. The size beside each figure is the one the verified-resource register records for that file, because a redirect's log line carries only the size of the redirect itself. AusMT hosts none of those bytes and adds nothing in the browser to measure them. |
| Daily series and calendar-month rollups | Downloads, volume, formats, visits, API requests and networks per UTC day, accumulated per month as each day folds. |

A download is counted once per day, per masked network, per file, whether the server returned the whole
file (200) or a range (206), because one download action does not produce one log line: a browser
re-requests from its download manager, and a resumed transfer writes one line per range. Bytes of every
request still sum. Visits, API requests and archive hand-offs are not de-duplicated: one hand-off is one
redirect, so every line is another request rather than another leg of one. Per-station and per-survey page views
cannot be counted: the portal loads the catalogue once and renders every view in the browser. User
identification, sessions and funnels are never collected.

## Privacy design

- IP addresses are masked at the edge: the web server truncates every client address at write time
  (IPv4 to a /24, IPv6 to a /48), and drops address-bearing headers (`X-Forwarded-For`, `X-Real-IP`,
  `Forwarded`, `Referer`) and credentials (`Cookie`, `Authorization`) from the log.
- Only aggregates are retained. The published `stats.json` contains no address and no user-agent string.
- The raw log rotates with about seven days of retention; it is for debugging, not the database.
- Nothing is added in the browser to measure a hand-off. The redirect is a request the reader was
  making anyway and the web server was already logging it, so there is no beacon, no extra request and
  no client-side event: the analytics client stays disabled and the page adds no measurement call.
- One label, and only one. When you export a map selection the portal adds `sel=bulk` to the file
  requests it was already making. No separate request is made for the label, and
  nothing about who is asking is recorded; the flag is stripped before the file is attributed, so a
  labelled and an unlabelled fetch of the same file are one download. The
  single-station download links in a station drawer carry no flag, which is what makes an unlabelled
  fetch mean single rather than unknown.

## Retention of the aggregates

| Record | Kept for | Why |
| --- | --- | --- |
| Raw access log (masked) | about 7 days | debugging only |
| Daily aggregate rows | 92 days | a rolling operational view |
| Monthly rollup rows | indefinitely | pure counts with no address, path or identity; quarterly and year-over-year reporting |
| Daily aggregate archive | indefinitely | one line of pure counts per folded day, no geography, never served or rendered |
| Time-series hand-off counts | with the aggregate row that carries them | request counts and register byte totals per survey, product level and destination archive; the by-country figure for them exists at the monthly and cumulative grains only, exactly like every other country figure here |

Each month is accumulated as its days fold, so expiring a daily row never loses the month. Each month
records how many days it covers, how many predate the detailed dimensions, how many were folded under
the current counting rules and how many contributed a country; those figures travel in the monthly CSV
export. Nothing is backfilled: a breakdown starts from the day it was added, an older day carries no
network count (absent, not zero), and a month with no detailed days reads "not measured". The exports
leave an unmeasured cell empty rather than writing a zero into it. The bulk-versus-single split records
its own start date and the screen names that day.

## Australian traffic by state, and why not by city

Beneath the AU row the screen can show a breakdown by state or territory, and it stops there. A /24 or
/48 prefix cannot place a request in a city (mobile carriers and CGNAT pools serve a state from one
prefix), and a city cell would be quasi-identifying in a research community this small. There is no city
dimension anywhere in the pipeline; the city and coordinate columns of the source dataset are read only
to be discarded. Country and state counts exist at the monthly and cumulative grains only, and the daily
archive carries no geography.

The request count always reconciles with its parent: an Australian request the state table does not
cover lands in a "Not in the state table" row, requests counted before state data existed get their own
row, and the state rows add up to the AU figure exactly. The download, visit, API and volume columns
began later and read "not measured" where they predate the request count. Where the state table is
absent the screen shows no state section.

## Geolocation data attribution

Country resolution uses the IP to Country Lite database by DB-IP (<https://db-ip.com>), and the
Australian state table is derived from DB-IP's IP to City Lite database, both under CC-BY-4.0:

> This product includes IP to Country Lite and IP to City Lite data created by DB-IP.com, available
> from <https://db-ip.com>, licensed under
> [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

Both are monthly CSVs of IP ranges read by a standard-library lookup; AusMT uses no MaxMind tooling and
holds no licence key. If the country CSV is absent or out of date, country resolves to `unknown` and
every other metric is unaffected. The City Lite CSV is never retained: a preparation script distils an
Australia-only `start_ip,end_ip,state_code` table and the download is deleted. The derived table carries
the DB-IP attribution in its own header, because a file outlives the terminal it was made in.

## Operating it

The aggregator runs as a daily host timer and the workbench Analytics screen (under Operations) renders
the result. Installing the timer, refreshing the DB-IP Country CSV and rebuilding the state table are
documented in `deploy/README.md` under "Usage analytics".
