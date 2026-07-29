# AusMT

AusMT is a survey-centric magnetotelluric (MT) data infrastructure for Australia. It stores
curated survey packages of transfer functions with their metadata, provenance and citation
records, and serves them through a public portal.

The survey is the primary object: a survey package combines transfer functions, metadata,
provenance and citation information into one curated, versioned unit, rather than treating
each file as an independent artifact.

It is built for researchers, students, survey custodians, data managers, research
infrastructure operators, government agencies, and the archive's future maintainers.

---

## Background

Hundreds of magnetotelluric surveys have been acquired across Australia by universities,
government agencies, research infrastructure programs and industry. They support research into
lithospheric architecture, crustal evolution, mineral systems, groundwater systems, geothermal
resources, natural hydrogen systems and tectonic processes. Many of the resulting datasets
remain scientifically valuable but sit in personal archives, institutional storage, project
websites, publication supplements or legacy media.

Reuse then fails in recognisable ways:

- Transfer functions survive while their metadata are lost.
- Metadata survive while the data become hard to locate.
- Processing workflows are undocumented, or the software no longer exists.
- Several versions of a dataset circulate with no authoritative source.
- Survey information is scattered across reports, publications and personal archives.
- Publication practice differs between organisations.

AusMT provides one consistent framework for survey discovery, transfer-function access,
metadata preservation, provenance tracking and long-term stewardship of these datasets.

## Why the survey, not the file

A folder of EDI files rarely says enough. A user also needs acquisition dates,
instrumentation, processing history, provenance, publications and citation information, and
all of that belongs to the survey rather than to any one file. Researchers ask for the
AusLAMP South Australia data or the Vulcan dataset, not for a station file. So the survey
package is what AusMT publishes, versions, cites and serves, and identifiers attach to it.

---

## Scope

AusMT curates and serves:

- Magnetotelluric transfer functions (EDI and EMTF XML, plus a per-survey transfer-function
  MTH5 bundle behind a deployment flag that ships on)
- Survey and station metadata
- Provenance records
- Citation information
- Derived screening diagnostics (apparent resistivity and phase, tipper, phase-tensor
  parameters, dimensionality)

Further derived products (strike analysis, distortion and decomposition) are planned and are
marked as such wherever they appear in this documentation.

## Out of scope

AusMT does not archive raw data. Time series remain in their original repositories
(national facilities such as NCI, institutional and project archives). Where a survey's
time-series collection has a persistent identifier, the survey package records it, so the
portal links to the time series without duplicating them. How those links are recorded is in
[External archives](interoperability/external-archives.md).

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

[Architecture](architecture/repositories.md) covers the components in full;
[Developer architecture](developer/architecture.md) is the maintainer's view.

---

## Where to start

Three paths through this documentation.

**Using the data.** [How AusMT serves data](interoperability/api-overview.md), then the
[data reference](interoperability/api-reference.md) for every served document, then
[tool integration](interoperability/tool-integration.md) for reading the artifacts in MT
software. Four hops from here to a working fetch.

**Contributing a survey.** [Data lifecycle](introduction/data-lifecycle.md) for the shape of
the journey, [Submission](operations/submission.md) for how to submit and what the validator
checks, and the [survey.yaml reference](reference/survey-yaml.md) for every field.

**Working on the code.** [Developer architecture](developer/architecture.md), then
[Build lifecycle](developer/build-lifecycle.md), then
[Portal data files](developer/data-files.md) for the positional contract.

For the reasoning rather than the mechanism, read
[Scientific philosophy](introduction/scientific-philosophy.md) and the
[design rationale](rationale/credit-model.md) pages.
