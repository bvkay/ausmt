# Transfer Functions

Transfer functions are the primary scientific products AusMT publishes. They describe the
frequency-dependent relationship between naturally occurring electric and magnetic field variations
measured at the surface (Cagniard, 1953; Chave & Jones, 2012), and for many older surveys they are the
only surviving scientific product.

## The impedance tensor

Processing estimates the frequency-domain relationship between the electric field `E = [Ex, Ey]` and
the magnetic field `H = [Hx, Hy]` through the complex impedance tensor:

```text
[Ex]   [Zxx  Zxy] [Hx]
[Ey] = [Zyx  Zyy] [Hy]
```

Apparent resistivity and phase are calculated from it (Cagniard, 1953; Vozoff, 1972). Where vertical
magnetic field measurements exist, the tipper is also estimated:

```text
Hz = Tzx·Hx + Tzy·Hy
```

Tipper products are sensitive to lateral conductivity contrasts and three-dimensional structure
(Vozoff, 1972; Chave & Jones, 2012).

## Supported formats

**EDI** (Electrical Data Interchange) is the most widely used exchange format in the MT community and
the first-class input to AusMT. It carries impedance tensors, tipper estimates, error estimates and basic
metadata.

**EMTF XML** is the XML format from the EarthScope electromagnetic transfer-function framework: a
structured representation of transfer functions, processing metadata, station information and error
estimates. It is an ingest format as well as an output format. The build discovers input transfer
functions from `transfer_functions/edi/`, `transfer_functions/emtfxml/` and MTH5, and writes a
faithful EMTF-XML rendering of every served station as the canonical served output. A station submitted
only as EMTF XML gets the same product set as one submitted as an EDI, including an EDI generated from
the same transfer function. Where a station arrives in both formats the EDI is the canonical source and
the submitted XML is not ingested. Ingest is gated: the canonical rendering must round-trip (impedance,
tipper and their error estimates preserved) or that station serves nothing and the failure is recorded
in `build_report.json`. This is the one place that statement is made; other pages link here.

**MTH5** is an HDF5 container for time series, transfer functions, metadata and provenance (Peacock et
al., 2022). AusMT accepts it as input for transfer functions only and generates per-survey and
per-station transfer-function files from every survey; see [MTH5 integration](../data-model/mth5.md).

Which formats are available for a given survey, and how to fetch each, is in
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

The transfer functions stay authoritative; everything above is a diagnostic computed from them and
regenerable. AusMT does not rank transfer functions. It computes one per-station screening scalar, `q`,
labelled a completeness and smoothness diagnostic rather than a data-quality judgement; its definition
is under [`station.json` diagnostics](../reference/station-products.md#18-diagnostics). It screens an
impedance, so it is withheld on a tipper-only station, which has none.

Transfer functions are themselves derived products: the time series they came from stay in
[external archives](../interoperability/external-archives.md), and the
[provenance model](../data-model/provenance.md) records the link.

## References

Cagniard, L. (1953). Basic theory of the magnetotelluric method of geophysical prospecting. Geophysics, 18(3), 605-635.

Chave, A. D., & Jones, A. G. (2012). The Magnetotelluric Method: Theory and Practice. Cambridge University Press.

Peacock, J. R., Kappler, K., Heagy, L., Ronan, T., Kelbert, A., & Frassetto, A. (2022). MTH5: An archive and exchangeable data format for magnetotelluric time series data. Computers & Geosciences, 162, 105102.

Vozoff, K. (1972). The magnetotelluric method in the exploration of sedimentary basins. Geophysics, 37(1), 98-141.
