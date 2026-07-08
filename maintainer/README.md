# Design records

This directory holds the project's dated design records: architecture decision records (ADRs)
and the numbered C-series design documents. Each C-series document froze the design and
security decisions for one subsystem before it was implemented. They are records, not living
documentation: the current state of the system is described by the docs site (`docs/`) and the
repository-root `RUNBOOK-DEV.md`; these files explain why it is built that way.

Amendments are appended in dated sections within each document rather than by editing the
frozen text. A change that contradicts a frozen decision starts with an amendment here.

| Record | Subject |
|--------|---------|
| [ADR-001-repo-structure.md](ADR-001-repo-structure.md) | The repository structure: one framework monorepo plus a separate data repository |
| [C10-GatewayDesign.md](C10-GatewayDesign.md) | Submission gateway: upload, antivirus scan, validation, quarantine (see its Amendments section) |
| [C11-CuratorDesign.md](C11-CuratorDesign.md) | Curator review queue, preview, and publication to the data repository |
| [C11b-PiiAcknowledge.md](C11b-PiiAcknowledge.md) | Curator acknowledgement path for personal-data findings in submitted packages |
| [C13-UploadDesign.md](C13-UploadDesign.md) | The add-survey page's direct upload |
| [C18-BuildCacheDesign.md](C18-BuildCacheDesign.md) | The incremental build cache and its integrity rules (see Amendments) |
| [C20-TfCompletenessDesign.md](C20-TfCompletenessDesign.md) | Transfer-function completeness diagnostic and its screening (not quality) semantics |
| [C31-MetadataEditorDesign.md](C31-MetadataEditorDesign.md) | Curator metadata editor: survey.yaml round-trip, versioning, release notes |
| [C32-BundlesVersionsDesign.md](C32-BundlesVersionsDesign.md) | Per-survey download bundles and served tool versions |
| [C33-OperatorDocsDesign.md](C33-OperatorDocsDesign.md) | Operator documentation and deployment portability |
| [C34-IntakeFilesDesign.md](C34-IntakeFilesDesign.md) | Intake generation of LICENSE.md/README.md into submitted packages before publication |
| [C35b-GitTruthDesign.md](C35b-GitTruthDesign.md) | Test-reality for the publication path: real-git tests, vendored validator contract |
| [UX4-MapAuslampScaling.md](UX4-MapAuslampScaling.md) | Map presentation: programme-based clustering, zoom-scaled markers |
| [UX5-TreeCollections.md](UX5-TreeCollections.md) | Survey tree: collections group and disclosure controls |

The numbering is a running sequence of implementation contracts; numbers absent from this
directory were contracts that changed code without freezing a design document.
