# Environments — reproducing the mt_metadata / mth5 ingest stack

The Phase-1 canonical-ingest path (`ausmt_science.ingest.normalize`) needs the community MT stack
(mt_metadata / mth5). Its behaviour is **version-sensitive** (the metadata-conditioning in
`normalize.py` depends on exact pydantic / mt_metadata validation), so the stack is **pinned**.

## Lock files

| File | What | Use |
|------|------|-----|
| `environment-lock.yml` | Exact conda lock of the tested env (win-64, captured 2026-06-16) | local/dev on win-64: `conda env create -f environments/environment-lock.yml` |
| `requirements-mtmetadata-lock.txt` | Exact all-pip lock (full transitive pins) | Linux / CI: `pip install -r requirements-mtmetadata-lock.txt` |
| `environment.yml` | Human-readable source spec (loose major pins) | starting point; not the reproducibility anchor |
| `../requirements-mtmetadata.txt` | Direct deps only (`mt_metadata`, `mth5`); lives in `engine/`, **not** in this `environments/` dir | convenience; transitive deps float — prefer the lock |

## Tested versions (2026-06-16, all round-trips pass)

python 3.12.13 · numpy 2.4.6 · scipy 1.17.1 · pandas 3.0.3 · xarray 2026.4.0 · h5py 3.16.0 ·
pydantic 2.13.4 · pyproj 3.7.2 · **mt_metadata 1.0.9 · mth5 0.6.8**

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
