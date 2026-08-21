# Architecture

AusMT is the public `ausmt` monorepo plus the separate, private `ausmt-surveys` data repository. The
framework is public because it is meant to be inspected and reused; the survey-data repository is
private because it holds embargoed material.

```text
ausmt-surveys     Published survey packages (separate, private repo)
ausmt/engine      Offline processing and product generation
ausmt/gateway     Submission service: upload, scan, validate, curate, publish
ausmt/portal      Public website and machine-readable products
ausmt/docs        System documentation
ausmt/contract    Single-source data contract (columns.json)
ausmt/deploy      Container images and deployment configuration
ausmt/maintainer  Design and security decision records
```

## Component roles

**ausmt-surveys** holds the published scientific record: one folder per survey under `surveys/`, plus
the package template, a worked example, the survey validator and the migration scripts for retired
`survey.yaml` fields. No raw time series and no processing environment. See
[Survey package](../data-model/survey-package.md).

**engine** is the offline build. It parses packages with mt_metadata, computes the screening
diagnostics, and writes the portal's data products, the canonical EMTF XML and the download bundles.
Its dependencies are mt_metadata, MTH5, numpy and a YAML parser; none reach the portal. See
[Build lifecycle](../developer/build-lifecycle.md).

**gateway** receives uploads into quarantine, scans them, validates them, builds a preview, and
publishes an approved package as a git commit, its only output. See
[Submission](../operations/submission.md).

**portal** is the public discovery and access interface: map, collection, survey and station views,
downloads, citation export, and the machine-readable JSON products. It reads generated products and
computes nothing scientific (it may display a phase-tensor plot; it must not compute one from an EDI at
request time), which keeps every published number reproducible from a build.

## Information flow

```text
submissions -> ausmt/gateway -> ausmt-surveys -> ausmt/engine -> generated products -> ausmt/portal
```

The engine writes generated products into the portal's data directory and never back into the survey
repository; the only component that writes to `ausmt-surveys` is the gateway's publish step. Nothing
downstream modifies what is published upstream.

Code, documentation and the website share a release cycle; published survey products have a different
audience, release cycle and access rules, so they stay in their own repository, and the embargo boundary
is a repository boundary rather than a convention. A folder per survey inside `ausmt-surveys` is enough
for almost every case.

## Trust boundaries

- Submitted material is untrusted: quarantined, scanned, validated and reviewed before publication.
- Published packages are the curated record and the source everything else is built from.
- Derived products come from the engine, traceable to their input transfer functions and software
  versions, never produced on demand by the portal.
- The portal displays; it authors no scientific output.

The implementation, including the network-disabled parsing container and the contact-details rule, is
in [Developer architecture](../developer/architecture.md).
