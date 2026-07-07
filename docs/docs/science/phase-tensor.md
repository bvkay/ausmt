# Phase Tensor Products

## Overview

The phase tensor is one of the most widely used diagnostic tools in modern magnetotellurics.

Introduced by Caldwell, Bibby and Brown (2004), the phase tensor provides a representation of the impedance phase relationships that is independent of galvanic distortion.

Because of this property, phase tensor products have become a standard component of MT interpretation workflows and are routinely used to assess dimensionality, structural trends and regional conductivity variations.

AusMT publishes a range of phase tensor products to support rapid assessment and interpretation of transfer-function datasets.

---

## Why Phase Tensors?

Apparent resistivity curves are often strongly influenced by near-surface conductivity variations.

These effects can complicate comparisons between stations and make regional interpretation difficult.

The phase tensor was developed to provide information that is insensitive to galvanic distortion while retaining sensitivity to the deeper conductivity structure (Caldwell et al., 2004).

This makes phase tensor products particularly useful for:

- Survey assessment
- Structural interpretation
- Dimensionality analysis
- Regional comparisons
- Quality control

---

## The Phase Tensor

The phase tensor is derived from the real and imaginary components of the impedance tensor.

If the impedance tensor is written as:

```text
Z = X + iY
```

where:

- (X) is the real component
- (Y) is the imaginary component

then the phase tensor is defined as:

```text
Φ = X⁻¹ Y
```

(Caldwell et al., 2004)

The resulting tensor contains information about the phase behaviour of the MT response that is independent of galvanic distortion.

---

## Phase Tensor Ellipses

The most common visual representation of the phase tensor is the phase tensor ellipse.

Each ellipse summarises the behaviour of the phase tensor at a particular period.

The ellipse is commonly described by:

- Major axis
- Minor axis
- Orientation
- Skew angle

These parameters provide information about:

- Structural directionality
- Dimensionality
- Lateral conductivity contrasts

Phase tensor ellipses are widely used in survey maps and profile displays.

---

## Phase Tensor Maps

Phase tensor ellipse maps for individual periods or period bands are a **planned** product —
they are not generated today.

Such maps allow users to visualise regional variations in conductivity structure across an
entire survey, supporting regional geological interpretation, lithospheric studies,
exploration targeting and survey-scale quality assessment. They are often one of the most
effective ways to obtain an overview of a large MT dataset, which is why they are on the
roadmap.

---

## Principal Phases

The phase tensor can be characterised using two principal phase values.

These are commonly denoted:

```text
Φmax
Φmin
```

and describe the maximum and minimum phase responses represented by the tensor.

Differences between the principal phases provide information about the anisotropy and dimensionality of the response.

---

## Phase Tensor Skew

Phase tensor skew is commonly used as an indicator of three-dimensional behaviour.

In a perfectly one-dimensional or two-dimensional Earth, the skew is expected to be small.

Increasing skew values generally indicate increasing departures from two-dimensional behaviour (Caldwell et al., 2004).

Within AusMT, the per-period skew β is served in the transfer-function data product, and the
median |β| is the primary input to the shipped dimensionality classification (see
[Dimensionality](dimensionality.md) for the thresholds).

---

## Interpretation

Phase tensor products are diagnostic tools.

They provide information about the characteristics of a dataset but do not themselves constitute a geological interpretation.

In particular:

- Similar phase tensor responses may arise from different conductivity structures.
- Phase tensor products should be interpreted alongside other information.
- Dimensionality indicators should be regarded as guides rather than absolute classifications.

The phase tensor is most powerful when used in conjunction with transfer functions, strike analyses and regional geological information.

---

## Products Published by AusMT

Shipped today, for every station:

- Per-period phase tensor parameters in the transfer-function data product — Φmin, Φmax,
  azimuth and skew β
- A phase-tensor plot in the portal's station drawer
- The azimuths feed the dimensionality classification and the selection-level strike rose

Planned:

- Phase tensor ellipse maps (per period or period band)
- Survey-level phase tensor summaries

---

## Relationship to Dimensionality

Phase tensor products form the foundation of several dimensionality diagnostics published by AusMT.

Examples include:

- Phase tensor skew
- Survey-scale dimensionality summaries
- Period-dependent dimensionality indicators

For this reason, phase tensor products should generally be considered before examining dimensionality classifications.

---

## Relationship to Strike Analysis

Phase tensor products and strike analyses are closely related.

Both seek to describe the directional characteristics of the MT response.

Phase tensor products provide information directly from the phase relationships within the impedance tensor, while strike analyses attempt to estimate preferred geoelectric directions.

Together, these products provide complementary perspectives on the underlying conductivity structure.

---

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457–469.

Bibby, H. M., Caldwell, T. G., & Brown, C. (2005). Determinable and non-determinable parameters of galvanic distortion in magnetotellurics. Geophysical Journal International, 163(3), 915–930.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.