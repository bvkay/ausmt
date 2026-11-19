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
| User-agent split (browser / scripted) | The user-agent resolves to crawler, scripted or browser while the day is folded and is never stored. Crawlers are excluded from every figure; scripted clients (`curl`, `wget`, `python-requests`, no user-agent) are counted and their share reported separately. |
| Operator requests | From `labels_since`, requests made by the site's own operator and curators, taken out of every other figure and counted on their own line per month and overall (see [Operator requests](#operator-requests)). |
| Client class | From `labels_since`, tool, portal session, landing page or unknown for each counted request that is not the operator's (see [Client class](#client-class)). |
| Network type | From `labels_since`, hosting, education or research, access provider, other or unknown for the masked network of each counted request that is not the operator's (see [Network type](#network-type)). |
| Bulk map exports vs single downloads | The file requests a map export was going to make anyway carry a query flag (`sel=bulk`). Reported as a file count and as an export-event proxy (distinct masked networks per day). |
| Downloads by collection | The `collection_id` of the survey, from the served catalogue document. |
| Time-series hand-offs to NCI THREDDS | The `/go/ts/<survey>/<station>/<level>` redirect the front door answers with the archive's own file URL, counted per survey, product level and destination archive. These are **requests, not completed transfers**: AusMT hands the reader off and never sees whether a byte moved, so nothing here can say a file was downloaded. The size beside each figure is the one the verified-resource register records for that file, because a redirect's log line carries only the size of the redirect itself. AusMT hosts none of those bytes and adds nothing in the browser to measure them. The destination breakdown reads as a single row today, because one archive holds every file AusMT hands off; it is recorded per destination anyway, since a breakdown that is missing when a second archive appears cannot be filled in backwards. |
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
- The operator, client class and network type labels below are a different thing: they are worked
  out from what the log already holds while each day is folded, and add nothing to any request.

## Retention of the aggregates

| Record | Kept for | Why |
| --- | --- | --- |
| Raw access log (masked) | about 7 days, including the copies the nightly count reads, which are removed once counted | debugging only |
| Daily aggregate rows | 184 days | the day-by-day charts on the curator Usage page |
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

## Operator requests

The site's own operator and curators make requests too: checking a release, browsing the curation
host, running health checks. From the first labelled day folded, recorded in the statistics as
`labels_since`, each counted request is first checked for being one of these, while the day is
folded and without storing anything per request. A request is the operator's when it arrives in the
curation host's own log (which only the host itself and its private network can reach), when its
user-agent starts with the client name the site's own checks send (`ausmt-ops/`), when its masked
address is a loopback, private, link-local, shared (100.64.0.0/10) or unspecified address, or when
its masked network is in the operator's list of static networks, which is held on the host and never published. Operator requests are taken out of
every figure from that date and counted only in a separate operator total per month and overall,
never per day. Figures before that date include the operator's own requests and are not revised.
The `ausmt-ops/` name is public: anyone sending it only moves their own requests into the operator
total.

## Client class

From the same date, each counted request that is not the operator's also carries a client class,
worked out while the day is folded:

- **tool**: a documented HTTP client or a request with no user-agent, or one client (the same
  user-agent on the same masked network) that fetched more than 50 different files in a day without
  the portal's export label. Every download from such a client that day is a tool download; its
  catalogue loads and other requests are not;
- **portal session**: a browser-like client whose masked network loaded the portal, or took a file
  carrying the export label, that day or the day before;
- **landing page**: a browser-like client whose masked network opened a survey or collection page
  that day or the day before;
- **unknown**: every other browser-like request.

A download counted once under the same-day rule takes the class of the request that was counted.
The evidence behind the class is held in memory while the day is folded and is never stored. The
statistics keep the class at month and cumulative grain, and the permanent daily record keeps only
a count per class for each day, with no network detail. Declared crawlers stay excluded, as before;
their requests are now also counted, per month and per day in the permanent daily record, as
excluded crawler requests. The existing browser
and scripted split of downloads is unchanged.

## Network type

From the same date, each counted request that is not the operator's also carries a network type,
looked up from its masked network in a table held on the host: **hosting**, **education or
research**, **access provider**, **other** or **unknown**. Government, enterprise, transit and every
other kind of network fold into other, so that no value points at a single organisation. Unknown
means the table does not cover the network, or the table was missing or out of date that day. No
address is sent anywhere for the lookup. The table is rebuilt monthly, and a table whose oldest
source is older than an age limit set on the host (45 days by default) is not used, so every request
then reads unknown. A table that is missing, unreadable or has no valid header is not used either.

By default the table lists hosting networks only, so every other network reads unknown. Network type
is kept only in the monthly and cumulative statistics, joined with the client class; it is never
written to the permanent daily record and never crossed with country, state, survey or dataset.

## Who made the requests

The workbench Analytics screen turns the client class and the network type into three audiences.
They are worked out from the stored monthly counts each time the screen is drawn and are never
stored themselves:

- **people**: portal sessions and landing-page visitors, on any network;
- **automated**: tools, plus unknown clients on hosting networks;
- **unclassified**: every other request. It is never guessed, and it may include people.

People is therefore a floor. A person on a commercial VPN, or a university job in a public cloud,
reads hosting; a script that opens the portal first and fetches 50 files or fewer a day reads as
people. The screen leads with the latest labelled month split this way for downloads, portal
visits, API requests and time-series hand-offs, with the operator's requests and declared crawler
requests on their own lines, and a table of how that month's requests were classified by client
and by network type. The quarterly table gains the same splits per month and the number of
labelled days.

A selection export fetches each selected station's file separately under the export label, so one
export can add thousands of counted downloads. The screen therefore shows, directly under the
headline's download line and in a quarterly row after the station files and bundles row, how many of
a month's downloads came from selection exports and in how many exports. The export count is
distinct masked networks per day that took a labelled file, so two exports from one network on one
day read as one: it is a floor, not a count of export actions. Both figures are reported monthly and
cumulatively only, never crossed with country, state, survey or dataset; the permanent daily record
keeps each day's export counts beside its other pure counts. A month before the selection split
began reads "not measured". On a month labelled on only some of its days the headline says that the
export figures cover the whole month, unlabelled days included. From
`labels_since` they exclude the operator's own exports, like every other figure.

Labels are reported at month grain only. No audience, client class or network type figure is
given for a single day, and none is crossed with country, state, survey or dataset: the survey
and country exports keep their columns, and the country, state, survey and top-dataset tables
only say that, from `labels_since`, operator requests are excluded from them. The cumulative
cards include the operator's own requests before that date and exclude them from it.

Where an input was missing the screen says so rather than letting the split look complete: a
month whose network-type table or operator list was unavailable on some labelled days names how
many, and so does a month labelled on only some of its active days. Once any month shown is
labelled, a month folded before labels began reads "not measured" on every label row; before that
the label rows are not shown. A labelled month whose only requests so far were the operator's or
a declared crawler's shows those lines and zero for everything else.

The monthly CSV export carries the same month figures in fixed columns after `detail_days`:
`label_days`, `nettype_days`, `nettype_full_days` and `operator_list_days`; people, automated and
unclassified for downloads, visits, API requests and hand-offs; the operator's downloads, visits,
API requests, hand-offs and download bytes; the declared crawler requests per metric; and
downloads by client class and by network type. Every one of those cells is empty, never 0, for a
month without labelled days. After them come `downloads_select_bulk`, `downloads_select_single` and
`bulk_export_events`, empty for a month the selection split did not cover. `downloads_browser` and `downloads_scripted` are unchanged: they are a
user-agent split only, and a browser-like user-agent is not evidence of a person.

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

## Network type data attribution

Hosting ranges: X4BNet lists_vpn, built in part from IPLocate.io data (CC BY-SA 4.0).

The publisher of the X4BNet lists states no licence for them. Without the derived table every network
reads unknown and the other figures are unaffected. The attribution is also carried in the header of
the derived table. When the full table is built, network types also come from PeeringDB,
and prefix to network from iptoasn.com (PDDL). The derived table holds IP ranges and a type only: no
network number, organisation name or domain.

## Operating it

The aggregator runs as a daily host timer and the workbench Analytics screen (under Operations) renders
the result. Installing the timer, refreshing the DB-IP Country CSV and rebuilding the state table and
the network-type table are documented in `deploy/README.md` under "Usage analytics".
