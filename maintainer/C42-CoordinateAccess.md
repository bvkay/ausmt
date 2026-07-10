# C42 — Coordinate access model: exact / generalised / withheld (frozen design)

Owner ruling (2026-07-10, audit item 6.1): **the custodian chooses** whether a station's
coordinates are served exact, generalised, or withheld. This record freezes the design.
Status: frozen, pending owner countersign on one flagged call — **D5 repo-visibility
governance** (⚑ inline). A second flag (elevation under generalised) dissolved during
adversarial verification: no served JSON surface carries elevation, and the byte-gate removes
the only bearers — see D2.

## D1. Current state (verified 2026-07-10, main @ 3d4be17)

Coordinates are **universally public by deliberate design** — the access drawer tells readers
"Station locations and survey metadata are public" even for `metadata_only`/`embargoed` surveys
(`portal/src/drawer.js:32,35,38`), and the embargo machinery withholds *bytes and curves only*:
`can_serve` gates EDI/XML/bundles (`engine/extract/build_portal.py:2217`), `withhold_tf_row`/
`withhold_sci_row` empty the display rows in place (`:230-255`), but catalogue lat/lon stay
verbatim "even for withheld surveys" (`:2435-2437`). C42 therefore **revises a design stance**,
not an omission. There is no masking precedent for coordinates; the withhold-in-place pattern
(row kept, values nulled, width preserved) is the alignment-safe template to extend.

Every served coordinate-bearing surface (recon 2026-07-10, all file:line verified):

| Surface | Coords | Producer |
|---|---|---|
| catalogue.json cols 2/3 (`contract/columns.json:3`) | exact, 6 dp | `build_portal.py:2428,2434` |
| mtcat.json station lat/lon + survey bbox/centroid | exact | `:559-561`, `:534-558` |
| collections.json bbox/centroid | exact-derived | `:414-417` |
| products/station.json `location` | exact | `:2281` — **publicly served**: `--products` writes inside the build dir (`deploy/Makefile:84-85`), Caddy has no exclusion (`Caddyfile:74-83`). The ":2271-2276 'not a distribution surface' comment is false in deployment** (latent leak). |
| qc_report.json out-of-extent entries | exact | `:1339`, written into served out/ at `:2410` (latent leak) |
| served EDI bytes + per-survey zip | exact, 3+ header sites (HEAD LAT/LONG/ELEV, INFO, DEFINEMEAS REFLAT/REFLONG) | verbatim byte copy `:2258-2259`; zip `:1680+` |
| served EMTF-XML + derived EDI | exact (coordinates carried through unmodified by mt_metadata's round-trip; normalize applies no coordinate masking) | `ausmt_science/ingest/normalize.py:382,386` |
| portal render + CSV export | exact | `main.js:5` → `map.js:94`, `drawer.js:164`, `exports.js:24-25` |

Not leaking today: tf.json/sci.json/surveys.json/build_report/feed/sitemap carry no coords;
DataCite emission is not implemented (docs-only) — no DOI coordinate leak exists yet, but any
future DataCite lane inherits this record's mask. `access.coordinate_resolution`
(`build_portal.py:1262-1286`) is a DMS **sign-bug QC correction**, unrelated to access — the two
must not be conflated (naming below avoids it). The **lone-station hazard is real**: a
single-station survey's mtcat centroid IS that station's exact position (`:557`).

## D2. Policy model

New survey.yaml fields under the existing `access` section (beside `level`/`embargo_until`):

```yaml
access:
  coordinates: exact | generalised | withheld     # survey default; absent => exact
  coordinate_overrides:                            # optional, per-station
    <STATION_ID>: exact | generalised | withheld
```

* **exact** (default — zero change to every existing survey): serve as recorded.
* **generalised**: lat/lon rounded to **0.1°** (~11 km), fixed precision, a single ENGINE-side
  rounding function — the portal never re-rounds; it renders the masked catalogue value verbatim
  (pinned, D6). Elevation: no served JSON surface carries elevation today, and a non-exact
  station's EDI/XML — the only elevation bearers — are byte-gated out (D3); the mask nulls
  elevation on the record anyway as a **defensive invariant** so any future emitter inherits it,
  and the leak-sweep fixture hunts a distinctive elevation value too.
* **withheld**: lat/lon/elevation all null. The station **keeps its catalogue row** (alignment
  invariant), its curves still serve, it lists in the survey — it simply has no position. The
  survey-level representation is the custodian-declared `geographic_extent` (already in the
  schema, validator `:502-510`) — declared by a human, never computed from the stations it is
  supposed to protect. No extent declared → no survey-level position shown.

Validator enforces the enums and that every override id names a real station file. The portal
badges the state honestly: "position generalised to 0.1° at custodian request" / "position
withheld at custodian request", replacing the universal "locations are public" drawer text with
policy-aware wording.

## D3. The masking seam — one choke point, ordered

Pipeline order is the design's load-bearing rule:

**parse → QC on TRUE coordinates → `apply_coordinate_policy()` in-place → ALL emission.**

QC (extent checks, ~10 m duplicate detection, frame gates) runs on real positions — masking
before QC would blind it. The mask then mutates the station records in place (the
`withhold_tf_row` template) **and explicitly rewrites every coordinate-bearing qc_report field**
— `outside_declared_extent` lat/lon (`:1339`), `near_duplicate_locations.at_deg` (`:1311-1318` —
a 3-dp ROUNDED derivative of the true position, computed inside qc_pass before the mask; a
sneaky leak class), and any future qc coord field. Every emitter downstream — catalogue `:2428`,
mtcat `:559`, station.json `:2281`, bbox `:534/:414` — consumes masked values with no
per-emitter logic. No emitter may read a coordinate from anywhere but the (post-mask) station
record; the leak-sweep pin (D6) enforces this artifact-agnostically, so a future emitter added
in ignorance of C42 is still caught.

**Cache boundary (invariant):** the C18 cache stores the PRE-mask parse output — true
coordinates (`:1113-1121`); a policy edit re-keys via the survey.yaml digest (`:1887`), but on a
warm rebuild with the policy already in place a cache HIT returns true coords. Therefore: **the
mask applies to the in-memory station record strictly AFTER every cache read (hit or miss) and
its output is NEVER cached; no cache entry is ever a served surface.** Pinned by the warm-cache
sweep (D6).

**products/station.json is masked in served deployments** — the `:2271-2276` "curator sees full
truth / not a distribution surface" comment is false in deployment (D1) and is updated in the
implementation lane; the curator's full-truth surface is the package in surveys-live, per D4.

* **Source bytes**: `can_serve` today is a SURVEY-scoped scalar (`:2217`); C42 adds a
  per-station coordinate-policy predicate at the copy/emit sites — the served-EDI copy loop
  (`:2256-2264`) and `_emit_served_xml` (which must receive per-station policy) — so a non-exact
  station's EDI is excluded from the served copies, the per-survey EDI zip, the EMTF-XML
  (+ derived EDI) and both zips, and the manifest (zips and manifest derive from the copy/emit
  sites, so exclusion propagates automatically — `:1680+`, `:2262-2269`); the portal shows an honest notice ("source file withheld at custodian request —
  contact the custodian"). **We never rewrite custodian bytes to redact them** — as-received
  provenance is standing policy (Black Hill corrections were new files with provenance blocks);
  coordinates hide in too many EDI corners (HEAD, INFO free-text, DEFINEMEAS, comments) for
  redaction to be trustworthy. A custodian-supplied pre-redacted export can be served instead at
  their choice.
* **bbox/centroid — one rule, policy-blind**: computed from the POST-MASK coordinates of every
  station that still has them. Withheld (null) stations drop out automatically via the existing
  `is not None` guard (`:534`); generalised stations contribute their 0.1° cell — a bbox derived
  from already-disclosed values discloses nothing new. A withheld lone station (or all-withheld
  survey) yields NO bbox/centroid — fall back to declared `geographic_extent` or omit. The
  emitters stay policy-blind; no policy tag survives on the masked record.
* **Cache coherence**: the policy lives in survey.yaml, which is already in the C18 cache salt
  and per-survey digest — a policy edit rebuilds affected artifacts with no new machinery
  (verify at contract time, do not assume).

## D4. Curator/workbench integration (C43 Stage 4)

The C43 stations panel gets the policy fieldset (exact/generalised/withheld radio per the locked
mockup); saving publishes a survey.yaml edit through the normal per-section flow — version bump,
release note, validator gate. Note honestly in the panel: the workbench's *served-fetch* facts
show the **masked** position (the workbench reads what the public reads); the true position
remains visible to the curator only in the package itself (surveys-live). Curator-auth-gated
surfaces that show true coords today (validator warnings on the curator page) are acceptable and
unchanged — curators are inside the trust boundary.

## D5. ⚑ Containment boundary (governance — owner countersign)

The served portal is only half the boundary. The **package in git contains the true
coordinates** regardless of what is served:

1. `ausmt-surveys` (and its GitHub backup role) must remain **non-public for as long as any
   non-exact-policy survey is published from it** — OR withheld-class surveys must arrive from
   the custodian already generalised (true coords never enter the repo). This is a standing
   governance constraint, not a code control; it must be re-affirmed at the AuScope transfer,
   where repo visibility decisions will be made by others.
2. Backups inherit the boundary (surveys-live's backup IS GitHub; the DB backup never contains
   coordinates).
3. Any future public mirror, DataCite lane, or DCAT/ISO-19115 export (task #3) inherits the mask
   at the same seam — record this in those lanes' contracts.

## D6. Verification (Invariant 10 — each pin states its failure criterion)

* **Leak-sweep pin (centrepiece):** fixture survey with one exact + one generalised + one
  withheld station carrying distinctive coordinates AND a distinctive elevation; build; sweep the
  ENTIRE emitted out/ tree — every byte of every file — for the true values (string variants:
  6 dp, trailing-zero trimmed, DMS, 3-dp rounded; plus numeric JSON parse with **epsilon ≥ 1e-3**,
  explicitly sized to catch the `at_deg` 3-dp derivative class). FAILS IF a true coordinate (or
  a rounded derivative finer than the disclosed precision) of a non-exact station appears
  anywhere in served output. Mutation-proof TWO ways: flip the fixture to all-exact and show the
  sweep finds every value; and plant a bare 3-dp derivative to show the epsilon catches it.
  Artifact-agnostic — new emitters are covered by construction.
* **Warm-cache sweep pin:** run the full leak-sweep on a SECOND build with the policy already in
  place and survey.yaml unchanged (cache hits > 0, misses = 0). FAILS IF a warm-cache build
  leaks a true coordinate a cold build masks — pins the D3 cache-boundary invariant, which no
  cold-build test exercises.
* **near-duplicate pin:** a withheld/generalised station that trips the ~10 m duplicate QC gets
  a qc_report entry whose `at_deg` carries no true-position bits. FAILS IF the 3-dp true
  derivative appears.
* **bbox pins:** lone-withheld-station survey → no bbox/centroid in mtcat.json or
  collections.json (FAILS IF either appears); a generalised station's survey bbox reflects the
  ROUNDED cell, never the true position (FAILS IF a true-coordinate bbox edge appears).
* **Alignment pin:** masked build preserves catalogue/tf/sci lengths and index identity.
* **Byte-gate pin:** the non-exact stations' EDI and XML are absent from out/edi, out/xml, both
  zips, and manifest.json. FAILS IF any file or manifest row exists.
* **qc_report pin:** an out-of-extent WITHHELD station's qc_report entry carries no coordinates.
* **Portal pins (executable JS, per the C43-S2a standing rule — never string pins alone):** null
  coords produce no map marker and no NaN; the drawer shows the policy badge; CSV export emits
  masked values; the portal renders the masked catalogue value UNCHANGED (no client-side
  re-rounding or re-derivation of precision — FAILS IF any JS path recomputes coordinate
  precision).
* **Validator pins:** unknown enum value → FAIL; override id naming no real station → FAIL.
* **Default-stability pin:** a survey with no `access.coordinates` field builds byte-identical
  catalogue coords to pre-C42. FAILS IF the default changes anything.

## D7. Implementation staging

1. **Engine lane** (the substance): schema read (`build_portal.py` SMETA `:737-780`), mask seam +
   pipeline ordering, byte-gate extension, bbox exclusion, all engine pins. Ships alone.
2. **Validator + editor lane**: `_validation/validate_survey.py` in ausmt-surveys (+ the vendored
   gateway fixture copy — both, they drift), `editor_form.py:62-67` access section fields.
3. **Portal lane**: null-coord handling — these are hard crash/NaN sites today, not soft gaps:
   `drawer.js:164` null-derefs on `.toFixed`, `map.js:93-99` builds markers and fitBounds over
   ALL stations (NaN bounds), `buildFootprints` (`:110-111`) pushes null points into hulls. The
   guards are named: buildMarkers/fitBounds/buildFootprints skip null-coord stations; the drawer
   branches on null before formatting. Plus policy badges + the drawer stance text (replacing
   the universal "locations are public" wording, `drawer.js:32,35,38`).
4. **C43 Stage-4 binding**: the stations-panel fieldset (D4).

Default `exact` means lanes 1–3 ship with zero behaviour change for every existing survey; the
feature activates only when a custodian first sets a policy.

## Provenance

Owner ruling 2026-07-10 (A1: "we give the user the option to withhold coordinates, or a
generalisation, or have it exact"). Recon map of every coordinate-bearing artifact verified
against main @ 3d4be17 the same day (two latent leaks found during recon: served qc_report
coords, served products/station.json). Architect positions flagged to the owner before freeze:
EDI withholding over redaction (rationale in D3), elevation-withheld-under-generalised (D2 ⚑),
repo-visibility governance (D5 ⚑).
