# Versioning and Releases

AusMT versions survey packages, not portal pages. Versioning exists so that a package
downloaded in future is scientifically identical to the version originally published, and so
that a citation can name what was actually used.

## Semantic versioning

Survey packages use `MAJOR.MINOR.PATCH`:

- **PATCH** — metadata-only corrections (`1.0.1`)
- **MINOR** — additions, such as new stations (`1.1.0`)
- **MAJOR** — reprocessed transfer functions (`2.0.0`)

What ships: the validator warns when `version` is missing or not `MAJOR.MINOR.PATCH`, and when
`release_notes` entries are not `{version, date, note}` records. The portal renders
`release_notes` in the survey drawer and uses the latest entry's date in the recently-added
feed.

## Releases

> **Implementation status (current).** Immutable, versioned release archives (one frozen zip
> per published version, never touched again) are a **planned** mechanism. No code generates or
> stores them. `version` in `survey.yaml` is a metadata passthrough: it is recorded and
> displayed, including in MTCAT, but nothing in the build snapshots or freezes bytes per
> version. The history of a package is its git history in the survey repository, and each build
> reconstructs the *current* state fresh.

The intended artefacts are one immutable archive per published version:

```text
vulcan-2022_v1.0.0_survey-package.zip
vulcan-2022_v1.0.0_edi.zip
vulcan-2022_v1.0.0_emtfxml.zip
```

What the build pre-generates today is per-survey EDI and EMTF-XML zips, plus a
transfer-function-only MTH5 bundle behind `flags.survey_h5_enabled` (which ships on). All of
them describe the survey's **current** state. Downloads from a station selection are assembled
on demand in the browser.

A release, once published, is meant never to change: corrections take a new version. In
practice today a correction means editing `survey.yaml` or the transfer functions in place and
rebuilding, and the prior state is recoverable through git history rather than a separately
served archive. Users should cite the version they used.
