# Code and data conventions

Pull requests are reviewed against these.

## What must not break

1. Column order and row alignment of `catalogue`, `sci` and `tf`: append, never reorder, and reference
   columns by name (the imported constants in the engine; `r[C.*]`, `sc[SC.*]`, `t[T.*]` in the
   portal). The contract is in [Portal data files](data-files.md).
2. Uniqueness and stability of `ausmt_id` (`au.<slug>.<station>[.<variant>]`, lowercase,
   dot-separated, permanent, public); existing identifiers are never renumbered or reformatted. A
   survey's `slug` and its folder name must be equal.
3. The single-source status of `_ediparse.pt_params` and of `contract/columns.json`.
4. The `extract/` and `ausmt_science/` separation: `extract/` ships, `ausmt_science/` (other than
   `ingest`) is scaffolding whose modules expose `available()` and a `write()` that raises
   `NotImplementedError`; the two share no imports. Documentation marks planned features as planned and
   drops the marker in the pull request that ships them.
5. Provenance fidelity: every build emits `build_provenance.json`, a new output that affects
   interpretation must be representable there, and recorded parameters are read from named constants,
   never re-typed.
6. Fail-closed behaviour: FAIL blocks and WARNING does not
  ([Submission](../operations/submission.md#validation)); gates must be non-vacuous (an empty survey
  tree fails, an empty build fails without `--allow-empty`, a new gate must demonstrably be able to
  fail); new accepted transfer-function formats go through the validator's extension and magic-byte
  checks.

## Dependencies

- mt_metadata and mth5 are core dependencies, the sole parser stack, pinned in
  `engine/environments/requirements-mtmetadata-lock.txt` (Python 3.12).
- Other libraries are import-gated: a guarded import sets a `HAVE_*` flag and the dependent feature
  degrades or exits with a clear message. PyYAML has a dependency-free fallback (`_mini_yaml`); the test
  suite carries a small schema-check fallback for `jsonschema`. More than one `_mini_yaml` copy exists
  (engine and validator); only the engine's is parity-tested against PyYAML, so consolidate rather than
  add another.
- A new third-party runtime dependency must carry an Apache-2.0-compatible licence.

## Code style

- Engine-internal modules are underscore-prefixed (`_mtm`, `_ediparse`, `_edi_*`).
- `safe_component()` sanitises every user-derived path or identifier component before it touches the
  filesystem or the DOM; route new user-derived identifiers through it.
- The version string is single-sourced from `pyproject` via `importlib.metadata`. File I/O that another
  tool will read passes `encoding="utf-8"` explicitly.
- Docstrings and comments explain why, not what, and cite the science where it applies (Caldwell,
  Egbert, Kelbert). Long orchestration functions are segmented with `# === section ===` banners.
- Portal JavaScript is plain script-order globals with no build step; new code appends to the load
  order. All untrusted strings reaching the DOM go through the `security.js` helpers; CSV cells go
  through the formula-injection guard in `exports.js`.
- Code licence and data licence are separate ([License](../reference/license.md)); keep that boundary
  explicit in user-facing copy and download artifacts.

## Review order

1. What the code does today: read it, do not assume.
2. Why it exists: reconstruct the original constraint before replacing anything.
3. Side effects on the positional contract, `ausmt_id`, `pt_params`, provenance, the empty-build guard.
4. Which modules and cross-repo consumers are affected.
5. The less invasive alternative, then the safest change that meets the need.

Anything under `engine/extract/` that changes a scientific result (dimensionality, phase tensor,
apparent resistivity or phase, the Z solve) needs a golden-test diff and a scientific justification;
the golden and canonical-parity tests must stay green, provenance must still describe what ran,
metadata must not be able to overwrite an observation silently, and new uncertainty must be flagged.
