# Governance and Operation

This page names who operates AusMT, how to reach them, and where responsibility for the data sits.
It is the authoritative public statement; the portal's About page (Governance section) carries the
same content in summary form.

## Who runs AusMT

AusMT is operated by **Ben Kay, National Geophysics Program Manager, AuScope**, as a
pre-institutional deployment of the AusMT framework. The intended long-term home is
AuScope/NCI institutional infrastructure; the framework, catalogue, and survey packages are
designed to transfer to that home without rework (see [Succession](#succession)).

Publication decisions rest with the curator(s). Curators review each submission's metadata,
licensing, access level, and validation results before anything is published; the review
process is described under [Operations → Review](../operations/review.md).

## Contact, corrections, and takedown

**Contact:** <ben@auscope.org.au>

- Questions and correction requests are acknowledged within **five business days**.
- **Takedown requests** for contested data are actioned as a priority: the affected data is
  **withheld from distribution while the matter is resolved** with the originating custodian.
  Discovery metadata may remain visible with a note, or be withdrawn, at the custodian's request.
- Custodians may request changes to their surveys' access level (open, metadata-only, embargoed)
  at any time; access levels are machine-enforced by the build (see
  [Operations → Publication](../operations/publication.md)).

## Data responsibility

Survey data remains the **property and responsibility of its originating custodians** under their
stated licence:

- AusMT redistributes transfer-function files **only** where the survey's licence appears on the
  recognised redistributable list *and* its access level is `open` with no active embargo;
  otherwise the survey is listed as metadata with a pointer to the source archive.
- Responsibility for the **scientific accuracy** of contributed data rests with the originating
  custodian. AusMT records and preserves provenance (original bytes, checksums, processing
  metadata) but does not alter scientific content.
- Contributor contact details are never published in portal data products.

## Succession

AusMT is built so that no data or capability is locked to the current operator:

- The framework is open source (**Apache-2.0**), with a maintainer knowledge base covering
  architecture, conventions, risks, and operations.
- The catalogue and all served packages are **rebuildable from the survey source repository**
  by any operator with one documented command.
- Survey packages are plain files (EDI + `survey.yaml`) under version control; heavyweight
  artifacts are designed to live on institutional storage (NCI THREDDS) referenced by
  pointer, not held by the operator.

## Status of this arrangement

This is a **pre-institutional** operating arrangement, appropriate to the current
private/demonstration phase. Before full public operation, AusMT is intended to move to an
organisational repository home with at least two maintainers, a tagged and DOI'd release,
and formal data-contribution agreements with custodian agencies.
