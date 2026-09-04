"""Build memory: the MTH5 arm must emit-and-release, so a build's peak RSS is bounded by one
station-sized unit of MTH5 work plus a small corpus-wide index, never by the number of stations.

The incident: the engine was OOM-killed by the kernel five times in one
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
  * the bound, end to end: two synthetic corpora built by the real CLI with the production flag set,
    the SAME largest survey in each and 10x the surveys in the second, and the peak RSS of the two
    child processes (os.wait4 rusage, independent of anything the engine reports) must not grow with
    the station count faster than SLOPE_MAX_MIB_PER_STATION. This is the guard against the next
    feature quietly re-materialising the world. The measured constant and slope are recorded below.
  * the record: build_report.json carries `peak_rss_mib`, schema-valid, and it agrees with the
    child's own rusage peak (the field is a measurement, not a guess).

Requires the mt_metadata/mth5 build stack; skips cleanly otherwise. The two subprocess pins need
os.wait4 (POSIX), which every CI engine workflow has.
"""
import gc
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE_SURVEYS = ROOT / "data"          # data/sample-survey: two real EDIs, CC-BY-4.0, open
SAMPLE_EDIS = sorted((ROOT / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
sys.path.insert(0, str(ROOT / "extract"))
import build_portal as bp  # noqa: E402
# The C42 module's engine-produced fixture writer (one EDI per station, distinctive positions, a
# Survey.yaml). Reused so the synthetic corpora are the SAME shape the coordinate-access workflow builds.
from test_coord_access import _stage_survey  # noqa: E402

# ---- the regression pin's recorded numbers on the fixed engine, macOS, the pinned
# mt_metadata 1.0.9 / mth5 0.6.8 stack; a Linux glibc box measures lower absolute peaks) ----
# corpora: A = 2 surveys x 10 stations (20), B = 20 surveys x 10 stations (200); same largest survey.
# The 180-station delta halves the slope's noise against the 80-station delta first used (two runs of
# 2x10,10x10 on the fixed engine read 0.138 and 0.025 MiB/station: about +-0.06 of noise for the cost
# of one 10 MiB wobble in a peak); 2x10,20x10 read 0.114 with the same constant.
MEMPIN_SIZES = os.environ.get("AUSMT_MEMPIN_SIZES", "2x10,20x10")   # "<surveys>x<stations>,..." (2 corpora)
# The pin: peak RSS may grow by at most this much per extra station between the two corpora. The
# leak this guards against measured 7.6 MiB per served station on the real corpus (5.3 MB/station in
# production at 2,580 stations) and 9.1 MiB per station on these small fixtures (unmodified engine:
# 428 MiB at 20 stations -> 1,158 MiB at 100); the fixed engine measures 0.11 (recorded below). A
# lighter retention than the fault also fails: keeping every TF object alive for the build (a
# module-level list of tf in _write_tf_mth5) measured 1.56 MiB/station on these fixtures, three times
# this limit; the limit itself is 0.5 = 3.9 GiB at 8,000 stations, over four times the measured slope
# and eight times its noise, so a machine's malloc wobble cannot fail it and half a TF per station can.
SLOPE_MAX_MIB_PER_STATION = 0.5
# Recorded fixed-engine measurements (for the reader; not asserted, the machine varies): the run that
# set these sizes measured 266 MiB at 20 stations and 287 MiB at 200, i.e. peak = constant + slope*N:
MEASURED_CONSTANT_MIB = 264            # the corpus-independent floor: interpreter + libraries + one survey
MEASURED_SLOPE_MIB_PER_STATION = 0.114  # the corpus-wide index (catalogue rows, records) per station


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
    """The leak. Runs the tier-1 unit (_write_tf_mth5 over ONE station: write + clause 6 round-trip gate)
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
    # the MTH5-INPUT arm (a survey shipping transfer_functions/mth5/*.h5, read by process_mth5 through
    # _mth5.records_and_components, one get_transfer_function per station): the same leak class, so
    # the same per-station release. Read the bundle just written and census after every station.
    import _mth5 as m5  # noqa: PLC0415
    n_read = 0
    for _rec, _per, _comp in m5.records_and_components(out / "bundle-tf.h5"):
        n_read += 1
        memo_after.append(_memo_len())
        classes_after.append(_live_model_classes())
    assert n_read == 2, "the reader must yield both stations of the bundle"
    memo_after.append(_memo_len())            # after the reader closed the file
    classes_after.append(_live_model_classes())
    assert all(m == 0 for m in memo_after), (
        f"mt_metadata's class-keyed field-tree memo must be released after every MTH5 unit "
        f"(written OR read); observed sizes per unit: {memo_after}")
    assert max(classes_after) <= classes_after_first, (
        f"live pydantic model classes must not grow with the number of MTH5 units written or read "
        f"(after first unit: {classes_after_first}; per unit: {classes_after})")


# --------------------------------------------------------------------------- the end-to-end bound

def _run_build_measured(surveys: Path, out: Path, log: Path) -> tuple[int, float]:
    """Run the real CLI with the production flag set as a child process and return (returncode,
    peak_rss_mib) where the peak is the child's own rusage ru_maxrss via os.wait4: measured by the
    kernel, independent of anything the engine writes. KiB on Linux, bytes on macOS."""
    cmd = [sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys), "--out", str(out),
           "--products", str(out / "products"), "--bundle-edi", "--survey-h5", "--station-h5",
           "--no-validate"]
    with log.open("w", encoding="utf-8") as fh:
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
        _pid, status, ru = os.wait4(p.pid, 0)
        p.returncode = os.waitstatus_to_exitcode(status)
    raw = ru.ru_maxrss
    nbytes = raw if sys.platform == "darwin" else raw * 1024
    return p.returncode, nbytes / (1024 * 1024)


def _stage_corpus(base: Path, n_surveys: int, n_stations: int) -> int:
    """n_surveys packages of n_stations stations each, ids unique corpus-wide, positions inside the
    fixture extent. Returns the station count."""
    base.mkdir(parents=True, exist_ok=True)
    for k in range(n_surveys):
        sts = [{"id": f"MP{k:02d}{s:03d}", "lat": -34.5 + k * 0.03 + s * 0.001,
                "lon": 134.5 + s * 0.03 + k * 0.001, "elev": 100.0 + s, "policy": "exact"}
               for s in range(n_stations)]
        _stage_survey(base, sts, declare_policy=False, slug=f"mempin-{k:02d}", name=f"Mempin {k:02d}")
    return n_surveys * n_stations


def _sizes():
    out = []
    for tok in MEMPIN_SIZES.split(","):
        a, b = tok.lower().split("x")
        out.append((int(a), int(b)))
    assert len(out) == 2 and out[0][1] == out[1][1] and out[1][0] > out[0][0], (
        "AUSMT_MEMPIN_SIZES must name two corpora with the SAME stations-per-survey and more surveys "
        f"in the second (got {MEMPIN_SIZES!r})")
    return out


@pytest.mark.skipif(not hasattr(os, "wait4"), reason="os.wait4 (POSIX rusage) not available on this platform")
def test_peak_rss_is_bounded_per_survey_not_per_corpus(tmp_path):
    """THE REGRESSION PIN. Two synthetic corpora with the same largest survey, the second holding 10x
    the surveys (10x the stations); both built by the real CLI with the production flags (tier-1 and
    tier-2 MTH5, EDI bundles, products). Peak RSS of each child (os.wait4) must not grow faster than
    SLOPE_MAX_MIB_PER_STATION per extra station: the build's memory is bounded by ONE survey plus a
    small corpus-wide index, never by the corpus. FAILS on unmodified code, where the MTH5 arm holds
    ~4-5 MiB per station on these fixtures (7.6 on the real corpus) and the slope reads that."""
    (na, sa), (nb, sb) = _sizes()
    peaks = {}
    counts = {}
    for label, (n_surveys, n_stations) in (("A", (na, sa)), ("B", (nb, sb))):
        surveys = tmp_path / f"surveys_{label}"
        counts[label] = _stage_corpus(surveys, n_surveys, n_stations)
        rc, peak = _run_build_measured(surveys, tmp_path / f"out_{label}", tmp_path / f"build_{label}.log")
        assert rc == 0, (tmp_path / f"build_{label}.log").read_text(encoding="utf-8")[-3000:]
        man = json.loads((tmp_path / f"out_{label}" / "manifest.json").read_text(encoding="utf-8"))
        h5 = [r for r in man["files"] if r["format"] == "mth5"]
        assert len(h5) == counts[label], f"corpus {label}: every station must reach the MTH5 arm"
        peaks[label] = peak
    d_stations = counts["B"] - counts["A"]
    slope = (peaks["B"] - peaks["A"]) / d_stations
    constant = peaks["A"] - slope * counts["A"]
    print(f"\n[mempin] A={counts['A']} stations peak={peaks['A']:.0f} MiB; "
          f"B={counts['B']} stations peak={peaks['B']:.0f} MiB; "
          f"slope={slope:.3f} MiB/station; constant={constant:.0f} MiB (max slope {SLOPE_MAX_MIB_PER_STATION})")
    assert slope <= SLOPE_MAX_MIB_PER_STATION, (
        f"peak RSS grew {slope:.2f} MiB per station between {counts['A']} and {counts['B']} stations "
        f"({peaks['A']:.0f} -> {peaks['B']:.0f} MiB): the build is holding something per station again "
        f"(limit {SLOPE_MAX_MIB_PER_STATION} MiB/station; the 2026-08-15 leak measured 7.6)")


@pytest.mark.skipif(not hasattr(os, "wait4"), reason="os.wait4 (POSIX rusage) not available on this platform")
def test_build_report_records_peak_rss(tmp_path):
    """build_report.json carries the build's own memory high-water mark as `peak_rss_mib`: a positive
    number, schema-valid, and consistent with the child's kernel-measured peak (at most the process
    peak, and not less than half of it: the report is written after the survey loop, where the memory
    is). FAILS on unmodified code (no such field), or on a field that stops being a measurement."""
    jsonschema = pytest.importorskip("jsonschema")
    out = tmp_path / "out"
    rc, peak = _run_build_measured(SAMPLE_SURVEYS, out, tmp_path / "build.log")
    assert rc == 0, (tmp_path / "build.log").read_text(encoding="utf-8")[-3000:]
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert "peak_rss_mib" in rep, f"build_report.json must record peak_rss_mib; keys: {sorted(rep)}"
    v = rep["peak_rss_mib"]
    assert isinstance(v, (int, float)) and v > 0, v
    assert v <= peak * 1.02 + 1, f"reported {v} MiB exceeds the process's own peak {peak:.0f} MiB"
    assert v >= 0.5 * peak, f"reported {v} MiB is not the build's high-water mark (process peak {peak:.0f} MiB)"
    schema = json.loads((ROOT / "schema" / "build_report.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(rep, schema)
    assert "peak_rss_mib" in schema["properties"], "the field must be schema-documented"
    log = (tmp_path / "build.log").read_text(encoding="utf-8")
    assert "build peak RSS:" in log, "the build log must state the peak on one line an operator can read"

