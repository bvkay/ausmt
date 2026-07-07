# Loading real surveys into the pipeline

How to turn a real set of transfer functions into a published AusMT survey, end to end.

## 1. Prepare the package

Either copy the template and edit it, or use the browser tool:

- **Manual**: `cp -r ausmt-surveys/_example/example-survey ausmt-surveys/surveys/<your-slug>`, then
  edit `survey.yaml` and drop the transfer functions into `transfer_functions/edi/` (and/or
  `transfer_functions/mth5/`). The `slug` MUST equal the folder name.
- **Add Survey page** (`portal/add-survey.html`): drop your EDIs in the browser, fill the form,
  **confirm station locations on the map** (this resolves the DMS HEAD/INFO conflict and writes
  `coordinate_resolution`), then download the package zip and unzip it under `surveys/<your-slug>/`.

A package is:

```text
<slug>/
├── survey.yaml
├── README.md
├── LICENSE.md
└── transfer_functions/
    ├── edi/      and/or
    └── mth5/
```

## 2. Validate

```bash
cd ausmt-surveys
python _validation/validate_survey.py surveys/<your-slug> --json /tmp/report.json
```

Fix any `FAIL`. WARNINGs (e.g. no DOI yet) do not block. See the [Curator checklist](curator-checklist.md).

## 3. Build the portal data

```bash
cd ../ausmt/engine
python -m extract.build_portal --surveys ../../ausmt-surveys/surveys --out ../portal/data --products products
```

- The extractor is `mt_metadata` (the community library) — it reads EDI (incl. Phoenix SPECTRA) and
  MTH5. It is a required dependency on Python 3.12 (install
  `environments/requirements-mtmetadata-lock.txt`); the build fails loudly if it is absent.
- The build refuses to emit empty products unless `--allow-empty` (the trust invariant).

## 4. Review & publish

Open a pull request adding `surveys/<your-slug>/`. CI runs the authoritative validator; a curator
reviews against the [Curator checklist](curator-checklist.md) and removes the private submitter block
before publication.

## Bulk / seed mode

To regenerate a large demo from loose EDI folders without packaging each one:

```bash
python -m extract.build_portal --raw <edi_root> --collections <map.json> --seed-meta <seed.json> \
       --out ../portal/data
```

This path uses `state_of()` to split AusLAMP into per-state surveys; survey-package mode does not.
