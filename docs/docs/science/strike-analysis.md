# Strike Analysis

Strike is the preferred orientation of subsurface conductivity structure. For an ideal
two-dimensional Earth the impedance tensor can be rotated into a coordinate system where the
diagonal elements are minimised and the off-diagonal elements carry most of the response
(Swift, 1967), and estimating that direction is part of many MT workflows: assessing
dimensionality, guiding interpretation, supporting 2-D inversion,
comparing neighbouring stations, and identifying regional structural trends. It also flags the
cases where a 2-D approximation is unlikely to be appropriate.

## Strike is not a single number

Real datasets are not ideal. Structures vary with depth, location and scale, so strike
estimates vary between periods and stations. Three-dimensional structure, near-surface effects,
data quality, period range and the estimation method itself all move the answer, and different
methods legitimately disagree about the same data. That is expected. Strike products are
diagnostic tools, not measurements.

Strike also varies with period, so AusMT treats it as a function of period rather than one
survey-wide value: short periods respond to shallow structure, long periods to deeper
structure.

## Methods

Impedance tensor rotation, phase tensor methods and decomposition-based methods all exist and
make different assumptions. Phase tensor strike is among the most widely used, because the
phase tensor is insensitive to galvanic distortion and so gives a comparatively robust
indicator of directional behaviour (Caldwell et al., 2004).

The one strike indicator AusMT ships has its method fixed and disclosed in the portal itself.
Once dedicated strike products are generated, the method will be recorded in each product's
provenance.

## What ships today

The portal's **selection-level rose**. For any set of selected stations, the browser draws a
rose from the served phase-tensor azimuths, using only low-skew periods (|β| < 5°), folded to
180°. The portal states its limitations alongside it: the 90° ambiguity inherent to strike is
not resolved, and combining with tipper induction arrows is suggested to break it.

> **Status: planned.** Dedicated strike products are **not yet generated** (the
> `ausmt_science/strike` module is scaffolding). Once implemented, the intended scope is
> per-station strike estimates, pre-computed station, survey and collection roses,
> period-dependent strike summaries, survey-level statistics and regional strike maps. See
> [Science products](science-products.md) for the authoritative implemented-versus-planned
> list.

A strike estimate is not a geological interpretation, and a well-defined strike does not by
itself justify a two-dimensional inversion. Read strike alongside the transfer functions, the
[phase tensor](phase-tensor.md), the dimensionality diagnostics and the regional geology.

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457–469.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Swift, C. M. (1967). A magnetotelluric investigation of an electrical conductivity anomaly in the southwestern United States. PhD Thesis, Massachusetts Institute of Technology.
