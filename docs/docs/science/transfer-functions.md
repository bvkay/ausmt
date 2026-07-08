# Transfer Functions

## Overview

Transfer functions are the primary scientific products published by AusMT. They describe the frequency-dependent relationship between naturally occurring electric and magnetic field variations measured at the Earth's surface and provide the foundation for most magnetotelluric interpretation workflows (Cagniard, 1953; Chave & Jones, 2012).

Within AusMT, transfer functions represent the principal link between field observations and geological interpretation.

Derived products such as phase tensor maps, strike analyses and dimensionality diagnostics are generated from transfer functions and should be regarded as supplementary to them.

---

## Why Transfer Functions?

Magnetotelluric observations begin as time-series measurements of electric and magnetic field variations.

These observations are processed to estimate the frequency-domain relationship between the electric field vector:

```text
E = [Ex, Ey]
```

and the magnetic field vector:

```text
H = [Hx, Hy]
```

through the complex impedance tensor:

```text
E = Z H
```

The impedance tensor forms the basis of most MT analysis and interpretation.

Transfer functions provide a compact representation of this information and are the products most commonly exchanged, archived and reused within the MT community.

---

## The Impedance Tensor

For a two-dimensional horizontal coordinate system, the impedance tensor is typically represented as:

```text
[Ex]   [Zxx  Zxy] [Hx]
[Ey] = [Zyx  Zyy] [Hy]
```

where:

- Ex and Ey are the horizontal electric field components.
- Hx and Hy are the horizontal magnetic field components.
- Zij are the complex impedance tensor elements.

The tensor contains information about the electrical conductivity structure of the subsurface across a range of frequencies or periods. Apparent resistivity and phase are calculated from the complex impedance tensor and have formed the basis of MT interpretation since the early development of the method (Cagniard, 1953; Vozoff, 1972).

---

## Additional Transfer Functions

Where vertical magnetic field measurements are available, additional transfer functions may be estimated.

These include the magnetic transfer function or tipper:

```text
Hz = Tzx·Hx + Tzy·Hy
```

where:

- Hz is the vertical magnetic field component.
- Tzx and Tzy are the complex tipper elements.

Tipper products are particularly sensitive to lateral conductivity contrasts and three-dimensional structure and are widely used as indicators of departures from one-dimensional behaviour (Vozoff, 1972; Chave & Jones, 2012).

---

## Transfer Functions in AusMT

AusMT focuses on transfer functions because they represent the products most commonly used for:

- Interpretation
- Inversion
- Data integration
- Reprocessing
- Archival preservation
- Data exchange

For many historical datasets, the transfer functions are the only surviving scientific products from the original survey.

Preserving and documenting these products is therefore a central objective of AusMT.

---

## Supported Formats

AusMT supports multiple transfer-function representations.

### EDI

EDI (Electrical Data Interchange) is the most widely used transfer-function exchange format in the MT community.

EDI files typically contain:

- Impedance tensors
- Tipper estimates
- Error estimates
- Basic metadata

EDI remains the primary exchange format for many interpretation and inversion workflows.

---

### EMTFXML

> **Implementation status (current).** EMTFXML is not an ingest format today — AusMT's build only
> discovers input transfer functions from `transfer_functions/edi/` (EDI, first-class) and MTH5.
> EMTFXML in a published survey package is instead a **derived, served canonical output**: the
> pipeline reads the source EDI and writes a faithful EMTF-XML rendering alongside it. Accepting
> EMTFXML directly as an ingest format (bypassing the EDI round-trip) is planned, not implemented.

EMTFXML is an XML-based format developed within the EarthScope electromagnetic transfer-function framework.

The format provides a structured representation of:

- Transfer functions
- Processing metadata
- Station information
- Error estimates

Within AusMT, EMTFXML is generated from the source EDI as the canonical served rendering, and is commonly used elsewhere within modern archival and processing systems.

---

### MTH5

MTH5 is an HDF5-based format developed to support modern MT data management, including transfer functions, metadata and observational data within a single self-describing framework (Peacock et al., 2022).

Unlike traditional transfer-function exchange formats, MTH5 can support:

- Time-series observations
- Transfer functions
- Metadata
- Provenance information

Within AusMT, MTH5 provides an important pathway toward improved interoperability and long-term stewardship.

---

## Transfer Function Quality

Transfer functions vary in quality depending on:

- Data quality
- Site conditions
- Instrumentation
- Recording duration
- Processing methodology
- Signal levels

AusMT does not rank transfer functions. It computes one per-station screening scalar (`q`),
explicitly labelled as a completeness/smoothness diagnostic and not a data-quality judgement —
its full definition is in [Quality Metrics](quality-metrics.md).

Users are provided with diagnostic products that allow them to evaluate the characteristics of the transfer functions directly:

- Apparent resistivity and phase plots, with per-period error bars where the EDI supplies them
- Tipper products and induction arrows
- Phase tensor products
- Dimensionality diagnostics

---

## Transfer Functions and Derived Products

Most scientific products published by AusMT are generated from transfer functions.

Each is derived directly from the transfer functions:

```text
Transfer Functions
├── Apparent resistivity and phase
├── Tipper / induction arrows
└── Phase tensor
    ├── Dimensionality diagnostics
    └── Strike screening
```

The transfer functions remain the authoritative scientific products.

Derived products provide additional context and interpretation support.

---

## Transfer Functions and Provenance

Transfer functions should always be considered together with their associated metadata and provenance records.

Important contextual information may include:

- Survey information
- Acquisition dates
- Instrumentation
- Processing software
- Processing versions
- Publication history

This information helps users understand how the products were generated and how they relate to other versions of the dataset.

---

## Relationship to Time-Series Data

Transfer functions are derived products.

They originate from time-series observations of naturally occurring electromagnetic field variations.

AusMT does not archive the underlying time-series data.

Where available, survey packages may provide references to external repositories containing the corresponding observations.

This approach allows transfer functions, metadata and provenance information to remain closely linked while avoiding duplication of large observational archives.

---

## References

Cagniard, L. (1953). Basic theory of the magnetotelluric method of geophysical prospecting. Geophysics, 18(3), 605–635.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Peacock, J. R., Kappler, K., Heagy, L., Ronan, T., Kelbert, A., & Frassetto, A. (2022). MTH5: An archive and exchangeable data format for magnetotelluric time series data. Computers & Geosciences, 162, 105102.

Vozoff, K. (1972). The magnetotelluric method in the exploration of sedimentary basins. Geophysics, 37(1), 98–141.