# Transfer Functions

Transfer functions are the primary scientific products AusMT publishes. They describe the
frequency-dependent relationship between naturally occurring electric and magnetic field
variations measured at the surface, and they are the foundation of most MT interpretation
(Cagniard, 1953; Chave & Jones, 2012). They are also, for many older surveys, the only
surviving scientific product.

## The impedance tensor

MT observations start as time series of electric and magnetic field variations. Processing
estimates the frequency-domain relationship between the electric field vector `E = [Ex, Ey]`
and the magnetic field vector `H = [Hx, Hy]` through the complex impedance tensor:

```text
[Ex]   [Zxx  Zxy] [Hx]
[Ey] = [Zyx  Zyy] [Hy]
```

The tensor carries information about subsurface electrical conductivity across a range of
periods. Apparent resistivity and phase are calculated from it, and have been the basis of MT
interpretation since the method's early development (Cagniard, 1953; Vozoff, 1972).

Where vertical magnetic field measurements exist, the magnetic transfer function or tipper is
also estimated:

```text
Hz = Tzx·Hx + Tzy·Hy
```

Tipper products are sensitive to lateral conductivity contrasts and three-dimensional
structure, and are widely used as indicators of departures from one-dimensional behaviour
(Vozoff, 1972; Chave & Jones, 2012).

## Supported formats

**EDI** (Electrical Data Interchange) is the most widely used exchange format in the MT
community and the first-class input to AusMT. An EDI typically carries impedance tensors,
tipper estimates, error estimates and basic metadata, and it remains what most interpretation
and inversion workflows expect.

**EMTF XML** is the XML format from the EarthScope electromagnetic transfer-function framework,
giving a structured representation of transfer functions, processing metadata, station
information and error estimates.

> **Implementation status (current).** EMTF XML is **an ingest format as well as an output
> format**. AusMT's build discovers input transfer functions from `transfer_functions/edi/`,
> `transfer_functions/emtfxml/` and MTH5, and writes a faithful EMTF-XML rendering of every
> served station as the canonical served output. A station submitted only as EMTF XML gets the
> same product set as one submitted as an EDI, including an EDI generated from the same transfer
> function. Where a station arrives in both formats the EDI is the canonical source and the
> submitted XML is not ingested. Ingest is gated: the canonical rendering must round-trip
> (impedance, tipper and their error estimates preserved) or that station serves nothing and the
> failure is recorded in `build_report.json`. This is the one place that statement is made;
> other pages link here.

**MTH5** is an HDF5-based container able to hold time series, transfer functions, metadata and
provenance in a single self-describing file (Peacock et al., 2022). AusMT accepts it as input
for transfer functions only and generates a per-survey transfer-function bundle from it; see
[MTH5 integration](../data-model/mth5.md).

Which formats are available for a given survey, and how to fetch each one, is in
[Selecting a format](../interoperability/api-reference.md#selecting-a-format).

## What is derived from them

```text
Transfer Functions
├── Apparent resistivity and phase
├── Tipper / induction arrows
└── Phase tensor
    ├── Dimensionality diagnostics
    └── Strike screening
```

The transfer functions stay authoritative; everything above is a diagnostic computed from them
and regenerable. AusMT does not rank transfer functions. It computes one per-station screening
scalar, `q`, explicitly labelled a completeness and smoothness diagnostic rather than a
data-quality judgement; its definition is under
[`station.json` diagnostics](../reference/station-products.md#18-diagnostics).

Transfer functions should always be read together with their metadata and
[provenance](../data-model/provenance.md), and they are derived products themselves: the
time series they came from stay in
[external archives](../interoperability/external-archives.md).

## References

Cagniard, L. (1953). Basic theory of the magnetotelluric method of geophysical prospecting. Geophysics, 18(3), 605–635.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Peacock, J. R., Kappler, K., Heagy, L., Ronan, T., Kelbert, A., & Frassetto, A. (2022). MTH5: An archive and exchangeable data format for magnetotelluric time series data. Computers & Geosciences, 162, 105102.

Vozoff, K. (1972). The magnetotelluric method in the exploration of sedimentary basins. Geophysics, 37(1), 98–141.
