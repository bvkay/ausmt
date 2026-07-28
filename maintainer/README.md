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
| [C25-ConventionGates.md](C25-ConventionGates.md) | Ingest convention gates: frame guard and sign-convention check at the parse seam, every EDI, every build (D0 supersedes the earlier frame policy) |
| [C31-MetadataEditorDesign.md](C31-MetadataEditorDesign.md) | Curator metadata editor: survey.yaml round-trip, versioning, release notes |
| [C32-BundlesVersionsDesign.md](C32-BundlesVersionsDesign.md) | Per-survey download bundles and served tool versions |
| [C33-OperatorDocsDesign.md](C33-OperatorDocsDesign.md) | Operator documentation and deployment portability |
| [C34-IntakeFilesDesign.md](C34-IntakeFilesDesign.md) | Intake generation of LICENSE.md/README.md into submitted packages before publication |
| [C35b-GitTruthDesign.md](C35b-GitTruthDesign.md) | Test-reality for the publication path: real-git tests, vendored validator contract |
| [C41-SurveyRetirement.md](C41-SurveyRetirement.md) | Survey lifecycle part A: curator-side retirement of a published survey (rename deferred to part B) |
| [C42-CoordinateAccess.md](C42-CoordinateAccess.md) | Coordinate access model: the custodian chooses exact, generalised or withheld station coordinates |
| [C43-CuratorWorkbench.md](C43-CuratorWorkbench.md) | Curator workbench: per-station and collection curation, scoped on the premise it may be the sole practical entry point |
| [C45-UsageAnalytics.md](C45-UsageAnalytics.md) | Usage analytics: downloads by dataset, visit counts and country, for research-infrastructure reporting |
| [UX4-MapAuslampScaling.md](UX4-MapAuslampScaling.md) | Map presentation: programme-based clustering, zoom-scaled markers |
| [UX5-TreeCollections.md](UX5-TreeCollections.md) | Survey tree: collections group and disclosure controls |
| [C47-PublicBridge.md](C47-PublicBridge.md) | Public demo bridge: a VPS front door on the tailnet exposing the reader only, with two independent walls keeping curator/admin surfaces private |

This table indexes every record in this directory. A file present here but missing from the table
is an error in the table, not a record of lesser standing; the table listed 15 of 20 until
2026-07-28, and the sentence that used to close this file explained the gaps in the *numbering*
in a way that read as an assurance the list itself was complete.

The C-series numbering is a separate matter: it is a running sequence of implementation contracts
with deliberate gaps, so a number with no document here was work that changed code without
freezing a design first. The ADR and UX records sit outside that numbering.
