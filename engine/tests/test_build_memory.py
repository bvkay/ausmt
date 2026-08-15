"""Build memory: the MTH5 arm must emit-and-release, so a build's peak RSS is bounded by one
station-sized unit of MTH5 work plus a small corpus-wide index, never by the number of stations.

The incident (production P350, 2026-08-15): the engine was OOM-killed by the kernel five times in one
night ("Killed process (python) anon-rss:13,740,244 kB" on a 14 GB box) at ~2,580 stations, one
night after 2,485 stations had built. Retries with a warm C18 cache (6,349 hits, 1 miss) reached the
same 13.7 GB, so per-station parsing was not the cost. The step-0 profile found every MiB of the
growth inside _write_tf_mth5: mth5 0.6.8 creates a FRESH pydantic model class per group instance
(about 75 per served station across the tier-1 file, the tier-2 bundle and the round-trip gate's
reopen), and mt_metadata 1.0.9's to_dict memoises each class's field tree in the module-global,
class-KEYED dict mt_metadata.base.pydantic_helpers._FIELDS_TREE_CACHE. Never-reused classes as keys
mean the memo never hits and pins every class, its json tree and its pydantic-core validator for the
life of the process: 7.6 MiB per served station, linear, unbounded (8.9 GiB at 1,182 served stations
here, 13.7 GB at 2,580 in production, a projected 41-59 GiB at 8,000).

What is pinned here, and what each pin fails on:

  * the leak itself: after N station-sized MTH5 units, the class-keyed memo is empty and the count of
    live pydantic model classes is what it was after the FIRST unit. FAILS on unmodified code with
    the memo at ~25 entries and ~50 classes per station and climbing.

Requires the mt_metadata/mth5 build stack; skips cleanly otherwise.
"""
import gc
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE_EDIS = sorted((ROOT / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
sys.path.insert(0, str(ROOT / "extract"))
import build_portal as bp  # noqa: E402


def _live_model_classes() -> int:
    """gc census of live pydantic model classes (the ModelMetaclass instances mth5 creates per group
    instance). A full collect first, so what is counted is what is REACHABLE, not what is merely not
    yet collected."""
    from pydantic._internal._model_construction import ModelMetaclass  # noqa: PLC0415
    gc.collect()
    return sum(1 for o in gc.get_objects() if isinstance(o, ModelMetaclass))


def _memo_len() -> int:
    from mt_metadata.base import pydantic_helpers as ph  # noqa: PLC0415
    return len(ph._FIELDS_TREE_CACHE)


def test_mth5_unit_releases_metadata_classes(tmp_path):
    """The leak. Runs the tier-1 unit (_write_tf_mth5 over ONE station: write + SPEC 6 round-trip gate)
    over the two sample EDIs three times each, exactly as emit_station_mth5 does per served station,
    then a tier-2 bundle of both, and asserts after every unit that (a) the class-keyed field-tree
    memo is empty and (b) the number of live pydantic model classes has not moved from what it was
    after the first unit. FAILS on unmodified code: the memo gains ~25 entries and ~50 classes per
    station and never gives them back."""
    assert len(SAMPLE_EDIS) >= 2, "the sample survey ships two EDIs"
    out = tmp_path / "h5"
    out.mkdir()
    units = [(p, {"id": f"{p.stem}_{k}"}) for k in range(3) for p in SAMPLE_EDIS]
    classes_after_first = None
    memo_after = []
    classes_after = []
    for i, (p, r) in enumerate(units):
        n = bp._write_tf_mth5([(p, r)], "memo-survey", "Memo Survey", out / f"{r['id']}.h5")
        assert n == 1, f"unit {i} did not write (the fixture must pass the gate)"
        memo_after.append(_memo_len())
        classes_after.append(_live_model_classes())
        if classes_after_first is None:
            classes_after_first = classes_after[-1]
    # a tier-2 bundle: every station into one file, released per station INSIDE the open file
    n = bp._write_tf_mth5(units[:2], "memo-survey", "Memo Survey", out / "bundle-tf.h5")
    assert n == 2
    memo_after.append(_memo_len())
    classes_after.append(_live_model_classes())
    assert all(m == 0 for m in memo_after), (
        f"mt_metadata's class-keyed field-tree memo must be released after every MTH5 unit; "
        f"observed sizes per unit: {memo_after}")
    assert max(classes_after) <= classes_after_first, (
        f"live pydantic model classes must not grow with the number of MTH5 units written "
        f"(after first unit: {classes_after_first}; per unit: {classes_after})")
