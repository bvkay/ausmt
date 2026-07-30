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
`networks_peak` so the reach proxy outlives the 92-day daily window, and `total_served_surveys` as
the denominator for "N surveys downloaded". The monthly export gains `geo_days`, `networks_peak` and
the client split; the per-survey export gains the country count.

`geo_days` closes the trap that ranked highest here. Per-month country counts are forward-only, so
`au_requests` can be derived from one day of a full month while every `state_*` column reconciles to
it exactly. The row looks self-consistent and under-reports, and it is the file that leaves the
building.

### Deploy note

`caddy validate` does not run on a dev box, so the two Caddyfile changes (`roll_uncompressed`, the
release force-download pattern) are pinned by config assertions in `deploy/tests`; the image build's
own `caddy validate` is the syntax gate.

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
