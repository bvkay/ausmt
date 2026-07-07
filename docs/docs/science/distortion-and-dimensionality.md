# Distortion and Decomposition (in development)

## Overview

Magnetotelluric transfer functions contain information about conductivity structure across a wide range of spatial scales.

However, the observed response may also be influenced by local conductivity variations near the measurement site.

These local effects can alter the apparent resistivity response and complicate the interpretation of regional conductivity structure.

A variety of decomposition and diagnostic methods have been developed to investigate these effects and to separate regional behaviour from local influences.

AusMT publishes distortion and decomposition products as advanced diagnostic tools intended to support interpretation and quality assessment.

These products should be regarded as complementary to the original transfer functions rather than replacements for them.

---

## Local and Regional Effects

MT responses commonly reflect a combination of:

```text
Regional Conductivity Structure
+ Local Conductivity Structure
= Observed Response
```

Local conductivity variations may influence:

- Apparent resistivity
- Strike estimates
- Dimensionality indicators
- Tensor geometry

The extent of these effects varies between sites and geological environments.

---

## What is Distortion?

The term distortion is commonly used to describe modifications of the observed impedance tensor caused by local conductivity structure.

These effects are often associated with conductivity contrasts near the measurement site and may alter the amplitude and directional characteristics of the observed response.

Distortion does not necessarily imply that the data are incorrect.

Rather, it reflects the fact that the observed response contains information from multiple spatial scales.

---

## Why Examine Distortion?

Distortion analysis may assist with:

- Understanding site responses
- Comparing neighbouring stations
- Assessing strike stability
- Evaluating dimensionality assumptions
- Identifying regional conductivity trends

These products are intended to provide additional context for interpretation rather than definitive corrections.

---

## Tensor Decomposition

Tensor decomposition methods attempt to separate different components of the observed MT response.

Many approaches seek to distinguish:

```text
Regional Response
Local Distortion Effects
Observed Impedance Tensor
```

Different decomposition methods make different assumptions regarding dimensionality and conductivity structure.

As a result, different methods may produce different estimates for the same dataset.

---

## Groom–Bailey Decomposition

The Groom–Bailey decomposition (Groom & Bailey, 1989) remains one of the most widely used approaches for analysing galvanic distortion in magnetotellurics.

The method assumes an underlying two-dimensional regional conductivity structure and represents the observed response using a set of distortion operators and regional impedance parameters.

Outputs commonly include estimates of:

- Twist
- Shear
- Anisotropy
- Site gain
- Regional strike

These parameters should be interpreted within the assumptions of the method.

---

## Multi-Site Decomposition

Several decomposition approaches extend the original Groom–Bailey framework by incorporating information from multiple stations simultaneously.

Examples include the methods of McNeice and Jones (2001).

By considering neighbouring stations together, these approaches may provide more stable estimates of regional strike and distortion parameters than single-station methods.

Multi-site approaches are widely used in regional MT studies.

---

## Modern Decomposition Approaches

Additional decomposition methods have been developed to address limitations of earlier approaches and to support more complex geological settings.

Examples include approaches based on:

- Phase tensor analysis
- Multi-site inversion
- Statistical decomposition
- Tensor invariants

Different methods emphasise different aspects of the MT response and should be interpreted within their respective theoretical frameworks.

---

## Lilley Invariants and Mohr Circles

Tensor invariants provide an alternative perspective on MT responses that does not rely directly on a preferred coordinate system.

Lilley (1993, 1998) introduced a series of tensor invariant representations that provide insight into:

- Dimensionality
- Rotational behaviour
- Tensor geometry

Mohr circle representations provide a graphical method for visualising tensor properties and assessing departures from simplified dimensionality assumptions.

These products are particularly useful for diagnostic analysis and educational purposes.

---

## Distortion and Dimensionality

Distortion analysis and dimensionality assessment are closely related.

Many decomposition methods assume:

```text
1D
or
2D
```

regional conductivity structure.

When the true Earth is strongly three-dimensional, decomposition results may become unstable or difficult to interpret.

For this reason distortion products should generally be interpreted alongside:

- Phase tensor products
- Strike analyses
- Dimensionality diagnostics
- Geological information

---

## Products Published by AusMT

> **Status: planned (in development).** Decomposition products are **not yet generated** (the
> `ausmt_science/decomposition` module is an optional, MTpy-v2-backed Tier-3 stub — see the developer
> [Product schema](../developer/product-schema.md)). The list below is the intended scope once it is
> wired in, not what currently ships.

Once implemented, depending on the survey and available processing products, AusMT may publish:

- Groom–Bailey parameters
- Multi-site decomposition products
- Regional strike estimates
- Tensor invariant products
- Mohr circle products
- Survey-level decomposition summaries

The available product set may evolve as methods and community practices develop.

---

## Interpretation

Distortion and decomposition products are diagnostic tools.

They do not provide a unique description of the Earth.

Different methods may produce different estimates because they are based on different assumptions regarding:

- Dimensionality
- Regional structure
- Distortion mechanisms

Users should therefore regard decomposition products as aids to interpretation rather than definitive solutions.

The original transfer functions remain the authoritative scientific products.

---

## Relationship to Other Products

Distortion and decomposition products should be interpreted together with:

- Transfer functions
- Phase tensor products
- Strike analyses
- Dimensionality diagnostics

No single product provides a complete description of the MT response.

The greatest value is often obtained by examining the consistency between multiple independent diagnostics.

---

## References

Booker, J. R. (2014). The magnetotelluric phase tensor: A critical review. Surveys in Geophysics, 35, 7–40.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Groom, R. W., & Bailey, R. C. (1989). Decomposition of magnetotelluric impedance tensors in the presence of local three-dimensional galvanic distortion. Journal of Geophysical Research, 94(B2), 1913–1925.

Lilley, F. E. M. (1993). Magnetotelluric analysis using Mohr circles. Geophysics, 58(10), 1498–1507.

Lilley, F. E. M. (1998). Magnetotelluric tensor decomposition: Part I. Theory for a basic procedure. Geophysics, 63(6), 1885–1897.

McNeice, G. W., & Jones, A. G. (2001). Multisite, multifrequency tensor decomposition of magnetotelluric data. Geophysics, 66(1), 158–173.