# C32 — Download bundles (EMTF-XML zip + survey MTH5) · served tool versions · zoom threshold

**Status: FROZEN 2026-07-06 (chief-architect design). Deviations need an amendment here first.**
Maintainer requests: (1) offer EMTF-XML and MTH5 downloads per survey alongside the EDI bundle; (2) record
mt_metadata/mth5 versions in what we serve; (3) unclustered map sites below continental zoom.

## §1 Per-survey bundles (engine)

1. **`bundles/<slug>-xml.zip`** — zip of the survey's already-emitted canonical EMTF-XMLs
   (`xml/<slug>/*.xml`; these exist only for round-trip-verified stations by construction). Include
   the same LICENSE.txt treatment the EDI zip gets. Emitted by a sibling of `_emit_survey_edi_zip`.
2. **`bundles/<slug>-tf.h5`** — one MTH5 file per survey containing the served stations'
   TRANSFER FUNCTIONS (the compare_mth5 write path is the pattern: TF objects → mth5). Naming and
   portal label must say **transfer functions only** — never imply time series. mth5's own internal
   version/provenance stamping is kept as written.
3. **Gating is identical to the EDI bundle, same code path**: `can_serve` / embargo (C1/C1b)
   withholds all three bundle kinds equally; manifest rows via the existing `_bundle_row` (it
   already documents "EDI zip / survey MTH5"). verify.py covers the new files automatically via the
   manifest re-hash — verify.py itself MUST NOT change (STOP condition).
4. A station whose TF cannot be written to MTH5 cleanly is skipped WITH a logged WARN and the
   bundle still ships the rest (mirror the XML honesty posture: never fabricate, never block the
   survey on one station); the manifest row's `n_stations` reflects the actual count included.
5. C18 cache: bundles are per-survey assemblies built AFTER station products; do not cache them in
   v1 (they rebuild each build, as the EDI zip does today). No change to cache keys.

## §2 Served tool versions (engine, additive keys only)

- `build.json` and `build_provenance.json` gain `"mt_metadata_version"` and `"mth5_version"`
  (read the same way the C18 salt reads them — single helper, one source of truth).
- The MTCAT document gains the same two keys at document level (additive; no schema version bump;
  confirm the mtcat schema tolerates additive keys as it did for C7 fields).
- build id string format is UNCHANGED (identity stays commit-commit-timestamp).

## §3 Portal

- Survey drawer/card downloads: the existing dormant h5 tile (drawer.js ~340, gated on
  `flags.survey_h5_enabled`) is wired to `bundles/<slug>-tf.h5`; a new "EMTF-XML bundle" tile for
  `bundles/<slug>-xml.zip` follows the exact pattern/labelling/gating of the EDI tile (Content-
  Disposition download path is already covered by the Caddyfile `/bundles/*` rule — verify, don't
  edit directives). Flip `survey_h5_enabled: true` in portal.config.yaml ONLY if the engine now
  always emits the h5; otherwise the tile stays flag-gated and the flag flips in this contract
  with the emission. Absent bundle (embargoed) renders the same withheld state as EDI today.
- **Zoom threshold**: `disableClusteringAtZoom` 12 → **6** in map.js (clusters at continental
  zooms ≤5 only; state/regional/local show individual sites). Named constant + comment stating the
  maintainer's rule ("grouped at continental scale only"); jsdom/source test pins the value so a drive-by
  revert fails a test. LPMT stations remain never-clustered (UX3) — untouched.

## §4 Tests

- Engine: xml-zip contents == the survey's emitted XML set (and only that); embargoed survey emits
  NO xml-zip/h5 (extend the existing C1b bundle assertions); mth5 bundle round-opens under mth5 and
  contains the served station TFs (reuse compare_mth5 helpers); versions present in build.json /
  provenance / mtcat with sane shapes; manifest rows carry size+sha for all three bundle kinds.
- Portal: tiles render/gate correctly incl. withheld state; hostile slug in bundle URL impossible
  (paths built from the sanitized slug already — assert). Zoom constant pinned.
- Full engine + portal + gateway suites + ruff at the end. OS-portable globs (sorted).

## §5 Scope guards

- No verify.py change, no contract/columns.json change, no cache-key change, no Caddyfile
  directive change, no gateway change. ≤ ~450 net non-test lines. STOP and escalate if any of
  those look necessary. mth5 write failures must never fail the build (WARN + skip posture).
