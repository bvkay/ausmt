# C20 — Transfer-function completeness (frozen design)

External reviews rated the absence of uncertainties the single largest scientific gap: a
transfer function without errors cannot be assessed for inversion. The portal also served
only tipper magnitude, and some source files carry an unphysical placeholder tipper.

## D1. Eight columns appended to the tf contract (APPEND-ONLY)
`contract/columns.json` TF_COLUMNS grows 10 -> 18, appended in this exact order:
  t[10] rho_xy_err   t[11] rho_yx_err   t[12] phs_xy_err   t[13] phs_yx_err
  t[14] tzx_re       t[15] tzx_im       t[16] tzy_re       t[17] tzy_im
Existing columns t[0..9] keep their positions and their served values byte-identically
(including t[5] tip_mag, retained for compatibility). All eight are thinned to the same
<=32-period axis as the existing columns, null where absent or masked.
Sources: rho errors from the existing RHO*.ERR propagation; phase errors as
degrees(|dZ|/|Z|) from the impedance error where present (the standard small-error linear
propagation; document the formula in data-files.md); tipper components from the component
dict's TXR/TXI/TYR/TYI as read (no sign changes at the data layer — conventions are a
presentation concern).

## D2. Placeholder-tipper honesty
Some EDIs carry a placeholder tipper (observed: |T| identically 1.0 at every period, one
component ~1e-17). Detection at the component level in the extraction path: if a station's
tipper has at least 4 present periods AND max|T|-min|T| < 1e-6 across them AND
||T|-1.0| < 1e-3 at every present period, the tipper is a placeholder: all four component
series and tip_mag are masked to null and a build NOTICE names the station. Real tippers
(varying |T|, or |T| far from 1) are untouched. The thresholds are named constants beside
the other science constants.

## D3. Induction-arrow panel (portal drawer)
The |T|-magnitude plot is REPLACED by an induction-arrow panel rendered BELOW the
phase-tensor plot. At each thinned period (log-period x-axis), two arrows from the axis:
REAL arrow in the Parkinson convention -- components (east, north) = (-tzy_re, -tzx_re) --
drawn solid in the primary colour; IMAGINARY arrow unreversed -- (tzy_im, tzx_im) -- drawn
lighter. A unit-scale reference (|T| = 0.5) is drawn in the corner. The panel is labelled
verbatim: "Induction arrows - Parkinson convention (real arrows point toward conductors);
imaginary unreversed." Stations whose tipper is absent or masked show the existing
"no tipper" state. The x=north, y=east frame of the source data is stated in
data-files.md alongside the new columns.

## D4. Error bars (portal plots)
The rho and phase curves gain error bars from t[10..13]: rho bars drawn in the log domain
(clipped at a small positive floor), phase bars in degrees. Bars only where the error is
present; no visual change for surveys without errors.

## D5. Cache and contract mechanics
The parse-product cache entries change shape: bump the cache entry format tag (v3 -> v4) so
pre-C20 entries MISS cleanly (one cold rebuild, as with C18b). contract/generate.py
regenerates both consumers; data-files.md documents the eight columns, the phase-error
formula, the placeholder rule and the arrow conventions; the extending recipe's consumer
checklist applies (data.js legend, main.js ST mapping if needed, verify.py, contribute.py
tolerance -- both read positionally and must tolerate longer rows; verify they index, not
destructure).

## Tests (each able to fail)
- Contract: generate.py --check green; width asserts updated by the constants themselves.
- Backward byte-identity: t[0..9] of every station in the example fixtures byte-identical
  before/after (golden comparison on the OLD slice; any old-column change = STOP).
- Error columns: a fixture with known impedance errors yields the documented propagation
  values (hand-computed expectations in the test).
- Tipper components: match the component dict on a real-dialect fixture; masked periods
  (1e32 fills) are null in all four (composes with the exact-zero masking).
- Placeholder: a synthetic flat-|T|=1.0 fixture masks; a real varying tipper does not; the
  NOTICE appears.
- Portal: driver assertions for the arrow panel's existence, the Parkinson label text, the
  (east,north) sign mapping on a hand-built tipper (arrow for tzx_re>0 points south =
  negative north component), error-bar rendering presence for with-error data and absence
  otherwise, and the no-tipper state.
- Cache: v3 entries miss cleanly post-bump (mirror the C18b test).

## Amendment A1 (2026-07-13, owner-approved)
The verbatim panel label is superseded by a short heading "Induction arrows (Parkinson)" + always-visible
convention subline; rationale: UX6 review #12 (heading length) + accessibility (no hover-only conventions);
the convention wording itself is unchanged and remains test-pinned in its subline form.
