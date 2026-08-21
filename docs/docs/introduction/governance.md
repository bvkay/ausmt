# Governance and Operation

Who operates AusMT, how to reach them, and where responsibility for the data sits. The portal's About
page carries the same content in summary form.

## Who runs AusMT

AusMT is an AuScope funded initiative, operated with the Australian MT community, as a pre-institutional
deployment of the AusMT framework. The intended long-term home is AuScope/NCI institutional
infrastructure; the framework, catalogue and survey packages are designed to transfer there without
rework.

Publication decisions rest with the curator(s), who review each submission's metadata, licensing,
access level and validation results before anything is published; see [Review](../operations/review.md).

## Contact, corrections, and takedown

**Contact:** <ben@auscope.org.au>

- Questions and correction requests are acknowledged within five business days.
- Takedown requests for contested data are actioned as a priority: the affected data is withheld from
  distribution while the matter is resolved with the originating custodian. Discovery metadata may
  remain visible with a note, or be withdrawn, at the custodian's request.
- Custodians may request changes to their surveys' access level (open, metadata-only, embargoed) at any
  time; access levels are machine-enforced by the build (see
  [Publication](../operations/publication.md)).

## Data responsibility

Survey data remains the property and responsibility of its originating custodians under their stated
licence:

- AusMT redistributes transfer-function files only where the survey's licence is on the recognised
  redistributable list and its access level is `open` with no active embargo; otherwise the survey is
  listed as metadata with a pointer to the source archive.
- Responsibility for the scientific accuracy of contributed data rests with the originating custodian.
  AusMT records and preserves provenance (original bytes, checksums, processing metadata) and does not
  alter scientific content.
- Contributor contact details are never published in portal data products.

## Succession

- The framework is open source (Apache-2.0), with the design and security decisions behind each
  subsystem recorded in the repository beside the code.
- The catalogue and all served packages are rebuildable from the survey source repository by any
  operator with one documented command.
- Survey packages are plain files (EDI plus `survey.yaml`) under version control; heavyweight artifacts
  are designed to live on institutional storage (NCI THREDDS) referenced by pointer.

## Status of this arrangement

This is a pre-institutional operating arrangement. The framework code is public and the portal's public
reader is served at <https://ausmt.auscope.org.au>, including the machine-readable products under
`/data/`. The curator and administrative surfaces are not exposed there, and the survey-data repository
is private because it holds embargoed material. Before full public operation, AusMT is intended to move
to an organisational repository home with at least two maintainers, a tagged and DOI'd release, and
formal data-contribution agreements with custodian agencies.
