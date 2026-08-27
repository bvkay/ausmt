# Build lifecycle and invariants

What one build run does, how it reports failure, and the invariants operational changes must preserve.

## The build, step by step

The production invocation, from `deploy/Makefile`:

```text
python -m extract.build_portal --surveys <dir> --out <data> --products <dir> --bundle-edi --survey-h5 --station-h5 --workers auto
```

`--bundle-edi` gates the entire served-download surface, per-survey EDI copies and manifest rows
included; `--survey-h5` enables the per-survey MTH5 bundles and `--station-h5` the per-station MTH5
files. The engine image ships without the portal config, so these flags, not `portal.config.yaml`, are
the production enables.

`--workers N|auto` parallelises the MTH5 writes (the dominant build cost: ~68% of a cold build,
~99% of a warm rebuild) across worker processes; `auto` means `min(6, cpus)`. Only the MTH5 writes
fan out. Parsing, EMTF XML, the build cache and all manifest bookkeeping stay in the main process,
and the engine's `test_build_parallel` pins a parallel build's products as indistinguishable from a
serial build's. The default without the flag is 1, the serial build; `deploy/Makefile`'s
`rebuild-data` passes `auto` (override with `AUSMT_BUILD_WORKERS` in the deploy `.env`).

`--ts-index <dir>` names a root of per-survey time-series registers (`<package>/ts-index.yaml`,
written out of band by the `ausmt-surveys` crawler; point it at the `--surveys` root to read each
package's own file). The build reads them as FILES and never contacts the archive, so a build stays
reproducible from its inputs. Rows are validated against the same closed vocabularies the survey
validator applies, and a row naming a station the package does not publish aborts the build: the
register is the only record of which remote file belongs to which station, so an unmatched row would
publish a download route under an identifier nothing assigned. Without the flag no register is read
and the output is byte-identical to a build from before the flag existed.

1. Parse arguments; create the output directories; resolve the survey validator (`AUSMT_VALIDATOR_PATH`
   or the documented search path). An unresolvable validator aborts the build.
2. Discover survey packages: one folder per survey containing `survey.yaml` and
   `transfer_functions/edi|emtfxml|mth5/`. Folders prefixed `_` are skipped; a package that fails
   validation is skipped and reported.
3. Record provenance: git commit, versions, extractor, dimensionality parameters.
4. Extract: mt_metadata parses each input once into a canonical record and component dict. Standard
   and Phoenix SPECTRA EDI dialects are read natively; EMTF XML and MTH5 input go through the same
   component dict. Where a station is supplied as both an EDI and an EMTF XML the EDI wins;
   `build_report.json` records the source per station. The same pass reads the `>INFO` block for
   acquisition facts: mt_metadata recovers none of them, and the custodians wrote them six different
   ways, so `extract/_runfacts.py` carries one extractor per dialect (the AusMT header enrichment's
   dotted `run.*` keys, MTpy `fieldnotes.*`, the LEMIMT `SITE` and `Instrument` lines, Phoenix
   EMpower's record JSON, Phoenix MTU field sheets and compact JSON, and the Geotools survey header,
   which states no acquisition fact at all). Every value carries an extraction-confidence class, and
   an uncertain parse emits nothing: a missing field beats a confidently wrong number. Three facts
   the corpus carries are declined rather than extracted, and the LEMIMT `SITE` line's `S-<rate>Hz`
   band is one of them: it records the merging of downsampled EDI files, not the rate the station was
   acquired at.
5. Derive: TF rows, science diagnostics, catalogue rows; coordinate QC and declared coordinate
   resolutions applied; station-id variants disambiguated.
6. QC: duplicate `ausmt_id` values fail the build (exit 2); other findings go to `qc_report.json`.
7. Emit: the JSON product set, per-station products, canonical EMTF XML, bundles, the SHA-256 manifest
   and the digest sidecar that verify reads (operator-only, never a served surface).
8. Verify (`scripts/verify.py`, run separately by the deployment Makefile): schema checks plus the
   cache-independent consistency check of served XML against current survey.yaml, read off the digest
   sidecar.

With `--incremental --cache-dir`, unchanged stations are served from the build cache, keyed on the EDI
bytes, the engine commit, library versions, the column contract and the `survey.yaml` digest, so it can
only affect build speed, never output bytes; a degenerate salt (an unknown or dirty engine commit)
disables it. Raw/bulk mode (`--raw` with `--collections` and `--seed-meta`, for regenerating a seed from
loose EDI folders) is excluded from caching; see [How to extend](extending.md#bulk-and-seed-mode).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success, or an empty build with `--allow-empty` |
| 2 | duplicate `ausmt_id`; or an empty build without `--allow-empty`; or an argument error |
| nonzero via `sys.exit(message)` | the required mt_metadata/mth5 stack is absent, or MTH5 input was requested without `mth5` |

An empty build fails by design: a green run that produced nothing would make every other green check
meaningless.

## Invariants

- **Parity.** The component dict feeds the same mathematics whether the transfer function came from an
  EDI, an EMTF XML or an MTH5 file; any difference between input formats is parsing or storage
  round-trip, never science (`tests/test_canonical_parity.py`, `tests/test_emtfxml_input.py`).
- **Traceability.** Every published value traces to a source file (`r[10]`), a content hash (`r[14]`),
  a unique identifier (`r[12]`) and `build_provenance.json`.
- **Build/render decoupling.** The portal renders whatever product set its `data_base_url` serves. The
  committed `portal/data/` files are the empty template; real data comes from a build output directory
  (in deployment `site-data/current`, swapped atomically after verification).
- **Package resolution.** `extract` and `ausmt_science` are installed packages; module resolution does
  not depend on the working directory, though the runner still passes an explicit `AUSMT_ENGINE_DIR`.

The portal loads its scripts in fixed order, fetches the required products (catalogue, tf, sci,
surveys) and the optional ones (provenance, collections, build), joins them by array index into the
station table, and renders; all exports are client-side. Submissions flow through the gateway, not
through direct pull requests ([Submission](../operations/submission.md)); published packages enter
`ausmt-surveys`, and the next build serves them.

## The build report

`build_report.json` is the structured per-survey record of what a build produced: stations built and
stations dropped (each with the gate's reason), the survey-scoped warnings, EMTF-XML emission failures,
the ingest source of each station (`edi`, `emtfxml` or `mth5`), the served-bytes integrity result for
copied EDIs, the parse-only fallbacks, the canonical-conditioning, frame and presence notes aggregated
by distinct note, the build-cache counters, per-survey wall time, and the build's peak RSS. Its identity
fields
come from the helpers that write `build.json`, so the two cannot disagree about which commits produced
a build.

`presence` is the report of the presence rule. mt_metadata instantiates a complete run for every
transfer function it reads, whether or not the file states one, so a parse routinely carries a run id
synthesised as `<station>a`, a 0 Hz rate, a 1980 epoch window, an unnamed data logger, a 0-ohm contact
resistance and a pair of `rr*` remote-reference channels. None of those is a source assertion and none
is ever published as one; the rows record, per survey and per distinct note, which of them that
survey's parses carried, so a value the emitter drops is visible to a curator rather than silently
absent. The rows are logged as `[presence] NOTICE` lines from the same aggregation that writes them.

`run_extraction` is the other half of the same provenance question, keyed by station id: not what was
a library default, but which `>INFO` dialect asserted each real acquisition value and how confidently
it was read. Every extractor classifies its output as `formal_edi_field`, `structured_dialect`,
`pattern_extracted`, `curator_supplied` or `inferred`, and `station.json` publishes the value alone,
so this is where the class is kept. It is the difference between a logger a structured dialect stated
and one pattern-matched out of a LEMIMT free-text line. Stations whose `>INFO` asserted nothing are
omitted.

It is not a public surface. The curator workbench reads it over the private listener, and
`scripts/verify.py`, the alert and doctor scripts read it from disk. It carries no stability promise and
is not a contract. Its schema is `engine/schema/build_report.schema.json` (JSON Schema draft-07, `$id`
`https://ausmt.org/schema/build-report-1.0.schema.json`); the build validates the document in its
self-check and the verify step re-checks its presence, its schema and a station-count cross-check
against the download manifest. Every survey entry is a closed object; `totals` is
`{surveys, stations_built, warnings}`.

Three things it states that nothing else does. `ingest_sources` is the only record of which stations
the EDI-wins rule resolved to EDI and which came from EMTF XML; an `emtfxml` station's served EDI is
generated, so the digest of the file the custodian supplied matches neither of its manifest rows.
`source_integrity` is the evidence that a copied custodian EDI landed byte for byte: a mismatch removes
the served file, drops its manifest row and raises a counted warning. `source_parse_fallbacks` lists
the files read through a normalised temporary copy (the mt_metadata 1.0.9 `>INFO` JSON defect); the
copy is never served or hashed, and the custodian's bytes are what is served.

An `xml_failures` entry means different things by source. An `edi`-sourced station falls back to its
custodian EDI and loses only its XML download; an `emtfxml`-sourced station has no custodian file
behind it and serves nothing, and the build removes the two unverified files. Every such entry is also
counted into `warnings`, so a green build cannot hide it.
