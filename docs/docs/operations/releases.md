# Releases

## Overview

> **Implementation status (current).** Nothing in the build pipeline generates or stores
> per-version release archives today — this page describes the **planned** release model. The
> current mechanism is: `version` in `survey.yaml` is a metadata passthrough (recorded and shown,
> e.g. in MTCAT), and a build always reconstructs the survey package's *current* bundles from the
> current-state source files. History of prior versions lives in this repository's git history,
> not in a frozen, downloadable per-version archive.

A release is intended to eventually be an immutable published representation of a survey package.

Releases exist to support citation, reproducibility and long-term stewardship.

## Release Artefacts

Typical release artefacts include:

```text
survey_v1.0.0_survey-package.zip
survey_v1.0.0_edi.zip
survey_v1.0.0_emtfxml.zip
```

## Portal Downloads

The build already pre-generates per-survey EDI and EMTF-XML zips (and a transfer-function-only
MTH5 bundle behind a deployment flag) — but for the **current** state of the survey, not as
frozen per-version artefacts.

Custom downloads from station selections are created on demand in the browser.

## Immutability

Once published, a release is intended to never change.

Corrections require a new version and a new release. Today, "correction" in practice means editing
`survey.yaml`/the transfer functions in place and rebuilding — the prior state is recoverable only
through git history, not a separately-served archive.

## Principle

Survey packages evolve through versioning. Users consume published releases.
