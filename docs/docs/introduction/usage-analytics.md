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
| Downloads by collection | The `collection_id` of the survey, from the served catalogue document. A collection's total is the sum of its member surveys, counted forward only from the fold that began reading collections; earlier downloads are not credited to any collection. |
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
| Raw access log (masked) | about 7 days, including the copies the nightly count pulls, which are removed once counted and more than 7 days old | debugging only |
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
its own start date and the Usage page names that day.

## Australian traffic by state, and why not by city

The curator Usage page can show Australian visits by state or territory, and it stops there. A /24 or
/48 prefix cannot place a request in a city (mobile carriers and CGNAT pools serve a state from one
prefix), and a city cell would be quasi-identifying in a research community this small. There is no city
dimension anywhere in the pipeline; the city and coordinate columns of the source dataset are read only
to be discarded. Country and state counts exist at the monthly and cumulative grains only, and the daily
archive carries no geography.

The state card on the Usage page is in visits over all time. It lists each state or territory the fold
counted, then a "Not placed in a state" row, then an Australia total. The total is the Australian visits
of the country detail, the same figure the countries card prints, and the remainder row is that
total less the named states: it covers visits the state table did not place and every day counted before
the table was loaded. A state counted before the visit detail existed reads "not measured". If the named
states ever came to more than the Australian total, the card would show no rows and say the figures are
not reconciled. Where the fold counted no state the card reads "Not measured yet." The exact request
total, where the state columns add up to the Australian request figure, is a property of the monthly CSV
export and is described in the operator guide.

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
  catalogue loads and other requests are not. The tool class includes what earlier versions of the
  curator page reported as scripted clients;
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

The curator Usage page turns the client class and the network type into three audiences. They are
worked out from the stored monthly counts each time the page is drawn and are never stored
themselves:

- **people**: portal sessions and landing-page visitors, on any network;
- **automated**: tools, plus unknown clients on hosting networks;
- **unclassified**: every other request. It is never guessed, and it may include people.

People is therefore a floor. A person on a commercial VPN, or a university job in a public cloud,
reads hosting; a script that opens the portal first and fetches 50 files or fewer a day reads as
people. The who card describes the last full month, the same month as the figures above it, when that
month is labelled. When it is not, and the month in progress carries labelled days, the card
describes the month in progress so far. It shows four rows, downloads, portal visits, API requests
and time-series hand-offs, each as a bar split three ways with the numbers printed beside it, then
one line with the operator's own requests and declared crawler requests left out. A collapsed table
under it gives that month's requests by client class and, where a network table was used, by network
type. Before any labelled month the card gives the configured start date when one is set, and
otherwise reads "Not measured yet".

A selection export fetches each selected station's file separately under the export label, so one
export can add thousands of counted downloads. The page therefore shows, under the downloads figure
and in the month table, how many of a month's downloads came from selection exports and in how many
exports. The export count is distinct masked networks per day that took a labelled file, so two
exports from one network on one day read as one: it is a floor, not a count of export actions. The
citation pack is a separate export the portal builds in the browser, and the log cannot count it.
Both figures are reported monthly and cumulatively only, never crossed with country, state, survey or
dataset; the permanent daily record keeps each day's export counts beside its other pure counts. A
month before the selection split began reads "not measured". From `labels_since` they exclude the
operator's own exports, like every other figure.

Labels are reported at month grain only. No audience, client class or network type figure is
given for a single day, and none is crossed with country, state, survey or dataset: the survey
and country exports keep their columns, and the survey, country and state figures only say that,
from `labels_since`, operator requests are excluded from them. The cumulative figures include the
operator's own requests before that date and exclude them from it.

Where an input was missing the page says so rather than letting the split look complete: one warning
line names a month labelled on only some of its active days, and how many labelled days lacked the
operator list or, where a network table is used, the network-type table or its full sources. On such a month every figure above the who card, the
selection export figures included, also counts the operator's requests on the unlabelled days. A table
counts as unavailable when it is missing, unreadable, without a valid header or older than its age
limit, so there is no single fixed cause; the fold journal names it. A month folded before labels
began shows no label figure. A labelled month whose only requests so far were the operator's or a
declared crawler's shows those lines and none for everything else.

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

## Reading the curator Usage page

The curator Usage page keeps its own wording short and leaves the method to this page. Every
counting rule it relies on is stated once above: what is measured and how a download is counted,
the [privacy design](#privacy-design), [retention](#retention-of-the-aggregates), the
[state card](#australian-traffic-by-state-and-why-not-by-city), the
[operator](#operator-requests), [client class](#client-class) and [network type](#network-type)
labels, [who made the requests](#who-made-the-requests) and the
[attributions](#geolocation-data-attribution). This section adds only what is particular to the page.

### The figures on the page

The tiles describe the last full month: the month of the data date when that date is a month end,
and otherwise the month before. Each tile compares with the month before it in whole percent, and
says so when that month has no row, was not measured, or was only partly counted because counting
began inside it. The month in progress gets one line of its own, to the data date.

The country count on the tile and on the countries card leaves unknown out of every country count,
so it can read one lower than the number of country rows in the monthly country export
(`analytics-countries.csv`). The count of served surveys the earlier screen printed beside the
survey count is kept in `stats.json` only and is in no export.

Single files are the station files less the selection export files. The fold does not cross the two,
so the figure reads "not measured" when either input is missing or the difference would be negative.

Hand-offs the register no longer lists are counted as unattributed hand-offs, a figure kept in
`stats.json` only; a non-zero figure there is register drift, the route table and the served data out of step, not lost requests.

### Seams in the record

The general rule is in [retention](#retention-of-the-aggregates). Two seams are named. The first is
`detail_since`: a month folded before the detailed breakdown existed carries real downloads and
visits and nothing finer, so its volume, formats, kinds, API requests and countries read "not
measured", and the month table's caption names that date. The second has no recorded date: the
counting rules the fold uses now (the client split, the within-day download dedupe, API geography,
the per-survey country count and the monthly network peak) began later, and a month folded between
the two seams reads "not measured" for those figures. Its bias runs in both directions: under the earlier
rules every request counted, so one repeated or resumed transfer counted twice, while scripted clients
were discarded as robots and ranged transfers were not admitted at all. The net is not recoverable, so
an older month can read higher or lower than the same traffic would today.

API requests count toward a country only from the fold that began counting them, so an older
country figure covers downloads and visits alone.

### Health line

The health line under the notes gives the data date, when the last nightly count finished, and the
day the permanent daily archive was last written through. The page reads the archive only through
that one date in `stats.json`. A count is late when none has finished for two timer periods, 48 hours
at the shipped daily cadence; a file stamped in the future also reads late. The page then marks the
header stale and warns, and still shows every figure as it was at that time. When the archive date is
earlier than the data date the page warns that the archive stops at that date, so later days are not
in the permanent record. When no archive date is recorded it warns that the date is not recorded;
a file written before the fold began recording the date reads that way until the first nightly
append after the upgrade. When the count is also late, one warning names both. The fold journal says
why, and the operator guide describes how to restore the archive. Days
the archive missed are not backfilled, so the warning clears once appends succeed again while the gap
stays.

### What the page leaves to the CSV exports

These figures were on the earlier curator screen and are now in the CSV exports only. The monthly
export carries the reach figure, `networks_peak`; the browser and scripted split, `downloads_browser`
and `downloads_scripted`; the per-month label columns; unattributed downloads, `unattributed`; and the
per-state request columns, `state_*`. The survey export carries each survey's country count and file
and bundle split, `countries`, `files` and `bundles`. The country export carries each country's
`requests`, `api` and `download_bytes`.

Four figures the earlier screen showed are kept in `stats.json` only, and are neither shown nor
exported: the top datasets, downloads by collection (see the collection row under
[what is measured](#what-is-measured)), hand-off volume, and the count of served surveys. Monthly
hand-off requests are shown in the month table; the monthly export carries them only as the label
split of a labelled month.

The month table shows every retained month, and every export carries
every retained month too. The operator guide (`deploy/README.md`) describes each export column by
column.

## Operating it

The aggregator runs as a daily host timer and the curator Usage page (under Operations) renders the
result. Before the first nightly count has written its file the page says so and shows no figure.
Installing the timer, refreshing the DB-IP Country CSV and rebuilding the state table and the
network-type table are documented in `deploy/README.md` under "Usage analytics".
