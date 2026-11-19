# C45 — Usage analytics (design record)

Owner directive (Ben, 2026-07-11): "stats, how much is getting downloaded, which datasets, maybe
from which country... how many views... analytics is very useful from a research infrastructure
view point." The consumers are AuScope reporting and custodian conversations ("your survey was
downloaded N times from M countries"), not ad-tech.

## D1. Current state (verified 2026-07-12, recon at main @ 3b806ad)

* **No access log exists.** The single Caddyfile (`deploy/docker/caddy/Caddyfile`, baked into the
  portal image) has no `log` directive anywhere; Caddy's default is logging OFF. Nothing HTTP-level
  is recorded today. Insertion point: the `:8080` site block (`Caddyfile:39-112`), or scoped to
  `handle_path /data/*` (`:74-83`).
* **Downloads are the only server-observable per-dataset signal.** Served download surfaces (all
  under `/data/…`): per-station `edi/<slug>/<file>.edi` and `xml/<slug>/<file>.xml`, per-survey
  `bundles/<slug>-edi.zip` / `-xml.zip` / `-tf.h5` (flag-gated, default off). `manifest.json` is the
  authoritative reverse map `url → {ausmt_id|slug, survey}` (`build_portal.py:305-320`). The
  `@download` matcher also names `/h5/*`, which has **no producer** — latent path, ignore.
  *(SUPERSEDED 2026-08-03: the tier-1 lane created the producer. `/data/h5/<slug>/<station>.h5` is a
  real served family, `h5` is in `_DOWNLOAD_FAMILIES`, and the recon fact above holds only as of the
  dated verification.)*
* **Per-dataset "views" are structurally uncountable server-side.** The portal is a hash-routed SPA
  that loads the corpus JSONs once at boot; `#/station/…`, `#/survey/…`, `#/collection/…` render
  from memory with **zero** per-navigation HTTP requests (`main.js:124-137`, `drawer.js:115-169`).
  The drawer's "Planned read API" block is display text, not wired. The only post-boot requests are
  user-initiated downloads and corpus-wide overlay layers.
* **A client-side event hook already exists, OFF by default:** `window.track(name, props)` —
  property-only, identifier-free (`analytics-shim.js:7-9`); fires `DownloadGenerated` etc.; reaches
  a backend only if Plausible is enabled (`config.js:15-18`, default off).
* **The public promise (binding constraint):** `portal/index.html:7-11` — "cookieless, no IPs
  stored, no cross-site tracking … AusMT deliberately collects NO personal data." There is zero
  GeoIP precedent in the repo.
* **The facts-for-gateway seam exists and is proven:** host timers write JSON into the state dir
  (`$AUSMT_DATA_DIR/gateway/state` ⇄ `/gw/state`) via mktemp→chmod 0644→mv -f; the gateway reads
  fail-closed with a both-directions staleness band (`serve_state.py:82-139`; writers `alert.sh`,
  `reconcile.sh`). systemd oneshot+timer pattern in `deploy/systemd/`. This record adds one more
  writer and one more file — no new pattern.

## D2. Privacy design (the load-bearing section)

The promise "no personal data" is a feature, not an obstacle — research-infrastructure analytics
needs aggregates, never identities. Design:

* **IPs are masked at the edge.** The Caddy `log` block writes JSON with the client address
  **truncated at write time** via Caddy's built-in log filtering (IPv4 → /24, IPv6 → /48 class;
  exact directive verified at contract time — prescribe intent, not idiom). A full IP never
  touches disk. Logged fields are minimal: timestamp, method, path, status, bytes, masked address,
  user-agent (bot filtering only). No cookies, no referrer bodies, no headers beyond UA.
* **Country resolution WITHOUT MaxMind:** the aggregator resolves the masked address to a country
  using the **db-ip.com "IP to Country Lite"** dataset — CC-BY-4.0, no account, no license key, a
  monthly CSV of ranges that a **stdlib** bisect lookup reads directly (no `maxminddb` dependency,
  no geoipupdate tooling, no MaxMind EULA custody). /24-masked IPv4 resolves country correctly in
  the overwhelming case; wrong-country noise at the margin is acceptable for aggregate reporting.
  Attribution line in docs/about (CC-BY requirement). The CSV refresh is a documented operator
  chore (stale data degrades gracefully — countries drift slowly).
* **Aggregates only leave the pipeline.** `stats.json` carries counts (downloads by dataset/format,
  visits, countries, dailies) — never an address, masked or otherwise, never a UA string. A leak
  pin enforces this (D6).
* **Raw log retention is short and stated:** rotated by Caddy, deleted after 7 days (aggregation
  runs daily — the tail exists only for debugging). Retention is config, pinned in the deploy
  tests.
* **The public promise text is AMENDED, honestly, in the same lane that enables logging** (owner
  eyes required — it is a public commitment): "server logs truncate IP addresses at the edge;
  only aggregate counts are kept; no cookies, no cross-site tracking, no personal data." The
  current absolute "no IPs stored" would otherwise be false the moment a log line lands.
* Naming note: the no-SMTP-on-box posture is exactly that — do NOT label it "A3" (in this repo
  A3 is a C18 cache amendment). Nothing here sends mail; the analytics pipeline is box-local.

## D3. Metrics v1 (what ships) — and the honest non-metrics

**Ships:** downloads by survey / station / format (log path × manifest reverse map); total portal
visits (proxy: `catalogue.json` fetches — one per SPA boot); downloads+visits by country
(aggregate); top-N datasets; daily time series. All computed from the access log alone.

**Does NOT ship, stated honestly:**
* **Per-station/per-survey VIEWS** — impossible from server logs (D1). If per-dataset views are
  ever wanted, that is a **first-party beacon decision** (the existing `track()` shim + a tiny
  same-origin collector, or self-hosted Plausible) — a separate owner decision with its own
  privacy review. This record deliberately does not smuggle it in.
* User identification, sessions, funnels — never. Not a growth product.

## D4. Pipeline architecture

```
Caddy (portal container)                 host (operator uid)                    gateway (uid 10002)
  log block: JSON, masked-at-edge  →  ausmt-stats.{service,timer}, daily   →  Analytics screen reads
  fields-minimal, rotated, 7d         python3 STDLIB aggregator:              stats.json from the
  volume-mounted logs dir             logs × manifest.json × dbip.csv         state dir (read-only,
                                      → stats.json (mktemp→mv, state dir)     staleness chip, ops-
                                      raw lines discarded after aggregation   floor pattern)
```

* The aggregator is a host-side stdlib-python script in `deploy/scripts/` (the `alert.sh`-writer
  class: never raises into the timer, atomic writes, 0644 before rename, shared timestamp format).
* `stats.json` is cumulative (the aggregator folds each day into running totals + a bounded
  daily tail); the raw logs are NOT the database — losing them loses nothing already folded.
* The workbench **Analytics screen** is a read-only gateway page (Operations group) rendering
  stats.json: summary cards, top datasets table, country table, daily sparkline. Same trust class
  as the ops floor (no new privilege, C40 intact). Served-lag honesty: the screen shows the
  aggregator's `generated_at` + a stale chip past 2 periods.
* **NCI portability:** the whole pipeline is files + a timer + a static dataset — nothing
  box-specific. At NCI the same Caddyfile block + timer recipe move across.

## D5. Lane split

* **Enablement rides 2b-ii (deploy lane, EARLY — owner-agreed 2026-07-11):** the Caddyfile `log`
  block + masked-address filter + logs volume mount + rotation/retention + the portal promise-text
  amendment. Rationale: baseline history starts accruing immediately, pre-NCI, even before the
  aggregator exists.
* **C45-impl lane (after 2b-ii):** the aggregator script + dbip CSV custody + `ausmt-stats`
  systemd pair + stats.json contract + the workbench Analytics screen + docs (attribution,
  operator chores, retention statement).

## D6. Verification (Invariant 10 — the implementation lanes carry these)

* **Masked-at-edge pin:** a request through the real Caddy config writes a log line whose address
  field is truncated (never a full IPv4/IPv6) — proven against a live Caddy in the deploy harness,
  red-then-green vs an unfiltered log block.
* **Leak pin (stats.json):** the emitted stats.json contains no IP-like token (v4 or v6, masked or
  not) and no UA string — artifact-level sweep, the C42 leak-sweep spirit.
* **Attribution pin:** aggregator over an engine-truth fixture (real manifest.json + synthetic log
  lines for its real URLs) attributes downloads to the right survey/station/format; unknown paths
  land in an `unattributed` bucket, never dropped silently.
* **Country pin:** bisect lookup over a fixture CSV resolves known ranges; masked addresses
  resolve; a missing/stale CSV degrades to `unknown` country, never crashes the aggregator.
* **Retention pin:** the rotation/retention config exists and the aggregator tolerates absent
  (already-rotated) logs.
* **Staleness pin:** the Analytics screen shows the stale chip on an old `generated_at` (the
  serve_state band pattern, fail-closed both directions).
* **Promise-consistency check:** the portal promise text and the shipped behaviour are reviewed
  together at the gate — a public commitment and its implementation must not diverge.

## Provenance

Owner directive 2026-07-11 (in-session, task #14). Recon 2026-07-12 (Caddyfile, portal routing,
state-dir seam, privacy anchors — file:line cited in D1). Prior decisions folded in: enablement
rides 2b-ii (2026-07-11); phase-1 = logs only, beacon = explicit later decision (2026-07-11).

## D7. Counting honesty, and state/funding detail (2026-07-30)

A four-agent read of the shipped pipeline against the live screen. Every item below is a change to
what is counted or to what a figure claims, not a new collection: the fold still reads only the
request path, the masked network, the response size, and the user-agent it discards.

### Rotation coverage

Caddy compresses a rolled log by default. Both consumers keyed on the plain `.json` name, so a roll
was neither shipped from the front door nor folded on the box, and because the fold advances its
watermark past a day whether or not it saw lines for it, those requests were lost rather than late.
Both Caddyfiles now set `roll_uncompressed`; the aggregator and the ship filter also carry the
`.gz` family as a salvage arm for the transition window.

### What counts as a client

The bot filter was a binary and put `curl`, `wget` and `python-requests` on the bot side, which are
the clients the published API reference hands people. Three classes now: **crawler** (excluded, as
bots were), **scripted** (counted, and reported as its own share of downloads), **browser**. An
absent user-agent is scripted, not human. The user-agent is still read transiently and never stored,
so the privacy invariant is untouched and the leak pins carry the new fields.

### What counts as a download

Admission gains status 206, and within one folded day an identical (masked network, path) counts
once. One save action logs two requests on a `Content-Disposition` path (renderer cancels, download
manager refetches) and a ranged transfer logs one per range, so the previous rule double-counted the
headline figure while making resumed transfers invisible. Bytes of every request still sum. The
dedupe set is run-local, built from the masked network, and never written. Visits and API requests
are not deduped.

### Surfaces that were counted nowhere

`/data/mtcat.schema.json` is the `$id` the MTCAT document declares, so it is the cleanest
machine-consumer signal in the corpus; it is now the third API path. `/data/releases/<tag>/bundles/`
holds the citable frozen copy a DOI resolves to, and classified as `ignore` while its mutable twin
counted: it is now a download, attributed by bundle filename against the live manifest, keeping its
own dataset row. The same missing-prefix cause (the matcher runs after `handle_path` strips `/data`)
left those paths out of Caddy's force-download matcher on both listeners; fixed there too. The
licence sidecars beside each survey MTH5 are ignored, because `unattributed` exists to detect
build/serve skew and nineteen structural sidecars drown that signal. Aggregator-side deliberately:
the engine must keep writing the sidecar beside the bytes.

### Geography

API requests now count toward their country and, for Australia, their state. Geography follows the
counted download rather than the log line, so the country map totals exactly downloads plus visits
plus API requests, and both table captions state that scope.

### What the screen may not claim

A month every folded day of which predates the detailed dimensions renders `not measured` rather
than `0 B`, `0 / 0` and a top survey drawn from nothing. This is the omit-rather-than-fabricate rule
the state table already applied at section grain, applied at cell grain. Both partial-dimension
disclosures now enumerate countries and unattributed; their absence is what made a month reading
"Countries: 1" beneath a headline of 11 look like an arithmetic fault. The reach note names the date
it actually shows (the most recent day with a network count, not the fold watermark), and the
Countries card states that it excludes `unknown`.

### State and funding detail

`by_state` is untouched: the reconciliation rows and the exact-total promise against the AU country
row are built on it. A parallel `by_state_detail` map splits the same requests into downloads,
visits, API requests and bytes, at the cumulative and month grains only. **The ratified exclusions
stand**: no city dimension, and no state figure for any single day. The detail columns are
forward-only and read `not measured` where they were not.

Three further figures a report needs and could not get: a per-survey country **count** (the custodian
sentence, with the list held at country grain and never rendered or exported), a per-month
`networks_peak` so the reach proxy outlives the daily window, and `total_served_surveys` as
the denominator for "N surveys downloaded". The monthly export gains `geo_days`, `networks_peak` and
the client split; the per-survey export gains the country count.

`geo_days` closes the trap that ranked highest here. Per-month country counts are forward-only, so
`au_requests` can be derived from one day of a full month while every `state_*` column reconciles to
it exactly. The row looks self-consistent and under-reports, and it is the file that leaves the
building.

### Deploy note

The two Caddyfile changes (`roll_uncompressed`, the release force-download pattern) are pinned by
config assertions in `deploy/tests`, and by a live `caddy validate` leg that runs wherever a caddy
binary is on PATH (`test_caddy_log_masking.py`, `test_frontdoor_bridge.py`; both skip where it is
not, and CI has it). Both edited Caddyfiles validate. The image build's own `caddy validate` remains
the last gate before the box serves either of them.

## D7.1. The second forward-only seam (2026-07-30)

Review of D7 found the same fabricated-zero defect one seam later than the rule that forbids it.
`detail_since` is the v1 to v2 hinge. Every dimension D7 added began months after it, so a month
folded between the two carries a real volume and a real format split beside no client split, no
network peak and no per-survey country count, and `seeded_days` (which marks only the first seam)
never fires for it. The screen rendered `0`, `0 / 0` and `0 countries` for months holding tens of
real downloads, and contradicted itself on one page: the reach note read a real peak off the
surviving daily rows while the month row above it read zero.

Each month now records `detail_days`, the count of its days folded under the current counting rules,
incremented in the same loop as `days`. It is an exact statement rather than an inference from a
zero: every day this fold folds is folded with every dimension it knows about, so a month carried
forward from an older file gains detail only for the days added from here on.

What follows from it:

- the quarterly peak and client rows read `not measured` at the second seam, as the older rows
  already did at the first;
- the detail caveat splits in two. The dated sentence keeps the dimensions that really do start at
  `detail_since`; the rest are named in their own sentence which claims no date, because that fold
  date is recorded nowhere and claiming the earlier one overstates coverage by the distance between
  the seams;
- the country table states that API requests joined the map later than the downloads and visits
  beside them, and states it only on a box whose history predates that;
- the per-survey country column distinguishes an empty code list (unmeasured) from codes that all
  resolved to `unknown` (measured, no country), because the fold records `unknown` as a code;
- `analytics.csv` gains `detail_days` and leaves `geo_days`, `networks_peak` and the two client
  columns EMPTY on a month that measured none of them, as `analytics-surveys.csv` does for its
  country cell. A zero in the file outlives the screen that would have said `not measured`.

Separately, the "N of M served" ratio is dropped when the numerator exceeds the denominator.
`by_survey` accumulates every survey ever downloaded and nothing prunes it, while the denominator is
restamped from the manifest being served now, so withdrawing one survey with historical downloads
renders an honest "41 of 40 served". Label counting closed the slug-versus-label case only.

## D8. The daily aggregate archive (2026-07-30)

Owner ruling: capture maximal non-geographic granularity at day grain now, so a report nobody has
asked for yet can still be derived later. "We do not want to limit ourselves."

The problem it closes is retroactive. The raw log rotates in about a week; the daily rows in
`stats.json` roll off after the daily window (184 days by default); only the calendar-month rollup
is permanent. Every question finer than a month therefore becomes unanswerable once the window passes, and it becomes
unanswerable about days we *did* fold: the data existed, the fold read it, and the detail was
discarded. Monthly rollups were built to survive daily pruning; this is the same argument one grain
down.

**Shape.** After the fold, one JSON line per newly folded day is appended to
`daily_archive.jsonl` beside `stats.json` (`AUSMT_STATS_DAILY_ARCHIVE` overrides the path). A line
carries `date`, the day's `downloads` / `visits` / `api` / `networks` / `download_bytes` /
`unattributed`, and the `by_format`, `by_kind`, `by_client`, `by_survey`, `by_dataset` and
`by_collection` maps, plus `served_build` where the served tree names itself. Sparse: only nonzero
entries are written, so a quiet day is a short line rather than a wall of zeroes that would read as
measured absence.

**Invariants.**

- *Append-only, once per day.* The fold watermark already guarantees a day folds exactly once, so
  the rows come only from the days this call folded and a rerun appends nothing. The append happens
  AFTER `stats.json` lands, deliberately: a failed stats write leaves the watermark where it was and
  those days fold again next run, so they must not already be in the file. The reverse failure loses
  a day from the archive, which is the tolerable direction and is why it is warned about loudly.
- *Never read.* No gateway route, no render path, no export opens it. It lives in the gateway state
  dir, outside `site-data/`, so nothing can serve it. Both facts are pinned in `deploy/tests`.
- *Never pruned, never rewritten.* It is the durable record; that is its whole purpose.
- *Never fatal.* A write failure warns and the fold still counts as done.

**The geographic boundary, which is the line that must not move.** The ratified exclusion of
day-by-state data generalises: no country and no state below the monthly grain, rendered OR
retained. A named country on a named day is a smaller cell than the named state in a named month
that was already ruled out. So the archive carries no country, no state, no address, no user-agent
and no per-network datum beyond the scalar count, and the leak sweep runs over it exactly as it runs
over `stats.json`.

### Collection rollup

A download is now credited to the programme its survey belongs to, from the served `mtcat.json`'s
`collection_id`, at the cumulative and month grains and in the archive line. The join is on the
bundle **slug** first and the survey **title** second: a slug is an identifier, a title is prose
that can be re-worded between builds. The map is keyed on the survey label like every other
per-survey map here, so a collection total is exactly the sum of its members and a reader can check
it by eye. Optional in the way the state table is: no served `mtcat.json`, no dimension, no zero.

It is rendered as one line under the cards, with its own one-sentence caveat rather than borrowing a
seam marker. This is a THIRD forward-only starting point, younger than both `seeded_days` and
`detail_days`, and neither of those speaks for it; naming it under either would overstate its
coverage by the same distance the D7.1 review found. It is deliberately not a quarterly-table row:
that would need a fourth per-month coverage counter to avoid rendering a zero nobody measured, and
the month data rides in `stats.json` and the archive for whenever a report actually wants it.

Tier-3 collection bundles do not exist yet. When they do they arrive as ordinary manifest bundle
rows and flow through the download path already; the latent case is noted in `build_collection_map`
so it is recognised rather than rediscovered.

### Unreadable log files are visible now

Verified incident, 2026-07-30: the box's `access.json` was `root:root 0600`. `read_log_lines` hit
`OSError` and continued silently, so the fold ran for days on the shipped front-door file alone and
wrote a complete-looking `stats.json` the whole time. Tolerant was never meant to mean silent. A
file the glob MATCHED but could not OPEN is now named on stderr and counted into `files_skipped=` on
the journal line. The posture is unchanged: it still never raises.

A gzip archive keeps the distinction it earns. Failing to open it is the same operational fault and
is reported; opening it and finding it is not a gzip stream is the documented salvage case, expected
of a hand-placed or half-pulled archive, and stays a silent skip so a routine recovery does not
become a nightly warning.

### Backfill: dropped

The July 2026 rotation-loss window (27 Jul 00:00 to 28 Jul 13:27 UTC, dropped before folding) is
accepted as-is by owner ruling: the site is not publicly launched, so pre-DNS numbers are not a
reporting baseline. No backfill machinery exists and none was built. **"Nothing is backfilled" stays
absolute.** The salvaged raw files remain on the box at zero cost.

## D9. Request labels

Three labels per admitted request, derived at fold time from fields the fold already reads plus the
name of the log file a line came from: operator, client class and network type. No edge change and no
header beyond the user-agent. This section records the switch and the three labels.

### The switch and rollback

`AUSMT_STATS_LABELS_FROM` in the host `.env`, a first-of-month date. Absent, malformed or mid-month,
labels are off and the fold output is byte-identical to the unlabelled fold across successive folds
(pinned against golden output of the unlabelled fold). A day D is labelled when D >= that date; every
other day folds exactly as before. Removing the setting is the soft rollback: labelling stops at the
next fold and the label blocks already folded are carried forward. A set but rejected value prints
`labels=off from=invalid` in the journal, without echoing it. `labels_since` is stamped once, at
the first labelled day folded, and never moved.

The full code revert restores nothing: the unlabelled fold drops `labels_since` and every label block
at its next run and keeps every other figure. Days folded from `labels_since` keep their exclusion of
operator requests, and their archive lines keep their label keys. Restoring an earlier `stats.json`
would lose every figure folded since it, and those days cannot be refolded once their logs rotate.

With labels off, or set for a month not yet reached, each line is parsed and folded in turn and none
is kept, as before labels, and the log is read as plain lines with no source. Only a fold that
reaches a labelled day holds its window of parsed records (as slotted objects, not dicts) for the
pre-pass.

### Operator

Closed set yes, no, unknown; unknown counts as not operator. The first match is yes:

1. the line came from the box listener's own log, matched positively by name (`access.json` or a
   Caddy roll of it). That listener is published on loopback only, so curators browsing the box over
   the tailnet are operator. A file of any other name is read as front door and counted in the
   journal as `other_files`;
2. the user-agent opens with `ausmt-ops/`. The repository's jobs send `ausmt-ops/1-<job>`: the
   three doctors append `-A ausmt-ops/1-doctor-frontdoor`, `-doctor-serve` or `-doctor-box` after
   the `AUSMT_DOCTOR_CURL` override, so a stub or wrapper keeps it, and both `make smoke` curls
   send `ausmt-ops/1-smoke`. The token has no space because `$CURL` expands unquoted at every call
   site. The name is public: a third party sending it only moves its own requests onto the
   operator line;
3. the masked address is in a fixed in-code list of loopback, private, link-local, shared and
   unspecified ranges. It is never `is_private`, which also covers the documentation ranges;
4. the masked address is inside an entry of the host operator list.

Otherwise no when the list was read (loaded, empty or partial), and unknown when it is absent or
unreadable. An operator request is counted on the operator line (downloads, visits, API requests,
hand-offs, download bytes; request counts, not de-duplicated) in the totals and its month, and
reaches no other figure, day row or archive line. A fault in the label code costs that request its
labels, never the request or the fold, and is counted as `label_fallbacks`.

Each labelled month carries `label_days` and `operator_list_days`, so a month whose operator list
was missing on some days says so rather than looking complete. The operator list and the network
table loaders never raise: a path the fold account cannot reach, including a directory it cannot
enter, reads `unreadable`.

### Client class

Non-operator requests only. Closed set portal_session, landing_page, tool, unknown. Precedence:

1. a declared crawler (classify_client) has no class: it stays excluded and each admitted crawler
   request on a labelled day is tallied, not de-duplicated, in `crawler_excluded` at cumulative,
   month and archive grain (the archive tally only on a day with counted activity);
2. tool: classify_client returns scripted (a scripted token or an empty user-agent);
3. tool, downloads only: the triple (day, masked network, exact user-agent) fetched more than
   `SWEEP_DISTINCT_FILES` = 50 distinct download paths without the export label that day. Every
   download of that triple that day is tool. Its visits, API requests and hand-offs, and other
   user-agents on the same network, are not swept;
4. portal_session: the network had an admitted catalogue load (200 or 304), or a request carrying the
   export label answered 200 or 206, that day or the day before;
5. landing_page: the network had a `/surveys/` or `/collections/` page answered 200 or 304 that day
   or the day before;
6. unknown.

The evidence (4, 5) and the sweep (3) come from a pre-pass over non-operator, browser-like records
from the day before labels start, or the day before the first new day if later, to the cutoff. Each
log line is parsed once into a reduced record that both passes read; the records keep the day of the
prior watermark so it can serve as evidence, and the fold still skips it. The sets are built from the
masked address and the transient user-agent, are never written, and die with the process. If the
pre-pass raises, the sets are emptied, every browser-like request reads unknown, counting continues,
and the journal says `prepass=failed`.

A deduplicated download takes the class of the counted line. The totals and each month carry
`labels`, a map per metric (downloads, visits, api, handoffs) of `<client>|<nettype>` counts that
sums to the figure counted on labelled days (on a month labelled on only some of its days, the
month's figure is larger by its unlabelled days). A labelled archive day carries `labelled: true`, `by_client_class` (per metric, by class) and `crawler_excluded`, and no
network type, operator figure, address or user-agent. The browser and scripted split is unchanged.
The journal also carries `fold_seconds`, the run time of the fold, for comparison with the unit's
start timeout.

### Network type

Non-operator requests only. Closed set hosting, education_research, access_provider, other,
unknown. `NetTypes` (a `_RangeTable`) looks up the masked address in
`$AUSMT_DATA_DIR/geoip/nettype.csv` (`AUSMT_STATS_NETTYPE_CSV`); its value hook accepts only the
four stored types, so unknown is the miss and is never stored. Government, enterprise, transit and
every other source type fold into other, so that no value points at a single agency.

The table is built by `deploy/scripts/prep_nettype.py`: stdlib only, no network call, ranges widened
to /24 and /48, overlaps resolved hosting first, rows sorted and disjoint because the lookup tests a
single bisect candidate. No AS number, organisation name or domain is written. The default build is
hosting only, from the X4BNet datacenter lists (the publisher states no licence; built in part
from IPLocate.io data, CC BY-SA 4.0); the full build adds iptoasn.com (PDDL) prefixes typed from a
PeeringDB net table, and waits on a reading of the PeeringDB terms for a stored snapshot. The table
header carries the attribution lines.

The first line, `# ausmt-nettype v1 built=... oldest_source=... sources=...`, gates the table. States:
absent; unreadable (an error reading it, or no valid row); stale (header missing or unparseable, or
oldest_source more than `AUSMT_STATS_NETTYPE_MAX_AGE_DAYS`, default 45, days before the run date);
aging (in date but past half that age, a journal warning only); loaded. Only loaded and aging tables
are used; otherwise every request reads unknown. Staleness is judged on the oldest source, never the
build date. The table is opened only while labels are on.

Each labelled month carries `nettype_days` (days with a usable table) and `nettype_full_days` (days
whose table names peeringdb among its sources), beside `label_days`. Network type exists only in the
joint `labels` keys at month and cumulative grain: never on a day row or an archive line, and never
crossed with country, state, survey, dataset or collection. The journal prints `nettype=<state>
nettype_rows=N nettype_sources=<list>`. A fault in the lookup falls under the label guard.

### Audience rule and the page

`audience(client, nettype)` in `gateway/curatorpage.py` is a pure function over the stored joint
key and is never stored: tool is automated; portal_session and landing_page are people on any
network; unknown is automated on hosting and unclassified on every other network type. A different
reading of it (for example hosting overriding portal evidence, or landing pages not counting as
people) is a renderer change that needs no refold.

The Analytics screen is server-rendered with no inline script. Its label surfaces are:

- a headline before the cards, built from the latest month carrying `label_days`: people,
  automated and unclassified per metric (hand-offs only when that month carries the hand-off
  class), the operator line with `labels_since`, the declared-crawler total, and an "Inputs
  missing" band in the stale-banner style when `nettype_days` or `operator_list_days` falls short
  of `label_days`. Before any labelled month it reads "not measured";
- a note under the cards that the cumulative figures include the operator before `labels_since`;
- the labels paragraph after the existing intro, and one sentence on the scripted-client
  paragraph, both only once `labels_since` is set, so an unlabelled box reads exactly as before;
- a classification table for that month (client classes, then network types, each summed over
  the other label), a note when some days had a hosting-only table, and the attribution line when
  a shown month has `nettype_days > 0` (PeeringDB and iptoasn.com only when `nettype_full_days >
  0`);
- quarterly rows after the browser and scripted row, reading "not measured" for a month that was
  never labelled and omitted, like the hand-off row, when no shown month is labelled. Seam notes name
  partial labelling, a missing network table, a hosting-only table and a missing operator list;
- a scope line on the survey, top-dataset, country and state tables;
- selection exports beside the download figures, because one export fetches each selected file
  separately and can add thousands of counted downloads. The month row already holds
  `downloads_by_select` and `bulk_export_events`, both excluding operator requests on labelled days,
  so no fold change is needed. A headline line under Downloads ("Selection exports: F files in at
  least E exports.") and a quarterly row after the station files and bundles row ("Selection
  exports: files / exports (at least)") read them, and the labels paragraph says what one export
  does to the count. Month rows carry the split densely, so a month counts as
  measured only when the fold has taken the split, the month carries current-rules days, and it is
  not wholly before `select_since`; otherwise it reads "not measured". On a month labelled on only
  some of its days the headline line adds that it covers the whole month, unlabelled days and the
  operator's exports on them included. The existing bulk export line and its caveat are unchanged.

A month counts as labelled when it carries `label_days`, or an `operator` or `crawler_excluded`
block, which the fold writes only on labelled days. `label_days` counts labelled days with counted
activity, so a labelled month whose only admitted requests were the operator's or a crawler's has
the blocks but no counter; it renders those lines as measured and every public label figure as a
measured zero. The headline and the classification table still describe the latest month with
`label_days`.

`analytics.csv` gains the fixed label columns after `detail_days`, empty rather than 0 for a month
without `label_days`, then `downloads_select_bulk`, `downloads_select_single` and
`bulk_export_events`, empty where the selection split did not cover the month. The survey and
country exports are unchanged, and no label figure is ever
crossed with country, state, survey or dataset.

### History

Nothing before `labels_since` is relabelled or backfilled. The only label that retained aggregates
could support is tool by user-agent, and that is exactly the existing scripted figure already shown
on the browser and scripted row; the sweep did not exist before, so it is not the same measure and
the new rows read "not measured". Every earlier month keeps its figures, including the operator's
own traffic.

### Readings raised separately

These are recorded here and are not changed by the labels:

- D2 says no header beyond the user-agent is logged, while the shipped front-door log filter
  (`deploy/frontdoor/Caddyfile`) deletes seven named headers and keeps the rest. The labels read
  no header beyond the user-agent either way. Which of the two is binding needs its own reading;
  if D2 holds, the fix is to delete more headers at the edge.
- The page states the selection export figure as a floor. `bulk_export_events` is distinct masked
  networks per day, so two exports from one network on one day read as one; the headline line reads
  "in at least E exports", the quarterly row is labelled "(at least)", and no line presents the
  figure as a count of export actions.
- Archive day lines carry `by_client_class` beside `by_survey` and `by_dataset`. They are separate
  marginals, but on a low-traffic day one class or one dataset makes the pair a crossing at day
  grain, finer than anything rendered. Keeping the class at month grain only would need its own
  reading.
- The default operator list path is under `$AUSMT_DATA_DIR`. Whether the host-level backup covers
  that directory, and so holds the list, is not visible from the repository.
- The hosting range source, the X4BNet `lists_vpn` datacenter lists, has no stated licence. Its use
  is an owner decision not yet made. The network-type table is optional: while it is absent every
  network reads unknown and the other labels are unaffected. The full build (iptoasn.com and
  PeeringDB) remains subject to the PeeringDB terms.
- The front-door rolls pulled to the box (`deploy/frontdoor/ship-frontdoor-logs.sh`, rsync without
  `--delete`) are not pruned there, which sits against the public statement that raw logs are kept
  for about seven days (`portal/about.html`). The labels do not read them. Listing and pruning them,
  or restating the retention, is left to the owner.

### Operator list custody

`$AUSMT_DATA_DIR/stats-private/operator-networks.txt`, directory 0700 and file 0600, owned by the
account the fold runs as. It is outside the gateway state dir that `backup.sh` snapshots and the
gateway mounts, and outside every compose volume source, so no route can read it. Entries are widened
to /24 or /48, the grain of the masked address. No entry, count or line number is written to
`stats.json`, the archive or the journal; the journal prints only the list state. If the fold moves to
another host the file moves by hand, never through git.
