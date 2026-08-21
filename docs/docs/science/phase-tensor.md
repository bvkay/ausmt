# Phase Tensor

The phase tensor (Caldwell, Bibby & Brown, 2004) represents the impedance phase relationships in a form
that is independent of galvanic distortion. Apparent resistivity curves are often dominated by
near-surface conductivity variations; the phase tensor stays sensitive to deeper structure without
carrying those local effects, which is why it is the basis of AusMT's screening diagnostics.

## Definition

Writing the impedance tensor as `Z = X + iY`, the phase tensor is:

```text
Φ = X⁻¹ Y
```

It is drawn as an ellipse, one per period, described by its major and minor axes, its orientation and
its skew angle. The principal phases `Φmax` and `Φmin` are the maximum and minimum phase responses the
tensor represents; their difference describes the anisotropy of the response. AusMT's ellipticity is
`|Φmax - Φmin| / (|Φmax| + |Φmin|)`.

## Skew

Skew (β) indicates three-dimensional behaviour. In a one- or two-dimensional Earth it is small;
increasing values indicate increasing departure from two-dimensional behaviour. Skew should be read with
the other diagnostics, not alone.

## Dimensionality

Dimensionality describes how far a response approximates 1-D (conductivity varies with depth only),
2-D (depth and one horizontal direction) or 3-D behaviour. It cannot be observed directly, different
diagnostics can disagree, and it varies with period: short periods respond to near-surface structure,
long periods to lithospheric structure, so a survey can be 3-D at short periods and 2-D at long ones.
Treat any dimensionality assessment as an indicator, not a verdict.

AusMT assigns each station one screening class from its phase tensor, using the median absolute skew,
the share of high-skew periods and the median ellipticity. The thresholds are stated with the served
file, [`dimensionality.json`](../reference/station-products.md#2-dimensionalityjson), which rides
beside `station.json` and is not a contract. It is a triage product; period-by-period dimensionality analysis is not attempted.

## What AusMT publishes

For every served station: per-period `Φmin`, `Φmax`, azimuth and skew β in the transfer-function data
product; a phase-tensor plot in the station drawer; and the azimuths, which feed the dimensionality
classification and the selection-level [strike rose](strike-analysis.md). Not generated: phase tensor
ellipse maps per period or period band, and survey-level summaries.

Phase tensor products are diagnostic tools, not geological interpretations. Similar responses can arise
from different conductivity structures, so read them alongside the transfer functions, strike products
and regional geology.

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457-469.

Bibby, H. M., Caldwell, T. G., & Brown, C. (2005). Determinable and non-determinable parameters of galvanic distortion in magnetotellurics. Geophysical Journal International, 163(3), 915-930.

Booker, J. R. (2014). The magnetotelluric phase tensor: A critical review. Surveys in Geophysics, 35, 7-40.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.
