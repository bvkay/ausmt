# Code and data conventions

The rules that keep changes consistent with the existing codebase. Pull requests are reviewed against
these.

## The positional contract

Append, never reorder, and reference columns by name (the imported constants in the engine; `r[C.*]`,
`sc[SC.*]`, `t[T.*]` in the portal) rather than by raw integer. The contract and the change procedure
are in [Portal data files](data-files.md).

## Dependencies

- mt_metadata and mth5 are core dependencies, the sole parser stack. Their pinned versions live in
  `engine/environments/requirements-mtmetadata-lock.txt` (Python 3.12).
- Other libraries are import-gated: a guarded import sets a `HAVE_*` flag and the dependent feature
  degrades or exits with a clear message. PyYAML has a dependency-free fallback (`_mini_yaml`); the test
  suite carries a small schema-check fallback for `jsonschema`.
- More than one `_mini_yaml` implementation exists (engine and validator copies); only the engine's is
  parity-tested against PyYAML. Consolidate rather than add another.
- A new third-party runtime dependency must carry an Apache-2.0-compatible licence.

## Naming and identity

- `ausmt_id` is `au.<slug>.<station>[.<variant>]`, lowercase, dot-separated, permanent and public.
  Existing identifiers are never renumbered or reformatted.
- A survey's `slug` and its folder name must be equal; the validator fails the package otherwise.
- Engine-internal modules are underscore-prefixed (`_mtm`, `_ediparse`, `_edi_*`).
- `safe_component()` sanitises every user-derived path or identifier component before it touches the
  filesystem or the DOM. Route new user-derived identifiers through it.

## Planned versus shipped

- `extract/` ships; `ausmt_science/` (other than `ingest`) is scaffolding. The two share no imports.
- Planned modules expose `available()` and a `write()` that raises `NotImplementedError`.
- Documentation marks planned features as planned, and the marker is removed in the same pull request
  that ships the feature.

## Provenance and reproducibility

- Every build emits `build_provenance.json`. A new output that affects interpretation must be
  representable there, and recorded parameters are read from the code's named constants, never re-typed.
- The version string is single-sourced from `pyproject` via `importlib.metadata`.
- File I/O that another tool will read passes `encoding="utf-8"` explicitly.

## Validation

- FAIL blocks; WARNING does not, and that is a governance principle
  (see [Submission](../operations/submission.md#validation)).
- New accepted transfer-function formats go through the validator's extension and magic-byte checks;
  several formats are deliberately opt-in.
- Gates must be non-vacuous: an empty survey tree fails, an empty build fails without `--allow-empty`,
  and a new gate must demonstrably be able to fail.

## Code style

- Docstrings and comments explain why, not what, and cite the science where it applies (Caldwell,
  Egbert, Kelbert).
- Long orchestration functions are segmented with `# === section ===` banners rather than extracted
  prematurely.
- Portal JavaScript is plain script-order globals with no build step. New code appends to the load
  order and communicates via globals; a bundler or module system is a deployment-model decision.
- All untrusted strings reaching the DOM go through the `security.js` helpers; CSV cells go through the
  formula-injection guard in `exports.js`.

## Review checklist

1. What the code does today: read it, do not assume.
2. Why it exists: reconstruct the original constraint before replacing anything.
3. Side effects: the positional contract, `ausmt_id`, `pt_params`, provenance, the empty-build guard.
4. Which modules and cross-repo consumers are affected.
5. The less invasive alternative.
6. The safest change that meets the need.

For anything under `engine/extract/` that changes a scientific result (dimensionality, phase tensor,
apparent resistivity or phase, the Z solve): a golden-test diff and a scientific justification are
required; the golden and canonical-parity tests must stay green; provenance must still describe what
ran; metadata must not be able to overwrite an observation silently; new uncertainty must be flagged.

## Licensing

Code licence and data licence are separate ([License](../reference/license.md)). Keep that boundary
explicit in user-facing copy and download artifacts.
