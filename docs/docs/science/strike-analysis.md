# Strike Analysis

## Overview

Strike analysis seeks to identify preferred geoelectric directions within a magnetotelluric dataset.

Many MT interpretation methods assume that the subsurface conductivity structure can be approximated by a two-dimensional Earth. Under this assumption, conductivity variations occur primarily perpendicular to a preferred strike direction.

Estimating this direction is therefore an important part of many MT workflows.

AusMT publishes strike products to assist users in assessing directional behaviour within a dataset and to provide context for interpretation and inversion.

---

## What is Strike?

In magnetotellurics, strike generally refers to the preferred orientation of the subsurface conductivity structure.

For an ideal two-dimensional Earth:

```text
Conductivity Structure
          │
          │
          │
          │
Strike Direction
          ↑
```

the impedance tensor can be rotated into a coordinate system where the diagonal elements are minimised and the off-diagonal elements contain most of the response (Swift, 1967).

Real datasets are rarely this simple.

Conductivity structures may vary with depth, location and scale, leading to different strike estimates at different periods and stations.

---

## Why Estimate Strike?

Strike estimates are commonly used to:

- Assess dimensionality
- Guide interpretation
- Support two-dimensional inversion
- Compare neighbouring stations
- Identify regional structural trends

Strike products can also help identify situations where a two-dimensional approximation is unlikely to be appropriate.

---

## Strike is Not Unique

Strike should not be regarded as a single definitive property of a survey.

Several factors can influence strike estimates, including:

- Three-dimensional structure
- Near-surface effects
- Data quality
- Period range
- Strike estimation method

As a result, different methods may produce different strike estimates for the same dataset.

This is expected.

Strike products should be interpreted as diagnostic tools rather than absolute measurements.

---

## Period Dependence

Strike commonly varies with period.

Short periods may be influenced by shallow geological structures, while longer periods may reflect deeper conductivity patterns.

For this reason, AusMT typically treats strike as a function of period rather than a single survey-wide value.

Examples may include:

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

The interpretation of these relationships remains the responsibility of the user.

---

## Strike Estimation Methods

Multiple approaches exist for estimating strike.

Common examples include:

- Impedance tensor rotation methods
- Phase tensor methods
- Decomposition-based methods

Different methods make different assumptions and may produce different results.

AusMT records the method used to generate a strike product as part of the product provenance.

---

## Phase Tensor Strike

Phase tensor analysis provides one of the most widely used approaches to strike estimation.

Because the phase tensor is insensitive to galvanic distortion, phase tensor strike estimates are often used as a robust indicator of directional behaviour (Caldwell et al., 2004).

Phase tensor strike products should be interpreted alongside other strike indicators rather than in isolation.

---

## Strike Roses

Strike roses provide a visual summary of strike estimates across a range of periods.

These products are particularly useful for identifying:

- Consistent directional trends
- Multiple strike populations
- Period-dependent behaviour
- Survey-wide patterns

AusMT may publish strike roses at station, survey and collection scales.

---

## Survey-Scale Strike Products

Individual stations often exhibit significant variability.

For this reason AusMT may generate survey-level summaries that combine information from multiple stations.

Examples include:

- Strike roses
- Period-dependent strike statistics
- Preferred strike summaries
- Regional strike maps

These products provide context that may not be apparent from individual stations alone.

---

## Relationship to Dimensionality

Strike estimation and dimensionality assessment are closely related.

For an ideal one-dimensional Earth, strike is undefined.

For a two-dimensional Earth, strike may be well defined.

For strongly three-dimensional structures, strike estimates may become unstable or ambiguous.

Strike products should therefore be interpreted alongside dimensionality diagnostics.

---

## Relationship to Phase Tensor Products

Phase tensor products and strike products describe related aspects of the MT response.

Phase tensor products provide information about directional behaviour and dimensionality, while strike products attempt to summarise preferred geoelectric directions.

Together they provide a more complete picture of the dataset than either product alone.

---

## Products Published by AusMT

> **Status: planned.** Dedicated strike products are **not yet generated** by the pipeline (the
> `ausmt_science/strike` module is planned scaffolding). What ships today is the **phase-tensor
> azimuth**, shown in the portal as an indicative strike estimate from low-skew stations. The
> products below are the intended scope once the strike module is implemented — see
> [Science Products](science-products.md) and the developer
> [Product schema](../developer/product-schema.md).

Once implemented, AusMT may publish, depending on the survey and processing workflow:

- Station strike estimates
- Strike roses
- Period-dependent strike summaries
- Survey-level strike statistics
- Regional strike maps

The available products may evolve as methods and community practices develop.

---

## Interpretation

Strike products should be regarded as diagnostic tools.

A strike estimate is not a geological interpretation.

Nor does the presence of a preferred strike necessarily imply that a two-dimensional inversion is appropriate.

Strike products are most useful when considered alongside:

- Transfer functions
- Phase tensor products
- Dimensionality diagnostics
- Geological information

---

## References

Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. Geophysical Journal International, 158(2), 457–469.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Swift, C. M. (1967). A magnetotelluric investigation of an electrical conductivity anomaly in the southwestern United States. PhD Thesis, Massachusetts Institute of Technology.