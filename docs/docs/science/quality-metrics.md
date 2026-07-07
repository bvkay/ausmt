# Quality Metrics

## Overview

AusMT publishes a range of quality metrics intended to assist users in assessing the characteristics of a dataset.

These products are designed to support discovery, quality assessment and interpretation.

The objective is not to assign a single quality score to a survey or station. Magnetotelluric data quality depends on many factors, including acquisition conditions, recording duration, processing methodology and the scientific objectives of a study.

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

## No Single Quality Score

AusMT does not assign a single numerical quality score to transfer functions or surveys.

A single metric cannot adequately represent:

- Period-dependent behaviour
- Survey objectives
- Acquisition environments
- Processing strategies

Instead, multiple complementary metrics are provided.

Users should interpret these metrics together rather than relying on a single indicator.

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

AusMT may report:

- Minimum period
- Maximum period
- Number of estimated periods
- Period spacing
- Period distribution

Period coverage provides insight into the depth range that may be investigated using a dataset.

---

## Statistical Uncertainty

Transfer-function estimates in the original submitted format (EDI) carry per-period uncertainty estimates.

These may include:

- Impedance uncertainties
- Tipper uncertainties
- Confidence intervals
- Variance estimates

> **Implementation status (current).** AusMT's derived products do not carry these per-period
> values through: the build pipeline collapses per-station uncertainty to a single scalar,
> `median_relative_error` (`mre`), reported in the portal diagnostics. The full per-period VAR
> blocks survive only inside the original served EDI file, not in any derived product. Restoring
> per-period uncertainty to derived products is a possible future enhancement, not current behaviour.

Uncertainty estimates provide information regarding the statistical reliability of transfer-function estimates.

Users who need per-period uncertainty should consult the original EDI's VAR blocks directly.

---

## Error Bars

Apparent resistivity and phase products in the original EDI commonly include per-period uncertainty estimates, conventionally displayed as error bars on quicklook plots produced by external MT software.

> **Implementation status (current).** AusMT does not currently render error bars anywhere in its
> own derived products or portal quicklooks — the portal shows only the single-scalar `mre`
> diagnostic described above. Error-bar display in AusMT-generated plots is planned, not shipped.

Error bars provide a visual indication of the variability associated with a transfer-function estimate.

Large uncertainties do not necessarily imply poor data quality, but they may indicate reduced confidence in a particular estimate.

---

## Transfer Function Consistency

Several products can provide insight into the internal consistency of a transfer function.

Examples include:

- Apparent resistivity behaviour
- Phase behaviour
- Tipper behaviour
- Tensor symmetry indicators
- Period-to-period stability

These diagnostics help users identify unusual features that may warrant further investigation.

---

## Survey Coverage Metrics

Survey-level metrics describe the spatial characteristics of a dataset.

Examples include:

- Number of stations
- Survey extent
- Station spacing
- Profile length
- Survey area

These metrics help users assess whether a survey is appropriate for a particular regional or local-scale application.

---

## Metadata Completeness

Metadata quality influences the long-term usability of a dataset.

AusMT may report the availability of:

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