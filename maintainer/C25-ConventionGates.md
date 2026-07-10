# C25 — Ingest convention gates: frame guard + sign-convention check (frozen design)

The engine served ~1,200 legacy stations under a declared standard (x = geographic north,
e^{+iωt}) that nothing verified per file (audit items B4/B5, tracked T1.1/T1.2; deadline = the
T2.1 contract freeze). Two gates now run at the mt_metadata parse seam
(`build_portal._parse_one_edi`, module `extract/_conventions.py`) on every EDI, every build.

## D1. Gate 1 — rotation/frame guard (T1.1)

mt_metadata 1.0.9 RECORDS rotation but never compensates: `io/edi/edi.py:455-461` reads >ZROT
(fallback >RHOROT, else zero-fill) into `rotation_angle`; `core.py:2118/2131,2134-2135` copies it
to `TF._rotation_angle` while Z is copied verbatim. The SPECTRA branch (`_read_spectra`,
edi.py:463-690) maps channels BY POSITION, ignores HMEAS/EMEAS azimuths, never parses ROTSPEC,
and leaves `_rotation_angle` None — a rotated spectra file is invisible to the TF object. So the
gate reads BOTH a raw-text evidence parse (ZROT/TROT blocks, per-line ROTSPEC, HMEAS azimuths —
load-bearing for spectra) AND `_rotation_angle` (cross-checked; disagreement = FAIL). mt_metadata
has no rotate utility (verified: no `def rotate` in the installed package; mtpy not a dep), so the
de-rotation is implemented here and pinned (below).

Disposition — frame POLICY v2 (owner-ruled 2026-07-10; supersedes the v1 "de-rotate everything
declared"). Owner context: the MT community collects AND processes in geomagnetic north; nearly
all Australian data lives in that acquisition frame; 3D modelling does not want strike rotations
forced on it. The archive therefore respects acquisition frames. Evidence hierarchy is unchanged
(ZROT wins on the impedance branch; azimuths only where nothing else declares; ROTSPEC+azimuths
on spectra; Black Hill |HMEAS-implied| == |ROTSPEC| is ONE rotation, disagreement FAILs).
Survey-scope classification (classify_survey_frame; the C18 cache key carries the policy context
via kind="parse#<ctx>", since a station's disposition depends on its siblings' angles):

* **R1 — per-period nonuniform rotation (PAX class): de-rotate per period** to the file's
  declared zero-azimuth reference. Frame MIXING is unservable. Z0(i) = R(-θi) Z(i) R(-θi)^T,
  T0(i) = T(i) R(-θi)^T, R(β) = [[cosβ, sinβ], [-sinβ, cosβ]]; tipper independently under its own
  TROT (AusLAMP-SA: PAX-rotated Z with TROT=0 — tipper untouched); errors in quadrature; partial
  periods masked wholesale before rotation. Pinned by the custodian-twin proof (below) and the
  synthetic round-trips. (auslamp-sa 396 stations — de-rotated while it remains served; the
  compilation is scheduled for retirement in favour of seven campaign surveys.)
* **R2 — station-uniform but survey-inconsistent** (per-station angles spreading >
  SURVEY_ANGLE_SPREAD_MAX_DEG = 5° within one survey): de-rotate the whole survey to zero — one
  survey must serve one frame. (tumby-bay 20/10/24/356.)
* **R3 — survey-uniform |θ| ≤ FRAME_KEEP_MAX_DEG = 15°: serve AS STORED.** An honest
  acquisition-frame (declination-class) declaration; the data is NOT rotated; the frame fields
  record frame_served="declared-azimuth" + declared_azimuth_deg and the conditioning note reads
  "served in its declared acquisition frame, x-axis θ° from the file's zero/geographic
  reference". (ccmt-2017 +8° ≈ local declination — untouched, recorded.)
* **R4 — survey-uniform |θ| > 15°: de-rotate to zero.** Beyond any Australian declination — an
  analysis/nonstandard frame, wrong for a common archive and map display. (olympic-dam-2004
  ZROT=TROT=-60; the synthetic Black Hill spectra shape at 90°.)
* **FAIL (station skipped, loud, structured)** — reserved for the UNKNOWABLE: sentinel (~1e32)
  angles at data-bearing periods; text-vs-reader disagreement; per-period rotation in a
  non-descending-frequency file; ROTSPEC-vs-azimuth conflict; RHOROT-rotated with the Z frame
  undeclared. Every reason names the angles and the fix (build_report stations_dropped + survey
  warning + stderr GATE FAIL line).

The 15° / 5° thresholds are v1 POLICY values (owner-tunable), single-sourced in _conventions.py
(FRAME_KEEP_MAX_DEG, SURVEY_ANGLE_SPREAD_MAX_DEG). Rationale: 15° bounds the Australian
declination range; 5° bounds honest per-survey processing variation.

**Frame-label honesty.** The de-rotation target and all labels are the file's DECLARED
ZERO-AZIMUTH REFERENCE — geographic north per the EDI convention, but de facto
geomagnetic/acquisition north for compass-referenced surveys without declination stamps. Field
values: frame_served = "declared-zero" | "declared-azimuth" (+ declared_azimuth_deg). Nothing
asserts absolute geographic where the file does not prove it; the absolute-frame ambiguity of
undeclared frames is stated, not papered over.

**Custodian-twin ground truth (pins the formula, the sign and the R1 disposition).** De-rotating
the PAX-rotated AusLAMP-SA exports by their per-period ZROT reproduces the custodian's own
zero-reference exports to machine precision (median relative residual ~0 vs 0.15-0.39 for
identity; 4 twin pairs). The four twin pairs are preserved at
.audit/realdata/_specimens/auslamp-pax/{pax,zero}/ (local harness; retirement-proofed — the
served compilation the pax/ copies came from is scheduled for deletion), consumed by
test_convention_gates_realdata.py. The neighbour PT-azimuth arbitration was run and reported
AMBIGUOUS (no discriminating power at 8° against ~50° regional differences); the sign rests on
the twin proof, not on it.

**Serving note (deliberate corrections):** derived products CHANGE for auslamp-sa (396,
per-period de-rotation), olympic-dam-2004 (46, -60° de-rotation) and tumby-bay (36, R2
de-rotation) — 478 stations; ccmt-2017 serves byte-identically to before the gates (as stored)
with its 8° frame now RECORDED. Source EDI bytes are NEVER rewritten (D1); the canonical/served
XML remains mt_metadata-faithful to the source. Open item: the EMTF XML's own orientation
statements for rotated sources remain a normalize()-surface honesty question (final-audit 4.2
class), out of scope here.

## D2. Gate 2 — sign-convention quadrant check (T1.2/C25)

Under e^{+iωt}, x=north: arg(Zxy) ∈ Q1, arg(Zyx) ∈ Q3. Per station, MEDIAN phase of each
off-diagonal over the mid-band (central 60%) of USABLE periods (both phases present, both |Z| ≥
1e-6 floor), evaluated on the SERVED component arrays (post-de-rotation, or as-stored under R3). Verdicts:
* BOTH medians out of quadrant -> FAIL, message names the signature (e^{-iωt} conjugation:
  Zxy→Q4/Zyx→Q2; x/y axis swap: Zxy→Q3/Zyx→Q1 — the three real USArray negative controls'
  shape). This is what makes the C20 induction-arrow "toward conductors" claim safe.
* ONE median out -> WARN honesty note (3D/distortion is legitimate): station.json + build_report
  survey warning, never a failure.
* < 5 usable mid-band periods -> explicit "insufficient data" note, NEVER a verdict (kalk-2026
  degenerate class). ±10° slack at quadrant edges; arg(Zyx) compared on a wrap-safe axis.
* **Stated limit:** Gate 2 is BLIND to ±90° frame rotations by construction (Zxy'=-Zyx keeps
  Q1/Q3; confirmed survey-wide, n=7835 periods). It checks the SIGN CONVENTION only — frames are
  Gate 1's job.

Constants single-sourced in `_conventions.py` (QUADRANT_SLACK_DEG, CONVENTION_MIN_PERIODS,
CONVENTION_MIN_ABS_Z, ROT_UNIFORM_EPS_DEG, AZIMUTH_TOL_DEG); tests import them.

## D3. Surfaces

* station.json gains a non-positional `frame` block (facts: evidence summary, source rotation,
  derotated flag, frame_served, convention_check verdict + medians) — the canonical_conditioning
  precedent; NO positional contract change (C18 cache digest untouched; salt re-keys on engine
  commit as designed).
* build_report.json: survey `stations_dropped` now carries the structured gate drops; new
  optional `frame` array (same aggregation shape as `conditioning`); convention WARNs land in
  `warnings`. Schema updated additively.
* Survey-level stderr: `[frame] NOTICE <slug>: <note> — k/N stations` via the shared
  conditioning aggregation (one line per distinct note).
* MTH5 ingest path (flag-gated off) is not covered by the gates — EDI-specific evidence.

## D4. Test honesty (Invariant 10)

Synthetic fixtures are runtime text-transforms of in-repo clean stations (no rotated real bytes
committed). Every transform pin asserts its own precondition (the fixture IS rotated/conjugated
as-read), and an adversarial meta-pin proves the round-trip can fail (a wrong-signed rotation
matrix is detected at >30° pt_az error). Real-corpus pins (dev-box, AUSMT_REALDATA): the three
USArray negative controls BY NAME (plus a full usarray scan pinning "nothing else fails"), the
ccmt +8° axial-shift acceptance, and the custodian-twin machine-precision proof. The spectra
round-trip pin reproduces the Black Hill shape synthetically (7-channel cross-power rotation,
HX=90/HY=180, ROTSPEC=90) against the in-repo Phoenix specimen.
