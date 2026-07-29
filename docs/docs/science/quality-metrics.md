# Quality Metrics

MT data quality depends on acquisition conditions, recording duration, processing methodology
and what a study is trying to do. No single number captures that, and AusMT does not rank
stations or surveys. What it publishes are diagnostics: information to assess a dataset with,
not pass-fail criteria.

## The `q` screening scalar

Each station carries a 0-5 scalar, `q`, computed by the build (`_edi_science.py`). It exists so
a user screening hundreds of stations can spot incomplete or rough transfer functions quickly.
It is **not** a data-quality or geological-value ranking, and the portal says so wherever it is
displayed.

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

Known limitations, stated plainly: smoothness uses the xy phase mode only; the error basis uses
off-diagonal resistivity errors only; there is no normalisation across instrument classes, so a
long-period and a broadband station are scored on the same scale. Whether the scalar should be
replaced by the underlying vector of diagnostics (`mre`, decades, completeness, smoothness) is
an open design question to settle with the community.

A single number cannot represent period-dependent behaviour, survey objectives, acquisition
environments or processing strategy. Read `q` with the metrics below, never on its own.

## Period coverage and uncertainty

**Period coverage** is one of the most informative characteristics of an MT dataset, because it
sets the depth range a dataset can speak to. AusMT reports minimum and maximum period, the
number of estimated periods, and decades of coverage.

**Uncertainty.** Transfer-function estimates in the submitted EDI carry per-period uncertainty.

> **Implementation status (current).** Per-period uncertainties for the off-diagonal modes are
> carried through to the portal's transfer-function data product: the `tf` contract includes
> `rho_xy_err`, `rho_yx_err`, `phs_xy_err` and `phs_yx_err` columns alongside the values. The
> per-station summary scalar `median_relative_error` (`mre`) is reported in the portal
> diagnostics. The complete VAR blocks for **all** components remain available in the original
> served EDI file.

**Error bars.** The station drawer renders error bars on the apparent-resistivity and phase
plots wherever the EDI supplies per-period errors: resistivity whiskers in the log domain,
phase whiskers as symmetric ± degrees. Stations whose EDIs carry no error blocks show no bars,
and their `q` falls back to the shape basis. Large uncertainties do not necessarily mean poor
data; they mean less confidence in that estimate.

## Consistency and coverage diagnostics

Several shipped diagnostics describe the internal consistency of a transfer function:

- Phase smoothness (median second-difference roughness, a `q` input)
- A galvanic/static-shift signature heuristic: resistivity modes offset by a near-constant
  factor in log space while phases coincide, flagged with a warning in the station drawer
- Phase-tensor dimensionality diagnostics (see [Dimensionality](dimensionality.md))

At survey level AusMT reports the number of stations and the geographic extent. Derived spatial
metrics (station spacing, profile length, survey area) are not computed today.

## Completeness of the record

The portal surfaces metadata completeness per station as availability badges (EDI, time series,
MTH5, DOI, licence) and a maturity bar covering survey metadata, station metadata,
[provenance](../data-model/provenance.md), citation and identifiers.

Metadata completeness is not scientific quality, and it is not evidence about it. Historical
surveys are frequently thin on documentation and highly valuable anyway, so read every metric
here in the context of the survey and its history. A dataset with sparse metadata can hold
excellent transfer functions, and a thoroughly documented one can still be hard data to work
with.
