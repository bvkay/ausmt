# Environments — reproducing the mt_metadata / mth5 ingest stack

The Phase-1 canonical-ingest path (`ausmt_science.ingest.normalize`) needs the community MT stack
(mt_metadata / mth5). Its behaviour is **version-sensitive** (the metadata-conditioning in
`normalize.py` depends on exact pydantic / mt_metadata validation), so the stack is **pinned**.

## Lock files

| File | What | Use |
|------|------|-----|
| `environment-lock.yml` | Conda lock of the tested env (win-64, captured 2026-06-16; its pip section was edited for the mt_metadata and mth5 pins below, not re-captured) | local/dev on win-64: `conda env create -f environments/environment-lock.yml` |
| `requirements-mtmetadata-lock.txt` | Exact all-pip lock (full transitive pins) | Linux / CI / **the engine image**: `pip install -r requirements-mtmetadata-lock.txt` |
| `environment.yml` | Human-readable source spec (loose major pins) | starting point; not the reproducibility anchor |
| `../requirements-mtmetadata.txt` | Direct deps only (`mt_metadata`, `mth5`); lives in `engine/`, **not** in this `environments/` dir | convenience; transitive deps float — prefer the lock |

Three pins in `requirements-mtmetadata-lock.txt` carry `sys_platform` markers (`colorama`,
`tzdata`, `win32_setctime`): the freeze was taken on Windows and those three are only ever required
there, per their upstream metadata. They install fine anywhere (all are pure-python wheels), so the
markers are for honesty and to keep three inert packages out of the Linux image. `pip freeze` on
Windows emits them unmarked, so re-apply the markers when regenerating.

## Tested versions (2026-06-16, all round-trips pass)

python 3.12.13 · numpy 2.4.6 · scipy 1.17.1 · pandas 3.0.3 · xarray 2026.4.0 · h5py 3.16.0 ·
pydantic 2.13.4 · pyproj 3.7.2 · **mt_metadata 1.0.9 · mth5 0.6.8**

## Current mt_metadata and mth5 pins (2026-09-30)

| Package | Pin | Reports itself as |
|---------|-----|-------------------|
| mt_metadata | `git+https://github.com/kujaku11/mt_metadata.git@22350c51fb176b57ec3bce6f1aeab1b44a9b8c6a`, the commit tag v1.0.11 names | `1.0.10` |
| mth5 | `mth5==0.6.9` from PyPI (tag v0.6.9) | `0.6.9` |

The rest of the closure is unchanged from the 2026-06-16 capture. On python 3.12.14 the engine
suite at the pin-move commit gave the same result on the fork pins and on these (1515 passed,
11 skipped, 1 xfailed), and the sample-survey build was identical apart from version and time stamps.

**Why mt_metadata is pinned to a commit.** v1.0.11 carries kujaku11/mt_metadata#289, the
performance work the build depends on (see below), and it is not on PyPI. PyPI's 1.0.10 predates it.
The v1.0.11 commit still declares `__version__ = "1.0.10"`, so `pip freeze`, `mt_metadata.__version__`
and every served `mt_metadata_version` key read `1.0.10` on this pin, the same string PyPI's 1.0.10
gives. Two consequences:

- pip treats an installed mt_metadata 1.0.10 as satisfying the pin and keeps it without a message.
  Install `requirements-mtmetadata-lock.txt` before anything else that pulls mt_metadata (the CI
  workflow and `deploy/docker/engine.Dockerfile` do), or pass `--force-reinstall`.
- A served version key cannot tell the pinned commit from PyPI's 1.0.10. The installed commit is in
  `mt_metadata-*.dist-info/direct_url.json`.
- Installing the lock, `environment.yml` or `environment-lock.yml` needs `git` on PATH, because pip
  resolves the `git+https` pin by cloning. The engine image installs git before its pip layer.

**When PyPI carries it.** Replace the commit with `mt_metadata==1.0.11` (or the first release
carrying #289) in `../requirements-mtmetadata.txt`, `requirements-mtmetadata-lock.txt`,
`environment.yml` and `environment-lock.yml` together, and check that the release reports the
version it is named for. Then re-read mt_metadata's `information.py` and `define_measurement.py` and
move `extract/edi_preflight.py`'s `MIRRORED_MT_METADATA` to the new version
(`tests/test_edi_preflight.py` fails until it matches), and update the version comment above
`requires-python` in `../pyproject.toml`.

## What the engine relies on the pinned stack for

- **A bounded field-tree memo.** mth5 builds a pydantic model class per group it opens, and
  mt_metadata memoises a field tree per class in `mt_metadata.base.pydantic_helpers._FIELDS_TREE_CACHE`.
  The pinned mt_metadata holds that memo's keys weakly and reuses the class built for an added field
  (kujaku11/mt_metadata#289, commits 97c09616 and 6a361343), so the MTH5 arm of a build stays flat
  without the engine emptying the memo. A mt_metadata without those commits leaks about 7.6 MiB per
  served station. The engine reads the memo's type rather than the version string
  (`extract/_mth5.py`, `field_tree_memo_mode`): on a strong-keyed memo it prints a `[mth5] WARN`
  line at build start and empties the memo after every station-sized MTH5 unit, which bounds the
  build again. `tests/test_build_memory.py` pins both arms, and
  `test_pinned_library_holds_the_field_tree_memo_weakly` fails on an env that got PyPI's 1.0.10.

## ABI history (the important correction)

Earlier notes warned that mixing a **conda/MKL numpy** with **pip/OpenBLAS scipy/pandas/xarray**
crashes mt_metadata's xarray impedance access with a Windows delay-load fault (`0xC06D007F`), and that
you must use an all-pip env. **That is superseded.** The tested env above is exactly that hybrid
(conda-forge python+numpy/MKL + pip scipy/pandas/xarray/h5py/mt_metadata/mth5) and it **works** — the
`normalize` round-trip passes on both standard and Phoenix-spectra EDIs. CI is **all-pip on Linux**,
which is also clean. If you *do* hit `0xC06D007F` on some version combination, realign the BLAS-linked
packages to one source, e.g.:

    pip install --force-reinstall --no-deps numpy scipy pandas xarray

…but it is no longer required by default. The pinned locks above are the reliable path.

## Acceptance gate

A reproduced env is valid when it runs the ingest round-trip gate green:

    pytest -q tests/test_ingest_normalize.py     # needs pytest in the env
