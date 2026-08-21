# Strike Analysis

Strike is the preferred orientation of subsurface conductivity structure. For an ideal two-dimensional
Earth the impedance tensor can be rotated into a frame where the diagonal elements are minimised and
the off-diagonal elements carry most of the response (Swift, 1967). Estimating that direction supports
dimensionality assessment, 2-D inversion, comparison of neighbouring stations and regional structural
interpretation, and flags the cases where a 2-D approximation is unlikely to hold.

## Strike is not a single number

Structures vary with depth, location and scale, so strike estimates vary between periods and stations,
and different methods legitimately disagree about the same data. Strike varies with period (short
periods respond to shallow structure, long periods to deeper structure), so AusMT treats it as a
function of period rather than one survey-wide value. Phase tensor strike is among the most widely used
methods because the phase tensor is insensitive to galvanic distortion (Caldwell et al., 2004).

## What ships today

The portal's selection-level rose. For any set of selected stations, the browser draws a rose from the
served phase-tensor azimuths, using only low-skew periods (|β| < 5°), folded to 180°. The portal states
its limitations beside it: the 90° ambiguity inherent to strike is not resolved, and combining with
tipper induction arrows is suggested to break it.

Dedicated strike products are not generated; `ausmt_science/strike` is scaffolding. The intended scope
is per-station strike estimates, pre-computed station, survey and collection roses, period-dependent
strike summaries and regional strike maps, with the method recorded in each product's provenance.
[Science products](science-products.md) is the authoritative implemented-versus-planned list.

A well-defined strike does not by itself justify a two-dimensional inversion. Read strike alongside the
transfer functions, the [phase tensor](phase-tensor.md), the dimensionality diagnostics and the
regional geology.

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457-469.

Swift, C. M. (1967). A magnetotelluric investigation of an electrical conductivity anomaly in the southwestern United States. PhD Thesis, Massachusetts Institute of Technology.
