# Dimensionality

## Overview

Dimensionality describes the degree to which a magnetotelluric response approximates one-dimensional, two-dimensional or three-dimensional behaviour.

It is one of the most important diagnostic concepts in magnetotellurics because many interpretation and inversion methods make assumptions regarding the dimensionality of the subsurface conductivity structure.

AusMT publishes dimensionality products to assist users in understanding the complexity of a dataset and to provide context for interpretation and model design.

---

## Why Dimensionality Matters

The electrical conductivity structure of the Earth may vary in one, two or three spatial dimensions.

These different situations produce different MT responses.

In simplified form:

```text
1D Conductivity varies with depth only
2D Conductivity varies with depth and one horizontal direction
3D Conductivity varies in all directions
```

Many MT processing and inversion workflows are based on assumptions regarding dimensionality.

Understanding whether those assumptions are reasonable is therefore an important part of data interpretation.

---

## Dimensionality is a Diagnostic Concept

Dimensionality cannot be observed directly.

Instead, it is inferred from characteristics of the transfer functions and related products.

Examples include:

- Impedance tensor behaviour
- Phase tensor characteristics
- Strike stability
- Tipper responses
- Tensor invariants

Different diagnostics may provide different perspectives on the same dataset.

For this reason dimensionality assessments should be regarded as indicators rather than definitive classifications.

---

## One-Dimensional Behaviour

In a one-dimensional Earth, conductivity varies only with depth.

The response is rotationally symmetric and no preferred geoelectric strike direction exists.

Characteristics commonly associated with one-dimensional behaviour include:

- Stable responses under rotation
- Small phase tensor skew
- Minimal directional dependence
- Strike ambiguity

True one-dimensional behaviour is relatively uncommon in regional MT datasets but may occur over limited period ranges or in specific geological settings.

---

## Two-Dimensional Behaviour

In a two-dimensional Earth, conductivity varies with depth and one horizontal direction.

A preferred geoelectric strike direction exists and the response may often be simplified through rotation into a strike-aligned coordinate system.

Characteristics commonly associated with two-dimensional behaviour include:

- Stable strike estimates
- Directional conductivity contrasts
- Consistent phase tensor orientations
- Distinct TE and TM responses

Many MT interpretation methods and inversion workflows are based on the assumption of approximately two-dimensional behaviour.

---

## Three-Dimensional Behaviour

In a three-dimensional Earth, conductivity varies in all directions.

The response cannot generally be reduced to a single strike direction and may exhibit substantial complexity.

Characteristics commonly associated with three-dimensional behaviour include:

- Variable strike estimates
- Significant phase tensor skew
- Complex tipper behaviour
- Strong lateral variability

Three-dimensional behaviour is common in many geological environments and becomes increasingly apparent as data quality and spatial coverage improve.

---

## Dimensionality and Scale

Dimensionality often varies with period.

Short periods may be influenced by shallow conductivity structure, while longer periods may reflect deeper geological features.

For example:

```text
Short Periods
↓
Near-Surface Structure

Intermediate Periods
↓
Crustal Structure

Long Periods
↓
Lithospheric Structure
```

A survey may therefore exhibit different dimensionality characteristics at different periods.

Dimensionality should not necessarily be considered a single property of an entire dataset.

---

## Phase Tensor Diagnostics

Many modern dimensionality assessments are based on phase tensor analysis (Caldwell et al., 2004).

Phase tensor products provide information regarding:

- Directionality
- Geoelectric strike
- Three-dimensional behaviour
- Structural complexity

Because phase tensor diagnostics are insensitive to galvanic distortion, they have become a widely used component of dimensionality analysis.

---

## Phase Tensor Skew

Phase tensor skew is commonly used as an indicator of departures from one-dimensional and two-dimensional behaviour.

In general terms:

- Small skew values are often associated with simpler responses.
- Larger skew values may indicate increasing three-dimensional complexity.

However, skew should not be interpreted in isolation.

It is most useful when considered alongside other dimensionality diagnostics.

---

## Ellipticity

Phase tensor ellipticity describes the shape of the phase tensor ellipse.

Ellipticity provides information about directional variations in the MT response and may assist in identifying departures from simple one-dimensional behaviour.

Within AusMT, ellipticity may form part of survey-level dimensionality assessments and summaries.

---

## Strike and Dimensionality

Strike analysis and dimensionality assessment are closely related.

For example:

```text
1D Strike undefined
2D Strike may be well defined
3D Strike may become unstable or ambiguous
```

For this reason dimensionality products should generally be interpreted together with strike products rather than independently.

---

## Survey-Level Products

AusMT may publish dimensionality products at several levels.

Examples include:

- Station dimensionality summaries
- Survey-level dimensionality statistics
- Period-dependent dimensionality products
- Dimensionality maps
- Dimensionality classifications

These products provide a concise summary of the complexity of a dataset.

---

## Classification

Dimensionality classifications should be regarded as interpretive tools rather than absolute descriptions of the Earth.

A classification such as:

```text
1D
2D
3D
```

is a simplification of a much more complex conductivity structure.

The purpose of dimensionality products is to assist understanding and guide further analysis rather than provide definitive answers.

---

## Relationship to Other Products

Dimensionality products are closely linked to:

- Transfer functions
- Phase tensor products
- Strike analyses
- Tipper products

Together these products provide complementary information regarding the structure and complexity of a dataset.

No single diagnostic should be used in isolation.

---

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457–469.

Booker, J. R. (2014). The magnetotelluric phase tensor: A critical review. Surveys in Geophysics, 35, 7–40.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.