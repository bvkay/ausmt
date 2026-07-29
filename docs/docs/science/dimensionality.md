# Dimensionality

Dimensionality describes how far an MT response approximates one-, two- or three-dimensional
behaviour. It matters because many interpretation and inversion methods assume an answer, and
knowing whether that assumption is reasonable is part of using the data properly.

```text
1D  Conductivity varies with depth only
2D  Conductivity varies with depth and one horizontal direction
3D  Conductivity varies in all directions
```

It cannot be observed directly. It is inferred from impedance tensor behaviour, phase tensor
characteristics, strike stability, tipper response and tensor invariants, and different
diagnostics can disagree about the same dataset. Treat any dimensionality assessment as an
indicator, not a verdict.

## What each case looks like

**One-dimensional.** Rotationally symmetric response, no preferred geoelectric strike: stable
under rotation, small phase tensor skew, minimal directional dependence, ambiguous strike. Rare
in regional datasets, though it can hold over limited period ranges.

**Two-dimensional.** A preferred strike exists and the response can often be simplified by
rotating into a strike-aligned frame: stable strike estimates, directional conductivity
contrasts, consistent phase tensor orientations, distinct TE and TM responses. Many
interpretation and inversion workflows assume approximately this.

**Three-dimensional.** No single strike direction: variable strike estimates, significant phase
tensor skew, complex tipper behaviour, strong lateral variability. Common in real geology, and
increasingly visible as data quality and coverage improve.

## Dimensionality varies with period

Short periods respond to near-surface structure, intermediate periods to crustal structure,
long periods to lithospheric structure. A survey can therefore be 3-D at short periods and 2-D
at long ones, which is why dimensionality is not one property of a dataset. Strike behaves the
same way: undefined in 1-D, well defined in 2-D, unstable or ambiguous in strong 3-D, so read
the two together (see [Strike analysis](strike-analysis.md)).

The diagnostics used below come from the [phase tensor](phase-tensor.md), which is where skew
and ellipticity are defined.

## The shipped classification

AusMT's build assigns each station a screening classification from its phase tensor
(`_edi_science.py`), with every threshold disclosed:

1. Per-period phase tensors are computed from the impedance (Caldwell et al., 2004).
2. Periods with non-physical skew (|β| ≥ 15°, symptomatic of dead channels or near-singular
   tensors rather than 3-D structure) are excluded as unusable.
3. If fewer than **50%** of the impedance-bearing periods survive, the station is
   **indeterminate**. The data do not support a call, and the build says so rather than
   defaulting to 3-D off saturated skew.
4. Otherwise: **3-D** if median |β| > **5°** or more than **40%** of usable periods have
   |β| > **3°**; else **2-D** if median ellipticity > **0.10**; else **1-D**.

Alongside the class, the station's science row carries the median |β|, the percentage of 3-D
periods and the median ellipticity, and the station drawer displays them. The portal also
colours the map by class.

This is a screening product for survey triage, not a substitute for period-by-period
dimensionality analysis, which the classification deliberately does not attempt.
Period-dependent products and survey-level statistics are not computed today.

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457–469.

Booker, J. R. (2014). The magnetotelluric phase tensor: A critical review. Surveys in Geophysics, 35, 7–40.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.
