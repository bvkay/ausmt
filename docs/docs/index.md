# AusMT

AusMT is a survey-centric magnetotelluric (MT) data infrastructure for Australia. It stores
curated survey packages of transfer functions with their metadata, provenance and citation
records, and serves them through a public portal.

The survey is the primary object: a survey package combines transfer functions, metadata,
provenance and citation information into one curated, versioned unit, rather than treating
each file as an independent artifact.

---

## Background

Hundreds of magnetotelluric surveys have been acquired across Australia by universities,
government agencies, research infrastructure programs and industry. Many of the resulting
datasets remain scientifically valuable but sit in personal archives, institutional storage,
project websites, publication supplements or legacy media. Transfer functions often survive
while processing details, metadata or provenance are lost; in other cases the reports survive
while the data become hard to locate.

AusMT provides one consistent framework for survey discovery, transfer-function access,
metadata preservation, provenance tracking and long-term stewardship of these datasets.

---

## Scope

AusMT curates and serves:

- Magnetotelluric transfer functions (EDI and EMTF XML; per-survey MTH5 bundles are built
  only where a deployment enables them)
- Survey and station metadata
- Provenance records
- Citation information
- Derived screening diagnostics (apparent resistivity and phase, tipper, phase-tensor
  parameters, dimensionality)

Further derived products (strike analysis, distortion and decomposition) are planned and are
marked as such wherever they appear in this documentation.

## Out of scope

AusMT is not a waveform archive. Raw time series remain in their original repositories
(national facilities such as NCI, institutional and project archives). Where a survey's
time-series collection has a persistent identifier, the survey package records it, so the
portal links to the waveforms without duplicating them.

---

## Design principles

- **Survey first.** Stations, transfer functions and derived products exist within a survey
  package; identifiers, versions and citations attach to the survey.
- **Reproducible.** Every published value traces to a source file, a content hash, a unique
  identifier and a build provenance record.
- **Interoperable.** Community standards are used throughout: mt_metadata and MTH5 for
  parsing and storage, EDI and EMTF XML for exchange.
- **Curated.** Publication happens through validation and human review, not unrestricted
  upload.
- **Attributable.** Metadata, provenance and citation information are first-class products,
  and data licensing is declared per survey by its custodians.

---

## System architecture

The framework is the `ausmt` repository; survey data lives in the separate `ausmt-surveys`
repository.

```text
submissions -> gateway -> ausmt-surveys -> engine -> portal
               (scan,      (curated        (offline   (static
               validate,    packages)       build)     site)
               curate)
```

- **gateway** — the submission service: upload, antivirus scan, validation, curator review,
  and publication as a git commit to the data repository.
- **ausmt-surveys** — the curated collection of published survey packages: metadata,
  transfer functions and provenance.
- **engine** — the offline build: parses packages with mt_metadata, computes the screening
  diagnostics, and writes the portal's data products, canonical EMTF XML and download
  bundles.
- **portal** — the public discovery and access interface. It consumes generated products and
  performs no scientific processing.

The developer-facing description, including the deployment and the data contract, is in
[Developer architecture](developer/architecture.md).

---

## Intended audience

Researchers, students, survey custodians, data managers, research infrastructure operators,
government agencies, and the archive's future maintainers.

---

## Reading order

1. [What is AusMT?](introduction/what-is-ausmt.md)
2. [Scientific Philosophy](introduction/scientific-philosophy.md)
3. [Architecture](architecture/overview.md)
4. [Data Lifecycle](introduction/data-lifecycle.md)
5. [Survey Package](data-model/survey-package.md)
