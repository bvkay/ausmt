# C42 — Coordinate access model: exact / generalised / withheld (frozen design)

Owner ruling (2026-07-10, audit item 6.1): **the custodian chooses** whether a station's
coordinates are served exact, generalised, or withheld. This record freezes the design.
Status: **FROZEN — owner-countersigned in full.** D5 repo-visibility governance countersigned by
the owner 2026-07-11 ("D5 governance statement is perfect"). The earlier elevation flag dissolved
during adversarial verification: no served JSON surface carries elevation, and the byte-gate
removes the only bearers — see D2. Implementation lanes may cut.

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

**Amendment (2026-07-11 fix round, F2; as amended by fix round 2) — engine fail-closed
granularity:** both policy error classes (unknown enum value AND an invalid override id) fail at
**SURVEY granularity**: the offending survey is dropped loudly and NOTHING of it is served, while
the rest of the corpus builds normally. One survey's typo must never zero the whole portal build.
Note the pipeline reality this makes explicit: exact stations' source bytes are emitted
(copied/zipped) inside the per-survey loop, BEFORE the corpus mask seam runs — the holding
invariant for source bytes is therefore the **per-station byte gate at the copy/emit sites**, not
raise-before-emission; the seam masks the derived record surfaces, the gate withholds the bytes.

**Amendment (2026-07-11 fix round 2) — override key semantics; one matcher by construction:**
fix round 1's discovery-time cross-check ("the ids its EDI files can yield — DATAID + stem",
with prefix tolerance) was BROKEN by the adversarial pass (probe-e): the candidate set was
strictly looser than the id set the mask applies with, so a filename-keyed override could
VALIDATE yet never APPLY — a withheld-intent station served its exact position at rc=0 while an
unrelated id-coincident station was silently masked instead. The ruling:

* **Override keys are STATION ids — never file names, full stop.** The station id derives from
  the EDI DATAID (Phoenix compound form unpacked) / MTH5 station id; a failed validation's SKIP
  message lists the survey's REAL station ids so a custodian who keyed by filename learns the
  correct handles immediately.
* **Base-id matching covers processing variants.** Privacy attaches to the PHYSICAL site: when
  DATAID collisions are deduped as `<base>.<variant>`, an override keys the BASE id and every
  variant record inherits it (the matcher strips the engine-appended variant tag via the record's
  own `variant` field — never by dot-guessing, since a natural DATAID may contain '.'). A full
  variant-suffixed id as an override key is INVALID (rejected; the listing shows bases).
* **Validation and application share ONE matcher, by construction.** Override ids are validated
  in the build loop at the point the REAL parsed station records exist — for BOTH input kinds
  (EDI and MTH5 alike), before any of that survey's bytes/products are emitted — by the very
  function (`validate_overrides`/`base_station_id`) whose derivation `station_policy` applies
  with. There is no discovery-time scrape (any second derivation is a divergence risk). A key
  that names one station's id but is ALSO the file stem of a DIFFERENT station (probe-e's exact
  construction) is AMBIGUOUS and fails closed rather than masking whichever site happens to
  carry the id.
* The corpus-seam raise inside `apply_coordinate_policy` calls the SAME validator on the SAME
  records and is therefore unreachable on EVERY input path of a full build (pinned); it remains
  as the final backstop for direct API callers.

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
  **Amendment (2026-07-11 fix round, F1):** the sweep build enables EVERY flag-gated distribution
  emitter (`--survey-h5` and any future flag) and covers binary containers NUMERICALLY — the
  served MTH5 bundle is opened and each transfer function's tf_summary latitude/longitude/
  elevation read as numbers (same epsilon), and a non-exact station's mere PRESENCE in the bundle
  is itself a failure. A text sweep is structurally blind to IEEE-754 doubles inside binary
  containers, and an emitter left out of the fixture build is an emitter the sweep never audits:
  the hostile panel constructed a real leaking build this way (emit_survey_mth5 re-read the RAW
  source EDIs for the FULL station list, serving a withheld station's exact position inside the
  h5 while every JSON surface was correctly null). Historically red; fixed by filtering the
  bundle's station list through the same per-station byte-gate predicate as the EDI/XML copies.
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
* **Matcher pins (2026-07-11 fix round 2 — the probe-e class):** the id/stem-coincidence fixture
  (file `ALPHA.edi` with DATAID `BRAVO` + an unrelated station whose id is `ALPHA`, override
  keyed `ALPHA`) is dropped LOUDLY with the real station ids listed — FAILS IF the mis-keyed
  survey builds and serves the withheld-intent station's true position (the constructed leak).
  The validated⇒applies PROPERTY pin: over an engine-built survey with a DATAID≠stem station and
  a processing-variant pair, EVERY override key that passes validation changes at least one
  record's effective policy — FAILS IF any validated key is a no-op (matcher divergence). The
  variant pin: a base-id override masks ALL variant records and byte-gates all their files; a
  variant-suffixed key is rejected listing the bases — FAILS IF a sibling variant serves the
  physical site's true position. The MTH5-input pin: a bad override on an mth5-input survey
  drops that survey alone before any of its bytes reach out/, rc=0 — FAILS IF the whole corpus
  aborts or any artifact of the dropped survey is emitted.

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

## Amendment A1 (2026-07-12) — portal-lane finding: the generalised badge needs an engine signal

The portal lane shipped withheld handling in full (null-coords are unambiguous: no marker, no
spatial selection, honest counts, the "coordinates withheld (custodian policy)" drawer line —
browser-verified, crash sites closed). But the lane's executor STOP-reported a real record-vs-code
gap: **the merged engine emits NO policy field on any portal-consumed artifact** — a generalised
station is a silently 0.1°-rounded number, indistinguishable from an exact station on a grid
point, and `distribution.edi_available=false` is shared with embargo/licence gating. The record's
own D-rules forbid recomputing coordinate precision client-side, so the "position generalised"
badge (this record's D2/D6) is **unimplementable portal-side today**. It was NOT faked; the
generalised value renders verbatim, unbadged, for now.

**Resolution (architect ruling): a small engine+portal follow-up delta.** The engine emits a
per-station coordinate-policy marker for NON-EXACT stations on a BOOT-LOADED artifact (the drawer
renders from the in-memory catalogue — `station.json` is never fetched on navigation, so the
signal must ride the catalogue row (additive column) or an equivalent boot artifact). Disclosing
"generalised"/"withheld" reveals policy, not position — it is the honesty this record already
mandates. Exact stations stay unmarked (zero-change default preserved). The same delta carries
the survey-level access-panel wording fix (`drawer.js:32-38` "Station locations … are public" —
now only conditionally true) and the portal badge itself. Leak-sweep pins extend to assert the
marker never co-occurs with exact coordinates for a non-exact station.

## Amendment A2 (2026-07-21) — C43 Stage-4 lane: what shipped, and the base-id-surface gap

The Stage-4 binding (D4) shipped in two parts, plus a stop-and-report on the third:

1. **Editor override assembly (shipped).** `gateway/editor_form.py` now assembles
   `access.coordinate_overrides` from the stations-panel fieldset's `{BASE_station_id: policy}` map
   (one canonical-JSON field, `s_access_coordinate_overrides`), beside the #53 survey-level select.
   INHERIT = a station absent from the map; an explicit policy is written verbatim (pins intent past
   later default changes); an EMPTY/absent map writes NO key (byte-unchanged promise), and setting a
   station back to inherit removes its key via `apply_patch`'s surgical map-merge. Values fail-close
   against `COORDINATE_POLICIES` like the #53 select. It rides the NORMAL per-section metaedit flow
   (`build_section_patch` → merge job → version bump, release note, validator gate) — no new publish
   machinery. Pinned engine-truth: the KEY-PARITY pin feeds the editor-assembled block through the
   REAL `parse_coordinate_policy` AND `validate_overrides` against realistic records (a
   DATAID-differs-from-stem station + a processing-variant pair) — every written key accepted and
   effective, unknown and variant-suffixed keys rejected, inherit removes, empty omits, unchanged
   round-trips to a no-op (all red-proven first).

2. **Effective-policy marker (shipped).** The stations-panel Position fact's static `(exact)` marker
   (D4 "honest display") is replaced by the station's EFFECTIVE policy, read same-origin at boot from
   the OPTIONAL `/data/coord_policy.json` — the SAME boot artifact the portal drawer reads (A1),
   keyed by `ausmt_id`, engine-resolved (override-or-default already applied), so `absent => exact` is
   honest with no client-side precision re-derivation. Served-fetch facts keep showing the masked
   position (the workbench reads what the public reads); no new true-coordinate surface is added.
   Pinned executable-JS (C43-S2a) via node.

3. **The interactive per-station fieldset is BLOCKED on a missing base-id surface (stop-and-report,
   A1-class).** D4 requires the fieldset keys to be **BASE station ids** (D2 fix-round-2: never file
   stems, never variant-suffixed ids — the probe-e discipline that exists to stop a mis-keyed override
   serving the wrong physical site's position or silently no-op'ing). Deriving a base id requires the
   record's `variant` field (id with the engine-appended variant tag stripped via that field, NEVER
   dot-guessing). **No served or boot artifact exposes `variant` or a base-id map:** `catalogue.json`
   carries `id` (possibly `<base>.<variant>`) + `ausmt_id` but no `variant` column; `station.json`
   carries `station`/`ausmt_id`/`coordinate_policy` but no `variant`; `coord_policy.json` is
   `{ausmt_id: policy}` for non-exact stations only. Server-side is no better: the gateway app image
   is content-blind (never imports `engine/`, no station list) and the `list_stations` runner job
   returns file STEMS, not content-derived base ids. So neither the browser nor the gateway can
   construct a fieldset whose keys are guaranteed base ids. Keying by `catalogue.id` would be correct
   for the common (non-variant) station but, for a variant station, would emit a variant-suffixed key
   — which the engine fail-closes at build (safe: no leak, the survey drops loudly), but which
   directly violates D2's "override keys are STATION ids, never variant-suffixed" and would ship a UI
   that generates keys the record forbids. Shipping that silently is the exact matcher-divergence
   class fix-round-2 outlawed, so the interactive editor is held rather than shipped keyed by a
   non-authoritative id. The **assembly + validation + marker are all in place and pinned**, so the
   fieldset is a thin follow-up once the surface exists.

   **Proposed resolution (small engine delta, A1-shaped):** emit a per-survey **base-id surface** on a
   boot artifact — the cheapest is to widen the existing non-exact `coord_policy.json` sibling to a
   compact `{ausmt_id: base_station_id}` map (or add `variant` to `station.json`), reusing the
   `base_station_id(r["id"], r["variant"])` derivation the mask seam already computes, carrying NO
   coordinate (leak-sweep-clean by construction). The stations-panel fieldset then keys strictly by
   base id (all variant records of one physical site collapse to one control, exactly D2's intent),
   POSTs the assembled map through the already-shipped editor path, and the engine/validator remain
   the authoritative key gate. This needs the engine owner's sign-off (it touches a served artifact),
   hence the stop-and-report rather than a unilateral engine change in this metadata-editing lane.

## Provenance

Owner ruling 2026-07-10 (A1: "we give the user the option to withhold coordinates, or a
generalisation, or have it exact"). Recon map of every coordinate-bearing artifact verified
against main @ 3d4be17 the same day (two latent leaks found during recon: served qc_report
coords, served products/station.json). Architect positions flagged to the owner before freeze:
EDI withholding over redaction (rationale in D3), elevation-withheld-under-generalised (D2 ⚑),
repo-visibility governance (D5 ⚑). Amendment A1 2026-07-12 (portal lane executor stop-and-report;
generalised-badge engine-signal delta ruled).
