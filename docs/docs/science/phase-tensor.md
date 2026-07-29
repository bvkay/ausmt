# Phase Tensor

The phase tensor, introduced by Caldwell, Bibby and Brown (2004), represents the impedance
phase relationships in a form that is independent of galvanic distortion. That property is why
it became a standard part of MT interpretation: apparent resistivity curves are often dominated
by near-surface conductivity variations, which makes station-to-station comparison and regional
interpretation difficult, while the phase tensor stays sensitive to the deeper structure
without carrying those local effects.

## Definition

Writing the impedance tensor as `Z = X + iY`, with `X` the real component and `Y` the
imaginary component, the phase tensor is:

```text
Φ = X⁻¹ Y
```

(Caldwell et al., 2004)

It is usually drawn as an **ellipse**, one per period, described by its major and minor axes,
its orientation and its skew angle. Those parameters carry information about structural
directionality, dimensionality and lateral conductivity contrasts.

The two **principal phases**, `Φmax` and `Φmin`, are the maximum and minimum phase responses the
tensor represents. The difference between them describes the anisotropy of the response.

## Skew

Phase tensor skew (β) indicates three-dimensional behaviour. In a perfectly one- or
two-dimensional Earth it is expected to be small, and increasing values generally indicate
increasing departure from two-dimensional behaviour (Caldwell et al., 2004). Skew should not be
read alone; it is most useful alongside the other diagnostics.

AusMT serves per-period β in the transfer-function data product, and the median |β| is the
primary input to the shipped dimensionality classification. The thresholds are disclosed in
[Dimensionality](dimensionality.md#the-shipped-classification).

## What AusMT publishes

Shipped today, for every station:

- Per-period phase tensor parameters in the transfer-function data product: `Φmin`, `Φmax`,
  azimuth and skew β
- A phase-tensor plot in the portal's station drawer
- The azimuths, which feed the dimensionality classification and the selection-level
  [strike rose](strike-analysis.md)

Not generated today: phase tensor ellipse maps per period or period band, and survey-level phase
tensor summaries.

## Interpretation

Phase tensor products are diagnostic tools, not geological interpretations. Similar phase
tensor responses can arise from different conductivity structures, so read them alongside the
transfer functions, strike products and regional geology. Dimensionality indicators derived
from them are guides, not classifications of the Earth.

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457–469.

Bibby, H. M., Caldwell, T. G., & Brown, C. (2005). Determinable and non-determinable parameters of galvanic distortion in magnetotellurics. Geophysical Journal International, 163(3), 915–930.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.
