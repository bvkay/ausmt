# AusMT

AusMT is a survey-centric magnetotelluric (MT) data infrastructure for Australia. It stores curated
survey packages of transfer functions with their metadata, provenance and citation records, and serves
them through a public portal and a set of machine-readable documents.

The survey is the primary object. A survey package combines transfer functions, metadata, provenance
and citation information into one curated, versioned unit, and identifiers, versions and citations
attach to it rather than to individual files: researchers ask for "the AusLAMP South Australia data",
and the acquisition dates, instrumentation, processing history and publications belong to the survey.

Hundreds of MT surveys have been acquired across Australia by universities, government agencies,
research infrastructure programs and industry. Many sit in personal archives, institutional storage,
project websites or legacy media, and reuse fails in recognisable ways: transfer functions survive while
their metadata are lost, processing workflows are undocumented, several versions circulate with no
authoritative source. AusMT is one consistent framework for discovering those surveys, fetching their
transfer functions, and preserving their metadata and provenance.

## Scope

AusMT curates and serves transfer functions as EDI, EMTF XML and MTH5 (per station and per survey);
survey and station metadata, provenance records and citation information; and derived screening
diagnostics (apparent resistivity and phase, tipper, phase-tensor parameters, dimensionality). Strike
and distortion products are planned and marked as such wherever they appear.

## Out of scope

AusMT does not archive raw data. Time series remain in their original repositories (national
facilities such as NCI, institutional and project archives). Where a survey's time-series collection
has a persistent identifier, the survey package records it, so the portal links to the time series
without duplicating them; see [External archives](interoperability/external-archives.md).

## Design principles

- **Survey first.** Stations, transfer functions and derived products exist within a survey package.
- **Reproducible.** Every published value traces to a source file, a content hash, a unique identifier
  and a build provenance record.
- **Interoperable.** mt_metadata and MTH5 for parsing and storage, EDI and EMTF XML for exchange.
- **Curated.** Publication happens through validation and human review, not unrestricted upload.
- **Attributable.** Metadata, provenance and citation are first-class products; data licensing is
  declared per survey by its custodians.

## System architecture

```text
submissions -> gateway -> ausmt-surveys -> engine -> portal
               (scan,      (curated        (offline   (static
               validate,    packages)       build)     site)
               curate)
```

The **gateway** uploads, scans, validates, takes curator review and publishes as a git commit;
**ausmt-surveys** holds the curated packages; the **engine** parses them with mt_metadata, computes the
screening diagnostics and writes the data products, canonical EMTF XML and download bundles; the
**portal** consumes generated products and performs no scientific processing. See
[Architecture](architecture/repositories.md) and [Developer architecture](developer/architecture.md).

## Where to start

**Using the data.** [How AusMT serves data](interoperability/api-overview.md), the
[data reference](interoperability/api-reference.md), [tool integration](interoperability/tool-integration.md),
and the [Reference section](reference/index.md) for the contracts field by field.

**Contributing a survey.** [Data lifecycle](introduction/data-lifecycle.md),
[Submission](operations/submission.md), and the [survey.yaml reference](reference/survey-yaml.md).

**Working on the code.** [Developer architecture](developer/architecture.md),
[Build lifecycle](developer/build-lifecycle.md), then [Portal data files](developer/data-files.md)
for the positional contract.
