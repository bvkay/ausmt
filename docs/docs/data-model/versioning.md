# Versioning

## Overview

Versioning allows survey packages to evolve while preserving reproducibility.

AusMT versions survey packages, not individual portal pages.

## Semantic Versioning

Survey packages use semantic versioning:

```text
MAJOR.MINOR.PATCH
```

Examples:

```text
1.0.0
1.1.0
1.1.1
```

## Releases

> **Implementation status (current).** Immutable, versioned release archives (one frozen zip per
> published version, never touched again) are a **planned** mechanism — no code generates or
> stores them today. What exists now: `version` in `survey.yaml` is a metadata passthrough (it is
> recorded and displayed, e.g. in MTCAT, but nothing in the build pipeline snapshots or freezes
> bytes per version). The actual history of a survey package lives in this repository's git
> history, and each build reconstructs the *current* state fresh — there is no per-version archive
> to download from an earlier release.

Each published version is intended to eventually generate an immutable release archive.

```text
vulcan-2022_v1.0.0_survey-package.zip
```

A release must never be modified after publication.

## Citation

Users should cite the survey package version used in their work.

## Principle

Versioning exists to ensure that a survey package downloaded in the future is scientifically identical to the version originally published.
