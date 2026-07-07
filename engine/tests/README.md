# tests/

Test suite for the engine. Run with `pytest -q`. Install `requirements-dev.txt` (which
pulls the core `mt_metadata`/`mth5` engine + the test tooling); for the pinned engine CI runs, also
`pip install -r environments/requirements-mtmetadata-lock.txt` into a clean Python 3.12 venv.

Since the 2026-06 regex-parser retirement, `mt_metadata` is the
sole parser, so the build/pipeline tests require it. The mt_metadata-dependent tests `importorskip`,
so they skip cleanly if the stack is somehow absent rather than erroring.

## Which fixture corpus to use

There are three deliberately-separate fixture sets. Pick by what you are testing:

| Corpus | What it is | Use it for |
|---|---|---|
| `data/sample-survey/` (repo root, **not** under tests/) | a small, valid survey **package** (`survey.yaml` + 2 EDIs) | end-to-end build tests and CI: `python -m extract.build_portal --surveys data …`, and `scripts/verify.py`. The canonical "does the whole pipeline run" sample. |
| `tests/fixtures/example-survey/` | a minimal survey package fixture | unit/integration tests that need a self-contained package without touching `data/`. |
| `tests/real_dialects/` | real EDIs from distinct instrument/processing dialects (`edl_birrp_*`, `lemi_birrp_*`, `phoenix_empower_*`) | locking mt_metadata dialect handling (`test_real_dialects.py`, the Phoenix golden test). |

Rule of thumb: **build/pipeline test → `data/sample-survey`; parser/dialect test → `tests/real_dialects`;
package-shape test → `tests/fixtures/example-survey`.**

## Adding a test

- Tests import the engine modules via a `sys.path.insert(... / "extract")` bootstrap at the top of
  each file (there is no `conftest.py`); copy that from an existing test.
- The science/catalogue row layouts are positional — see `docs` → `developer/data-files.md`
  (and the `*_COLUMNS` constants) before asserting on `sc[5]`, `row[8]`, etc.
- Add a new dialect sample to `tests/real_dialects/` and a case to `test_real_dialects.py`; add a
  golden assertion against the mt_metadata output so the dialect handling stays locked.
