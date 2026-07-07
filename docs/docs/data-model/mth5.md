# MTH5 Integration

## Overview

AusMT supports multiple transfer-function formats, including:

- EDI
- EMTFXML
- MTH5

The project does not require a single format for publication. Instead, it aims to support existing community standards while encouraging interoperability and long-term preservation.

MTH5 is of particular importance because it provides a modern, extensible framework for storing magnetotelluric data and metadata within a single self-describing format.

For this reason, MTH5 forms a central part of the long-term AusMT strategy.

---

## What is MTH5?

MTH5 is an HDF5-based format developed by the international magnetotelluric community.

The format was designed to address several limitations of older MT data formats by providing a consistent structure for storing:

- Time-series data
- Transfer functions
- Survey metadata
- Station metadata
- Processing information
- Provenance information

MTH5 is closely integrated with the mt_metadata project and forms part of a broader effort to improve interoperability within the MT community.

---

## Why MTH5?

Historically, MT datasets have often been distributed using formats such as EDI.

EDI remains widely used and continues to be supported by many processing and interpretation workflows.

However, EDI was never intended to capture the full range of information associated with modern MT datasets.

In practice, important information is often stored separately:

- Survey metadata
- Processing notes
- Station metadata
- Provenance records
- Publications

MTH5 provides a framework for bringing much of this information together in a structured and machine-readable form.

---

## MTH5 and AusMT

AusMT adopts MTH5 because it aligns with several core project objectives:

### Metadata Preservation

MTH5 provides a consistent framework for storing metadata alongside scientific products.

### Provenance Support

MTH5 supports the recording of processing and lineage information required for reproducibility.

### Interoperability

MTH5 is designed to work closely with community projects such as:

- mt_metadata
- MTpy
- Aurora
- future processing workflows

### Long-Term Stewardship

A structured and self-describing format improves the likelihood that datasets remain understandable and reusable in the future.

---

## Current Reality

Despite growing adoption, much of the global MT archive remains in formats such as:

- EDI
- EMTFXML
- Project-specific formats

Many legacy datasets will likely remain in these formats indefinitely.

AusMT therefore treats MTH5 as part of an evolving ecosystem rather than a replacement for existing formats.

Support for historical formats remains essential.

---

## Supported Publication Formats

> **Implementation status (current).** `transfer_functions/emtfxml/` in a published survey package
> is a **build output**, not an ingest folder — the build pipeline globs
> `transfer_functions/edi/*.edi` for its input and writes the canonical EMTF-XML rendering back out
> alongside it. Submitting EMTFXML directly as the input representation (skipping the EDI) is
> planned, not implemented; today a submitter provides EDI (and/or MTH5), and EMTFXML is generated
> for them.

Published survey packages may contain:

```text
transfer_functions/
├── edi/       # submitted input (first-class)
├── emtfxml/   # generated canonical output (derived from edi/, not submitted directly)
└── mth5/      # submitted input (transfer-function products only)
```

A survey package may contain one, two or all three representations, but only `edi/` and `mth5/` are accepted as submitted input today.

Where multiple formats exist, they should describe the same underlying transfer-function products.

---

## MTH5 as a Preferred Archival Format

From an AusMT perspective, MTH5 is the preferred long-term archival format for MT products.

Reasons include:

- Self-describing structure
- Strong metadata support
- Provenance support
- Community adoption
- Integration with modern software

This does not imply that EDI or EMTFXML are deprecated.

Rather, it recognises that MTH5 provides capabilities that extend beyond traditional transfer-function exchange formats.

---

## Relationship to Time-Series Data

MTH5 was originally designed to support both time-series data and transfer-function products.

AusMT focuses on transfer functions and associated metadata.

Raw time-series archives remain outside the scope of AusMT and are expected to reside within dedicated archival systems.

Where available, survey packages may record links to external MTH5 resources containing the corresponding observational data.

This allows AusMT to maintain traceability without duplicating large-volume archives.

---

## Relationship to mt_metadata

The MTH5 and mt_metadata projects are closely related.

Within AusMT:

- mt_metadata provides metadata models.
- MTH5 provides data structures.
- Survey packages provide publication and discovery structures.

These components serve different purposes but are highly complementary.

---

## Migration and Adoption

The MT community is currently in a period of transition.

Many existing workflows continue to rely on EDI and EMTFXML.

At the same time, new processing and archival systems increasingly adopt MTH5 and mt_metadata.

AusMT is designed to support this transition.

The project does not require immediate migration of legacy datasets.

Instead, survey packages may evolve over time as improved representations become available.

This approach allows historical and contemporary datasets to coexist within a common framework.

---

## Future Directions

The long-term objective is not to promote a particular file format.

The objective is to improve interoperability, reproducibility and long-term usability of MT datasets.

MTH5 currently provides the strongest foundation for achieving those goals and is expected to play an increasingly important role within the broader MT community.

AusMT will continue to support community standards as they evolve while maintaining access to legacy datasets and products.