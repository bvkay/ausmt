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

Disposition (evidence hierarchy):
1. **Impedance branch, >ZROT present** — ZROT is the stored-tensor frame (the EDI standard's
   `ROT=ZROT` block attribute). Uniform 0 -> pass. Uniform nonzero -> DE-ROTATE to geographic:
   `Z' = R(-θ) Z R(-θ)^T`, `R(β) = [[cosβ, sinβ], [-sinβ, cosβ]]`. Per-period varying (all angles
   finite) -> DE-ROTATE PER PERIOD (see the flagship ruling below). HMEAS azimuths on this branch
   are ACQUISITION metadata, never a gate trigger (USArray: sensor azimuths ±19° with ZROT=0 =
   processed-to-geographic; an unconditional azimuth trigger would mass-flag correct data).
2. **Impedance branch, no ZROT** — coherent rotated HMEAS pair (HY = HX+90 ±0.5°, HX ≠ 0) is the
   frame declaration -> de-rotate by HX. Incoherent azimuths (harness-Tasmania HX=180/HY=90
   placeholders) are NOT evidence -> serve + record "frame not machine-verifiable"; Gate 2 still
   checks. RHOROT nonzero with no ZROT -> FAIL (rho declared rotated, Z frame undeclared).
3. **Spectra branch** — uniform ROTSPEC and/or coherent azimuths; when both exist and
   |HMEAS-implied| == |ROTSPEC| they are ONE rotation (the Black Hill 2005 GEOTOOLS shape:
   HX=90/HY=180 + ROTSPEC=90), not two; disagreement -> FAIL naming both. Nonzero -> de-rotate
   Z AND tipper together (same rotated channels).
4. **Tipper frame is independent of Z**: >TROT/>TROT.EXP when present (AusLAMP-SA serves
   PAX-rotated Z with TROT=0 — tipper untouched); else tipper-block `ROT=ZROT` follows θ_Z; else
   not de-rotated, with a note when θ_Z ≠ 0. Errors propagate in quadrature
   (`var' = Σ (R_ik R_jl)² var_kl`). Periods with PARTIAL components are masked wholesale before
   rotation (a fill would smear into every element) and counted in a note.
5. **FAIL (station skipped, loud, structured)** is reserved for the UNKNOWABLE: sentinel (~1e32)
   angles at data-bearing periods; text-vs-reader disagreement; per-period rotation in a
   non-descending-frequency file (alignment unverifiable); ROTSPEC-vs-azimuth conflict; RHOROT
   ambiguity. Every reason names the angles and the fix. Fail = skip + stderr GATE FAIL line +
   build_report `stations_dropped` {station, reason} + a survey warning.

**Flagship ruling (supersedes "nonuniform -> FAIL"; adversarially confirm).** The served
AusLAMP-SA (396 stations) declares `ROTATION=PAX` with per-period ZROT — the impedance is
genuinely principal-axis-rotated per frequency (served curves/azimuths were frame-mixed).
Ground truth: de-rotating the served files by their per-period ZROT reproduces the custodian's
own geographic-frame exports (the .audit harness twins) to machine precision (median relative
residual ~0 vs 0.15-0.39 for identity; 4 twin pairs; pinned in
`test_convention_gates_realdata.py`). A fully-specified per-period rotation is exactly invertible
— the "no single frame exists" rationale for FAIL does not hold for this class, and a literal
nonuniform->FAIL kills the flagship. Ruling implemented: fully-specified -> de-rotate per period;
unknowable -> FAIL. ccmt-2017 (uniform ZROT=8, ≈ the local declination), olympic-dam-2004
(ZROT=TROT=-60), tumby-bay (ZROT=20/10/24/356) de-rotate under the same rule.

**Serving note (deliberate correction):** served derived products CHANGE for auslamp-sa (396),
ccmt-2017 (55), olympic-dam-2004 (46) and tumby-bay (35) stations — they now serve in geographic
north. Source EDI bytes are NEVER rewritten (D1 byte-fidelity); the canonical/served XML remains
mt_metadata-faithful to the source (it carries the source's declared rotation). Open item: the
EMTF XML's own orientation statements for rotated sources remain a normalize()-surface honesty
question (final-audit 4.2 class), out of scope here.

## D2. Gate 2 — sign-convention quadrant check (T1.2/C25)

Under e^{+iωt}, x=north: arg(Zxy) ∈ Q1, arg(Zyx) ∈ Q3. Per station, MEDIAN phase of each
off-diagonal over the mid-band (central 60%) of USABLE periods (both phases present, both |Z| ≥
1e-6 floor), evaluated AFTER Gate-1 de-rotation, on the exact served component arrays. Verdicts:
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
