# Quality Metrics

## Overview

AusMT publishes a range of quality metrics intended to assist users in assessing the characteristics of a dataset.

These products are designed to support discovery, quality assessment and interpretation.

Magnetotelluric data quality depends on many factors, including acquisition conditions, recording duration, processing methodology and the scientific objectives of a study. No single number can capture that, and AusMT does not rank stations or surveys.

AusMT *does* compute one per-station screening scalar (`q`, described below), but it is explicitly labelled in the portal as a completeness/smoothness diagnostic, **not** a data-quality or geological-value judgement.

Quality metrics should therefore be regarded as diagnostic information rather than pass–fail criteria.

---

## Why Quality Metrics?

Users commonly wish to assess:

- Data completeness
- Period coverage
- Statistical uncertainty
- Transfer-function stability
- Spatial coverage
- Survey consistency

before downloading and analysing a dataset.

Quality metrics provide a summary of these characteristics and help users understand the strengths and limitations of a survey.

---

## The `q` screening scalar

Each station carries a 0–5 scalar, `q`, computed by the build (`_edi_science.py`). It exists so
a user screening hundreds of stations can spot incomplete or rough transfer functions quickly.
It is **not** a data-quality ranking, and the portal says so wherever it is displayed.

The definition is deliberately simple and fully disclosed:

- **completeness** — fraction of periods with usable apparent resistivity *and* phase
- **coverage** — decades of period coverage, scaled against four decades
- **smoothness** — 1 − (median second-difference roughness of the xy phase curve)/25°
- **errscore** — where per-period resistivity errors exist: the median relative error (`mre`)
  mapped log-linearly from ≥30% → 0 to ≤2% → 1

When error information exists (`quality_basis = "error"`):

```text
q = 5 × (0.45·errscore + 0.18·coverage + 0.15·completeness + 0.22·smooth)
```

When the EDI carries no usable error blocks (`quality_basis = "shape"`):

```text
q = 5 × (0.40·coverage + 0.30·completeness + 0.30·smooth)
```

Known limitations, stated plainly: smoothness uses the xy phase mode only; the error basis
uses off-diagonal resistivity errors only; there is no normalisation across instrument
classes (a long-period and a broadband station are scored on the same scale). Whether the
scalar should be replaced by the underlying vector of diagnostics (`mre`, decades,
completeness, smoothness) is an open design question to be settled with the community.

A single metric cannot adequately represent period-dependent behaviour, survey objectives,
acquisition environments or processing strategies — so interpret `q` together with the
complementary metrics below, never as a standalone indicator.

---

## Data Completeness

Completeness metrics describe the availability of observations and products.

Examples include:

- Number of stations
- Available transfer-function formats
- Period range
- Presence of tipper products
- Availability of provenance records
- Availability of derived products

These metrics help users determine whether a survey contains the information required for a particular application.

---

## Period Coverage

Period coverage is one of the most important characteristics of an MT dataset.

AusMT reports:

- Minimum and maximum period (catalogue and station pages)
- Number of estimated periods
- Decades of period coverage (a `q` input)

Period coverage provides insight into the depth range that may be investigated using a dataset.

---

## Statistical Uncertainty

Transfer-function estimates in the original submitted format (EDI) carry per-period uncertainty estimates.

These may include:

- Impedance uncertainties
- Tipper uncertainties
- Confidence intervals
- Variance estimates

> **Implementation status (current).** Per-period uncertainties for the off-diagonal modes are
> carried through to the portal's transfer-function data product: the `tf` contract includes
> `rho_xy_err`, `rho_yx_err`, `phs_xy_err` and `phs_yx_err` columns alongside the values. The
> per-station summary scalar `median_relative_error` (`mre`) is reported in the portal
> diagnostics. The complete VAR blocks for **all** components remain available in the original
> served EDI file.

Uncertainty estimates provide information regarding the statistical reliability of transfer-function estimates.

Users who need the full per-component uncertainty record should consult the original EDI's VAR blocks.

---

## Error Bars

Apparent resistivity and phase products in the original EDI commonly include per-period uncertainty estimates, conventionally displayed as error bars.

> **Implementation status (current).** The portal's station drawer renders error bars on the
> apparent-resistivity and phase plots wherever the EDI supplies per-period errors: resistivity
> whiskers are drawn in the log domain, phase whiskers as symmetric ± degrees. Stations whose
> EDIs carry no error blocks show no bars (and their `q` falls back to the shape basis).

Error bars provide a visual indication of the variability associated with a transfer-function estimate.

Large uncertainties do not necessarily imply poor data quality, but they may indicate reduced confidence in a particular estimate.

---

## Transfer Function Consistency

Several shipped diagnostics provide insight into the internal consistency of a transfer function:

- Phase smoothness (median second-difference roughness, a `q` input)
- A galvanic/static-shift signature heuristic — resistivity modes offset by a near-constant
  factor in log space while phases coincide; flagged with a warning in the station drawer
- Phase-tensor dimensionality diagnostics (see [Dimensionality](dimensionality.md))

These diagnostics help users identify unusual features that may warrant further investigation.

---

## Survey Coverage Metrics

Survey-level metrics describe the spatial characteristics of a dataset.

Reported today:

- Number of stations
- Geographic extent (the map itself, and per-survey pages)

Derived spatial metrics (station spacing, profile length, survey area) are not currently
computed.

These metrics help users assess whether a survey is appropriate for a particular regional or local-scale application.

---

## Metadata Completeness

Metadata quality influences the long-term usability of a dataset.

The portal surfaces this per station as availability badges (EDI, time series, MTH5, DOI,
licence) and a maturity bar covering:

- Survey metadata
- Station metadata
- Provenance information
- Citation information
- Identifier information

Metadata completeness should not be confused with scientific quality, but it is an important component of stewardship and reuse.

---

## Provenance Completeness

Provenance information provides context regarding the origin and processing history of a dataset.

Examples include:

- Processing software
- Processing versions
- Product generation dates
- Version history

The availability of provenance information may be reported as part of survey-level quality summaries.

---

## Historical Datasets

Historical datasets often contain incomplete metadata or provenance information.

These limitations should not be interpreted as indicators of poor scientific quality.

Many historically important MT surveys remain highly valuable despite incomplete documentation.

Quality metrics should therefore be interpreted within the context of the survey and its history.

---

## Quality Metrics and Interpretation

Quality metrics are intended to support informed assessment of a dataset.

They do not replace scientific judgement.

A survey with limited metadata may contain excellent transfer functions.

A survey with comprehensive metadata may still contain challenging data.

The purpose of quality metrics is to provide context, not to determine whether a dataset is "good" or "bad".

---

## Future Development

Quality assessment remains an active area of research and development within the MT community.

Additional metrics may be incorporated into AusMT as methods evolve and community practices develop.

New metrics should complement existing products and provide meaningful information to users without obscuring the underlying transfer-function data.

---

## Principle

Quality metrics should help users understand a dataset, not rank it.

The objective is to provide transparent information about the characteristics of a survey while allowing users to determine which metrics are most relevant to their own scientific questions.