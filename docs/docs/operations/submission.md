# Submission Workflow

## Overview

AusMT is a curated repository.

Survey packages are submitted for review rather than published directly.

This approach helps ensure that published datasets are discoverable, interpretable and accompanied by sufficient metadata and provenance information to support future reuse.

The objective is not to restrict data sharing. The objective is to ensure that published survey packages remain useful long after the original project has concluded.

---

## How Submission Works Today (the Gateway)

Submissions run through the AusMT **submission gateway** — a small service alongside the portal
(the portal's *Add survey* page packages your files and uploads them directly). Every submission
follows the same fail-closed pipeline:

1. **Upload** — the package is received into quarantine and assigned a tracking id with a private
   status link.
2. **Antivirus scan** — nothing advances until the scan completes.
3. **Validation** — the survey validator checks structure, metadata, licensing and EDI parseability,
   and an engine preview build proves the package actually builds.
4. **Curation** — a human curator reviews the validated package, its reports, and a rendered preview
   before approving.
5. **Publication** — approval commits the package to the survey repository; the live portal picks it
   up at the next data rebuild.

At every step the system refuses rather than guesses: an unreadable package, an unrecognised
licence, or an unscanned file stops the pipeline with an explicit state rather than publishing
something ambiguous. Submitter contact details are held separately from the package and never enter
the published record.

The gateway's security design is frozen in the maintainer knowledge base
(`maintainer/C10-GatewayDesign.md` and successors) for readers who want the full detail.

---

## Who Can Submit Data?

Submissions may be made by:

- Researchers
- Survey custodians
- Universities
- Government agencies
- Research infrastructure facilities
- Industry partners

The submitter should have the authority to publish the dataset or act on behalf of the data custodian.

---

## What Can Be Submitted?

AusMT accepts survey packages containing:

- Survey metadata
- Station metadata
- Transfer-function products
- Provenance information
- Citation information
- References to related publications and external resources

Transfer-function formats:

- **EDI** — accepted by default (first-class input; the only format the build pipeline parses into
  derived products such as the canonical EMTF-XML rendering and the portal's `tf.json`)
- **MTH5** — accepted by default (transfer-function products only; never raw time series)
- **EMTFXML** (and processing-software products such as `.zmm` / `.zrr` / `.j`) — accepted on an
  opt-in basis. "Accepted" here means the file passes the validator's file-type gate and is stored
  in the submission package; it is **not** parsed into any built product. The automated validator
  FAILs these by default and a curator enables them per submission (the `--allow-optin-formats`
  flag in `validate_survey.py`; `--allow-mth5` still works as a deprecated alias). This keeps the
  default submission surface small while still allowing these formats where a reviewer expects them.

A survey package may contain one or more of these formats.

---

## What Should Not Be Submitted?

AusMT is not a time-series archive, document repository or media archive.

The following should be stored elsewhere:

- Raw MT time-series data
- Native recorder files
- Processing workspaces
- Site photographs
- PDF reports
- Journal articles
- Presentations
- Project backups
- Large supplementary datasets

Where these resources exist, survey packages should provide references to the appropriate external repository, archive or publication.

---

## Before Submitting

Before preparing a submission, contributors should ensure that:

- The dataset can be shared.
- Ownership is clear.
- Licensing requirements have been considered.
- Metadata are available.
- Transfer-function products have been identified.
- References to related publications have been recorded where available.

Historical datasets are welcome, even when metadata are incomplete.

Contributors are encouraged to provide as much contextual information as possible, but incomplete metadata should not prevent the preservation of scientifically valuable datasets.

---

## Submission Package

The survey package is the unit of submission.

A typical submission contains:

```text
survey-slug/
├── survey.yaml
├── README.md
├── LICENSE.md
└── transfer_functions/
    ├── edi/                 # default
    ├── mth5/                # default
    └── emtfxml/             # optional (curator-enabled)
```

(`LICENSE.md` is checked by the validator. There is no `stations.csv` — station-level
information is read from the transfer-function files themselves, not a separate sheet.
Submitter-side provenance lives in `survey.yaml`'s `processing.*` and free-text fields;
there is no separate provenance file, and derived products are never submitted — the build
generates them.)

Publication references, external resources and identifiers are recorded within the metadata rather than stored as separate files.

---

## Validation

Submitted packages undergo automated validation.

Validation checks include:

- Package structure (survey.yaml present, transfer functions under the expected directories)
- Required metadata (name, licence, access level; semantic version and release-notes shape)
- Coordinate sanity checks, including DMS/decimal cross-checks
- Transfer-function file-type gates, signature checks and EDI parseability
- File-size caps

Validation produces one of three outcomes:

```text
PASS
WARNING
FAIL
```

### PASS

The package satisfies all required validation checks.

### WARNING

The package is valid but contains issues that should be reviewed.

Examples include:

- Missing recommended metadata
- Incomplete provenance
- Missing publication references
- Missing identifiers

### FAIL

The package contains issues that prevent publication.

Examples include:

- Invalid metadata
- Missing required fields
- Unsupported formats
- Corrupted transfer-function products

---

## Review

Automated validation is only one part of the submission process.

Published survey packages are also reviewed.

Review may consider:

- Data ownership
- Licensing
- Metadata quality
- Provenance completeness
- Collection membership
- Scientific consistency

The purpose of review is to improve long-term usability and discoverability.

---

## Publication

Following validation and review, the survey package may be accepted for publication.

Publication typically includes:

- Addition to a collection
- Generation of derived products
- Catalogue registration
- Portal indexing
- Machine-readable discovery via the static MTCAT document (`mtcat.json`) and portal `data/*.json`
  — a REST API is planned but not yet implemented (see [API Overview](../interoperability/api-overview.md))

Once published, the survey package becomes part of the curated AusMT record.

---

## Updating Existing Surveys

Survey packages may be updated after publication.

Examples include:

- Metadata corrections
- Additional provenance
- New publication references
- New derived products
- Additional transfer-function formats
- Improved documentation

Updates follow the same validation and review process as initial submissions.

Published changes are tracked through the AusMT versioning model.

---

## CARE Considerations

Some datasets may have additional cultural, community or governance considerations that extend beyond technical metadata requirements.

Submitters should identify any known restrictions, agreements or obligations associated with the survey during submission.

Examples may include:

- Indigenous data governance requirements
- Cultural heritage considerations
- Community agreements
- Access restrictions
- Embargo requirements

The presence of CARE-related considerations does not necessarily prevent publication, but they should be recorded and reviewed as part of the curation process. This recording is manual (the `care.*` fields in `survey.yaml`) and reviewed by a human curator — no automated check currently blocks publication on CARE grounds.

---

## Historical Datasets

Many historically important MT surveys contain incomplete metadata or provenance.

AusMT recognises this reality.

The absence of perfect metadata should not prevent valuable datasets from being preserved and shared.

Where information is missing, survey packages should record what is known and identify gaps where appropriate.

Improving a dataset over time is generally preferable to leaving it unpublished.

---

## Stewardship

Submission is the beginning of a survey package's life within AusMT, not the end.

Metadata may be improved.

Additional provenance may be recovered.

New publication references may become available.

Derived products may be regenerated using improved methods.

The submission workflow is designed to support that ongoing stewardship while maintaining a clear and traceable record of what has been published.