"""Both MTH5 tiers are build-cache entries: h5/<slug>/<station>.h5 and bundles/<slug>-tf.h5.

Design: maintainer/C18-BuildCacheDesign.md. The pins here:

  * a warm build places every MTH5 file by HARDLINK to the cache payload (same inode), skips the
    MTH5 write and the round-trip gate for it, and the placed file still passes
    mth5_survey_roundtrip_ok against the stations of THAT build;
  * equality is SEMANTIC: an independent write differs from a cached one only in the root
    `file.access.time` attribute and in the raw address bytes of HDF5 object references, so the
    comparator below resolves references to object names and drops that one attribute, and every
    other attribute and dataset is compared exactly;
  * the station key binds every input that reaches the file, and the survey key is derived from the
    sorted member station keys, so a one-byte EDI edit moves the station file AND its survey file,
    and nothing in another survey;
  * ro never writes, refresh rewrites, a degenerate salt never touches the cache, a corrupt payload
    is deleted, counted and recomputed, a failed hardlink falls back to a counted copy;
  * build_provenance.json carries per-kind counters and the build WARNs when the size cap evicted;
  * the prune only ever touches cache entries: a foreign file in the cache root survives it.

Every test states how it fails. The integration tests patch cache._dirty_checkout to clean and pin
the engine commit, exactly as test_build_cache.py's clean_salt does, so a dirty dev worktree cannot
turn the cache inert and a moving HEAD cannot flip the salt between two builds.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")
h5py = pytest.importorskip("h5py")
np = pytest.importorskip("numpy")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402
import cache as cache_mod  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
N = len(SAMPLE_EDIS)
KINDS = ("parse", "xml", "station_h5", "survey_h5")
KIND_FIELDS = ("hits", "misses", "writes", "corrupt", "link_fallbacks", "evicted")


@pytest.fixture
def clean_salt(monkeypatch):
    """The cache fires deterministically: the dirty-checkout gate INPUT reads clean, the engine
    commit is pinned (never a live rev-parse between two builds), the cap env and worker env are
    cleared."""
    monkeypatch.setattr(cache_mod, "_dirty_checkout", lambda cwd: False)
    monkeypatch.setattr(build_portal, "_git_commit_at",
                        lambda cwd: "testpin" if Path(cwd) == build_portal.HERE else None)
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    monkeypatch.delenv("AUSMT_CACHE_MAX_MB", raising=False)
    monkeypatch.delenv("AUSMT_BUILD_WORKERS", raising=False)


def _write_pkg(root: Path, slug: str, name: str, yaml_extra: str = "") -> Path:
    edir = root / slug / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (root / slug / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
        f"access: open\nlicense: CC-BY-4.0\n{yaml_extra}", encoding="utf-8")
    for src in SAMPLE_EDIS:
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    return root / slug


def _one_survey(tmp_path) -> Path:
    root = tmp_path / "surveys"
    _write_pkg(root, "mc-a", "Cache MTH5 A")
    return root


def _two_surveys(tmp_path) -> Path:
    """The sample survey composed twice under two slugs: the SAME EDI bytes in both, so the only
    thing keeping their entries apart is the survey-level key material."""
    root = tmp_path / "surveys"
    _write_pkg(root, "mc-a", "Cache MTH5 A")
    _write_pkg(root, "mc-b", "Cache MTH5 B")
    return root


def _build(surveys, out, cache_dir, mode="rw", workers=None, extra=None):
    argv = ["--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate",
            "--survey-h5", "--station-h5"]
    if cache_dir is not None:
        argv += ["--incremental", "--cache-dir", str(cache_dir), "--cache-mode", mode]
    if workers is not None:
        argv += ["--workers", str(workers)]
    if extra:
        argv += extra
    rc = build_portal.main(argv)
    assert rc == 0, f"build rc={rc}"
    return out


def _prov_cache(out: Path) -> dict:
    return json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))["cache"]


def _kind(out: Path, kind: str) -> dict:
    return _prov_cache(out)["kinds"][kind]


def _served_h5(out: Path) -> dict:
    return {p.relative_to(out).as_posix(): p for p in sorted(out.rglob("*.h5"))}


def _payloads(cache_dir: Path, kind: str) -> list:
    return sorted(p for p in cache_dir.rglob(f"*.{kind}") if p.is_file())


def _stations_by_survey(out: Path) -> dict:
    """{slug: [(served EDI path, {"id": station})]} from the manifest's EDI rows. The served EDI is
    a byte copy of the source (the integrity ledger pins that), so it is the build's own station
    input for the round-trip gate."""
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    by = {}
    for r in man["files"]:
        if r["format"] == "edi":
            slug = r["url"].split("/")[1]
            by.setdefault(slug, []).append((out / r["url"], {"id": r["station"]}))
    return by


# ---- semantic HDF5 comparison ---------------------------------------------------------------------

VOLATILE_ATTRS = {"/@file.access.time"}


def _canon(f, v):
    if isinstance(v, h5py.Reference):
        return ("ref", f[v].name if v else None)
    if isinstance(v, np.void) and v.dtype.names:
        return tuple(_canon(f, v[n]) for n in v.dtype.names)
    if isinstance(v, np.ndarray):
        if v.dtype.names or v.dtype.kind == "O":
            return ("arr", v.shape, [_canon(f, x) for x in v.reshape(-1)])
        return ("arr", v.dtype.str, v.shape, v.tobytes())
    if isinstance(v, np.generic):
        return repr(v.item())
    return repr(v)


def _h5_semantic(path: Path) -> dict:
    """Every attribute and dataset of an HDF5 file, object references resolved to the NAME they
    point at, minus the write clock. Two writes of the same inputs are equal under this map."""
    out = {}
    with h5py.File(path, "r") as f:
        for k, a in f.attrs.items():
            out[f"/@{k}"] = _canon(f, a)

        def visit(name, obj):
            for k, a in obj.attrs.items():
                out[f"/{name}@{k}"] = _canon(f, a)
            if isinstance(obj, h5py.Dataset):
                out[f"/{name}#"] = _canon(f, obj[()])
        f.visititems(visit)
    for k in VOLATILE_ATTRS:
        out.pop(k, None)
    return out


def test_semantic_comparator_sees_value_changes_but_not_the_write_clock(tmp_path):
    """FAILS IF: the comparator every other test leans on is blind. Two independent writes of one
    station must compare EQUAL (they differ in bytes), and a write of a value-changed EDI must
    compare UNEQUAL."""
    import time
    src = SAMPLE_EDIS[0]
    a, b, c = tmp_path / "a.h5", tmp_path / "b.h5", tmp_path / "c.h5"
    assert build_portal._write_tf_mth5([(src, {"id": "S1"})], "s", "S", a)
    time.sleep(1.05)
    assert build_portal._write_tf_mth5([(src, {"id": "S1"})], "s", "S", b)
    assert a.read_bytes() != b.read_bytes(), "two writes were byte-identical: the premise moved"
    assert _h5_semantic(a) == _h5_semantic(b)
    edited = tmp_path / src.name
    edited.write_text(_one_byte_impedance_edit(src.read_text(encoding="latin-1")), encoding="latin-1")
    assert build_portal._write_tf_mth5([(edited, {"id": "S1"})], "s", "S", c)
    assert _h5_semantic(a) != _h5_semantic(c), "the comparator cannot see an impedance change"


def _one_byte_impedance_edit(txt: str) -> str:
    """Change ONE byte of the first ZXYR datum: its last mantissa digit, so the value provably moves."""
    m = re.search(r"(>ZXYR[^\n]*\n\s*)(-?\d+\.\d+)([eE][+-]?\d+)?", txt)
    assert m, "no ZXYR datum to edit"
    i = m.end(2) - 1
    d = txt[i]
    return txt[:i] + str((int(d) + 1) % 10) + txt[i + 1:]


# ---- cold then warm ------------------------------------------------------------------------------

def test_warm_build_hardlinks_both_tiers_and_skips_write_and_gate(tmp_path, clean_salt, monkeypatch):
    """FAILS IF: a warm build rewrites an MTH5 file it could have linked, re-runs the round-trip gate
    on a cache hit, serves a file that is not the cache payload's inode, or serves bytes that differ
    from the populating build (the manifest is then byte-identical too, h5 sha256 included)."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    cold = _build(surveys, tmp_path / "cold", cache)
    k_st, k_sv = _kind(cold, "station_h5"), _kind(cold, "survey_h5")
    assert (k_st["hits"], k_st["misses"], k_st["writes"]) == (0, N, N), k_st
    assert (k_sv["hits"], k_sv["misses"], k_sv["writes"]) == (0, 1, 1), k_sv
    assert len(_payloads(cache, "station_h5")) == N and len(_payloads(cache, "survey_h5")) == 1

    calls = {"write": 0, "gate": 0}
    real_write, real_gate = build_portal._write_tf_mth5, build_portal.mth5_survey_roundtrip_ok

    def _count_write(*a, **k):
        calls["write"] += 1
        return real_write(*a, **k)

    def _count_gate(*a, **k):
        calls["gate"] += 1
        return real_gate(*a, **k)
    monkeypatch.setattr(build_portal, "_write_tf_mth5", _count_write)
    monkeypatch.setattr(build_portal, "mth5_survey_roundtrip_ok", _count_gate)
    warm = _build(surveys, tmp_path / "warm", cache)
    monkeypatch.setattr(build_portal, "_write_tf_mth5", real_write)
    monkeypatch.setattr(build_portal, "mth5_survey_roundtrip_ok", real_gate)
    assert calls == {"write": 0, "gate": 0}, f"a warm build wrote or gated an MTH5 file: {calls}"

    k_st, k_sv = _kind(warm, "station_h5"), _kind(warm, "survey_h5")
    assert (k_st["hits"], k_st["misses"], k_st["writes"]) == (N, 0, 0), k_st
    assert (k_sv["hits"], k_sv["misses"], k_sv["writes"]) == (1, 0, 0), k_sv

    payload_inodes = {p.stat().st_ino for k in ("station_h5", "survey_h5") for p in _payloads(cache, k)}
    served = _served_h5(warm)
    assert len(served) == N + 1, sorted(served)
    for rel, p in served.items():
        assert p.stat().st_ino in payload_inodes, f"{rel} is not a hardlink to a cache payload"
    assert (warm / "manifest.json").read_bytes() == (cold / "manifest.json").read_bytes(), \
        "the warm manifest differs from the populating build's"


def test_warm_h5_files_pass_the_roundtrip_gate_against_this_builds_stations(tmp_path, clean_salt):
    """FAILS IF: a file placed from the cache would fail the round-trip gate the miss build ran:
    every warm station file against its one station, every warm survey file against all of its
    stations, each station read from THIS build's served EDI."""
    surveys = _two_surveys(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    warm = _build(surveys, tmp_path / "warm", cache)
    assert _kind(warm, "station_h5")["hits"] == 2 * N and _kind(warm, "survey_h5")["hits"] == 2
    by = _stations_by_survey(warm)
    assert sorted(by) == ["mc-a", "mc-b"], sorted(by)
    for slug, stations in by.items():
        ok, rep = build_portal.mth5_survey_roundtrip_ok(warm / "bundles" / f"{slug}-tf.h5", stations)
        assert ok and rep["checked"] == N, (slug, rep)
        for (p, r) in stations:
            ok, rep = build_portal.mth5_survey_roundtrip_ok(warm / "h5" / slug / f"{r['id']}.h5", [(p, r)])
            assert ok and rep["checked"] == 1, (slug, r, rep)
    # The two slugs carry identical EDI bytes, yet each survey file groups under its OWN slug.
    for slug in ("mc-a", "mc-b"):
        with h5py.File(warm / "bundles" / f"{slug}-tf.h5", "r") as f:
            assert list(f["Experiment/Surveys"].keys()) == [slug]


def test_one_byte_edi_edit_moves_its_station_and_survey_files_only(tmp_path, clean_salt):
    """FAILS IF: a one-byte EDI change is served from a stale MTH5 entry at either tier, or it
    disturbs anything outside its own survey. Exact arithmetic: the edited station misses (1) and
    its survey file misses (1); every other station file (2N-1) and the other survey file (1) hit."""
    surveys = _two_surveys(tmp_path)
    cache = tmp_path / "cache"
    cold = _build(surveys, tmp_path / "cold", cache)
    target = sorted((surveys / "mc-a").rglob("*.edi"))[0]
    target.write_text(_one_byte_impedance_edit(target.read_text(encoding="latin-1")), encoding="latin-1")
    warm = _build(surveys, tmp_path / "warm", cache)
    k_st, k_sv = _kind(warm, "station_h5"), _kind(warm, "survey_h5")
    assert (k_st["hits"], k_st["misses"]) == (2 * N - 1, 1), k_st
    assert (k_sv["hits"], k_sv["misses"]) == (1, 1), k_sv

    cold_h5, warm_h5 = _served_h5(cold), _served_h5(warm)
    moved = sorted(rel for rel in warm_h5 if _h5_semantic(warm_h5[rel]) != _h5_semantic(cold_h5[rel]))
    sid = [r["station"] for r in json.loads((cold / "manifest.json").read_text(encoding="utf-8"))["files"]
           if r["format"] == "edi" and r["url"].endswith(f"mc-a/{target.name}")][0]
    assert moved == sorted(["bundles/mc-a-tf.h5", f"h5/mc-a/{sid}.h5"]), moved
    by = _stations_by_survey(warm)
    ok, rep = build_portal.mth5_survey_roundtrip_ok(warm / "bundles" / "mc-a-tf.h5", by["mc-a"])
    assert ok, rep


def _h5_org(path: Path, slug: str) -> str:
    with h5py.File(path, "r") as f:
        return str(f[f"Experiment/Surveys/{slug}"].attrs.get("acquired_by.organization"))


def test_survey_yaml_edit_misses_that_survey_only(tmp_path, clean_salt):
    """FAILS IF: a survey.yaml edit is served from a stale MTH5 entry (the survey metadata travels
    inside every file of that survey), or it colds the OTHER survey. The edited field is the
    organisation, which reaches the file only through the survey metadata (it is not the label),
    so a key that drops the survey.yaml digest and the SMETA projection serves the old value."""
    surveys = _two_surveys(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    y = surveys / "mc-a" / "survey.yaml"
    y.write_text(y.read_text(encoding="utf-8").replace("organisation: Test Org",
                                                       "organisation: Edited Org"), encoding="utf-8")
    warm = _build(surveys, tmp_path / "warm", cache)
    k_st, k_sv = _kind(warm, "station_h5"), _kind(warm, "survey_h5")
    assert (k_st["hits"], k_st["misses"]) == (N, N), k_st
    assert (k_sv["hits"], k_sv["misses"]) == (1, 1), k_sv
    assert _h5_org(warm / "bundles" / "mc-a-tf.h5", "mc-a") == "Edited Org"
    assert _h5_org(warm / "bundles" / "mc-b-tf.h5", "mc-b") == "Test Org"
    station = sorted((warm / "h5" / "mc-a").glob("*.h5"))[0]
    assert _h5_org(station, "mc-a") == "Edited Org", f"{station.name} carries a stale organisation"


# ---- modes, salt, corruption, fallback -----------------------------------------------------------

def test_refresh_rewrites_and_ro_never_writes(tmp_path, clean_salt):
    """FAILS IF: refresh reads an MTH5 hit or leaves the old payload in place, or ro writes a single
    cache file (ro against an empty cache must leave it empty; ro against a populated cache hits
    and leaves the listing unchanged)."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "ro_empty", cache, mode="ro")
    assert not any(p.is_file() for p in cache.rglob("*")), "ro persisted cache files"
    assert _kind(tmp_path / "ro_empty", "station_h5")["writes"] == 0

    _build(surveys, tmp_path / "cold", cache)
    before = {p: p.stat().st_ino for p in _payloads(cache, "station_h5") + _payloads(cache, "survey_h5")}
    ref = _build(surveys, tmp_path / "refresh", cache, mode="refresh")
    for k, n in (("station_h5", N), ("survey_h5", 1)):
        c = _kind(ref, k)
        assert (c["hits"], c["misses"], c["writes"]) == (0, n, n), (k, c)
    after = {p: p.stat().st_ino for p in _payloads(cache, "station_h5") + _payloads(cache, "survey_h5")}
    assert set(after) == set(before)
    assert all(after[p] != before[p] for p in before), "refresh did not rewrite the payloads"

    listing = sorted((p.relative_to(cache).as_posix(), p.stat().st_ino) for p in cache.rglob("*")
                     if p.is_file())
    ro = _build(surveys, tmp_path / "ro_warm", cache, mode="ro")
    assert _kind(ro, "station_h5")["hits"] == N and _kind(ro, "survey_h5")["hits"] == 1
    assert sorted((p.relative_to(cache).as_posix(), p.stat().st_ino) for p in cache.rglob("*")
                  if p.is_file()) == listing, "ro changed the cache"


def test_corrupt_payload_is_deleted_counted_and_recomputed(tmp_path, clean_salt):
    """FAILS IF: a bit-rotted station payload is linked into the served tree instead of being
    re-hashed, deleted, counted corrupt and recomputed; or the recompute leaves the cache without a
    good entry (the next build must hit everything)."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    cold = _build(surveys, tmp_path / "cold", cache)
    victim = _payloads(cache, "station_h5")[0]
    raw = bytearray(victim.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    tmp = victim.with_name(victim.name + ".rot")
    tmp.write_bytes(bytes(raw))
    os.replace(tmp, victim)   # cache-side rot only: the served cold tree keeps its own inode
    warm = _build(surveys, tmp_path / "warm", cache)
    c = _kind(warm, "station_h5")
    assert (c["corrupt"], c["misses"], c["hits"], c["writes"]) == (1, 1, N - 1, 1), c
    for rel, p in _served_h5(warm).items():
        assert _h5_semantic(p) == _h5_semantic(cold / rel), f"{rel}: corrupt bytes shipped"
    again = _build(surveys, tmp_path / "again", cache)
    c = _kind(again, "station_h5")
    assert (c["hits"], c["misses"], c["corrupt"]) == (N, 0, 0), c


def test_corrupt_sidecar_is_deleted_counted_and_recomputed(tmp_path, clean_salt):
    """FAILS IF: a damaged sidecar (the entry's own checksum line) is trusted, or not counted."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    ref = sorted(cache.rglob("*.survey_h5.ref"))
    assert len(ref) == 1, ref
    raw = bytearray(ref[0].read_bytes())
    raw[-3] ^= 0x01
    ref[0].write_bytes(bytes(raw))
    warm = _build(surveys, tmp_path / "warm", cache)
    c = _kind(warm, "survey_h5")
    assert (c["corrupt"], c["misses"], c["hits"], c["writes"]) == (1, 1, 0, 1), c


def test_degenerate_salt_writes_fresh_and_never_touches_the_cache(tmp_path, monkeypatch):
    """FAILS IF: an unknown engine commit reads or writes a single MTH5 entry, or the build stops
    producing its MTH5 files (it must write them fresh, gate included)."""
    monkeypatch.setattr(build_portal, "_git_commit_at", lambda cwd: None)
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    monkeypatch.delenv("AUSMT_BUILD_WORKERS", raising=False)
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    out = _build(surveys, tmp_path / "out", cache)
    c = _prov_cache(out)
    assert c["enabled"] is False and c["degenerate"] is True, c
    for k in KINDS:
        assert all(c["kinds"][k][f] == 0 for f in KIND_FIELDS), (k, c["kinds"][k])
    assert not any(p.is_file() for p in cache.rglob("*")), "a degenerate salt created cache files"
    assert len(_served_h5(out)) == N + 1


def test_failed_hardlink_falls_back_to_a_counted_copy(tmp_path, clean_salt, monkeypatch):
    """FAILS IF: a filesystem that refuses hardlinks (a cross-device cache, EXDEV) breaks the build or
    serves nothing, or the fallback copy goes uncounted. The copy is a new inode with the same bytes."""
    import errno
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    cold = _build(surveys, tmp_path / "cold", cache)

    def _no_link(src, dst, *a, **k):
        raise OSError(errno.EXDEV, "Invalid cross-device link")
    monkeypatch.setattr(os, "link", _no_link)
    warm = _build(surveys, tmp_path / "warm", cache)
    c_st, c_sv = _kind(warm, "station_h5"), _kind(warm, "survey_h5")
    assert (c_st["hits"], c_st["link_fallbacks"]) == (N, N), c_st
    assert (c_sv["hits"], c_sv["link_fallbacks"]) == (1, 1), c_sv
    payload_inodes = {p.stat().st_ino for k in ("station_h5", "survey_h5") for p in _payloads(cache, k)}
    for rel, p in _served_h5(warm).items():
        assert p.stat().st_ino not in payload_inodes
        assert p.read_bytes() == (cold / rel).read_bytes(), rel


# ---- the gates, the counters, the log -----------------------------------------------------------

def test_verify_passes_on_the_warm_build(tmp_path, clean_salt):
    """FAILS IF: scripts/verify.py (unmodified, cache-blind) rejects a warm build whose MTH5 files
    came from the cache, with and without the --surveys consistency leg."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    warm = _build(surveys, tmp_path / "warm", cache)
    assert _kind(warm, "station_h5")["hits"] == N
    for extra in ([], ["--surveys", str(surveys)]):
        proc = subprocess.run([sys.executable, str(REPO / "scripts" / "verify.py"), "--data-dir",
                               str(warm), *extra], cwd=str(REPO), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, check=False)
        assert proc.returncode == 0 and "VERIFY: PASS" in proc.stdout, proc.stdout[-3000:]


def test_build_provenance_carries_per_kind_counters_and_the_log_prints_them(tmp_path, clean_salt, capfd):
    """FAILS IF: build_provenance.json's cache block loses a per-kind counter, the corpus-total
    counters stop being the parse+xml tally, or the end-of-build stderr summary omits a kind."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    capfd.readouterr()
    warm = _build(surveys, tmp_path / "warm", cache)
    err = capfd.readouterr().err
    c = _prov_cache(warm)
    assert set(c["kinds"]) == set(KINDS), c.get("kinds")
    for k in KINDS:
        assert set(KIND_FIELDS) <= set(c["kinds"][k]), (k, c["kinds"][k])
    assert c["hits"] == c["kinds"]["parse"]["hits"] + c["kinds"]["xml"]["hits"], c
    assert c["misses"] == c["kinds"]["parse"]["misses"] + c["kinds"]["xml"]["misses"], c
    for k in KINDS:
        line = [ln for ln in err.splitlines() if ln.startswith(f"C18 cache kind {k}:")]
        assert len(line) == 1, f"no end-of-build summary line for {k}:\n{err[-2000:]}"
        for f in KIND_FIELDS:
            assert f" {f}=" in line[0], (f, line[0])


def test_size_cap_eviction_warns_and_is_counted(tmp_path, clean_salt, monkeypatch, capfd):
    """FAILS IF: the size cap evicts entries at the end of a build without a WARN on stderr, or the
    evictions are not in build_provenance.json. A cap that silently colds every build is the
    failure this guards against."""
    surveys = _two_surveys(tmp_path)
    cache = tmp_path / "cache"
    monkeypatch.setenv("AUSMT_CACHE_MAX_MB", "1")
    capfd.readouterr()
    out = _build(surveys, tmp_path / "cold", cache)
    err = capfd.readouterr().err
    c = _prov_cache(out)
    evicted = sum(c["kinds"][k]["evicted"] for k in KINDS)
    assert evicted > 0, c["kinds"]
    assert c["max_mb"] == 1, c
    # A cold build used every entry it holds, so every eviction is of a live entry: the number the
    # operator reads as "the cap is too small" must equal the eviction count.
    assert c["prune"]["pruned_size"] == evicted, c["prune"]
    assert c["prune"]["evicted_live"] == evicted, c["prune"]
    m = re.search(r"C18 cache WARN: .*evicted (\d+) entries, (\d+) of them used by this build", err)
    assert m, err[-2000:]
    assert (int(m.group(1)), int(m.group(2))) == (evicted, evicted), m.group(0)


def test_evictions_of_entries_this_build_did_not_use_are_not_live(tmp_path):
    """FAILS IF: evicted_live counts entries last used BEFORE this build started (it must compare
    against BuildCache.started), so an over-cap cache of stale entries would read as a cap that
    colds every build. Three 600 KB entries dated an hour ago, a 1 MB cap: two go, none live."""
    root = tmp_path / "c"
    seed = _bc(tmp_path, root=root)
    for i in range(3):
        seed.put_bytes(f"{i:064x}", "json", os.urandom(600 * 1024), kind="parse")
    old = seed.started - 3600
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, (old, old))
    later = _bc(tmp_path, root=root, max_mb=1)
    summary = later.prune()
    assert (summary["pruned_size"], summary["evicted_live"]) == (2, 0), summary
    assert later.kinds["parse"]["evicted"] == 2, later.kinds["parse"]


def test_parallel_build_hits_the_same_entries(tmp_path, clean_salt):
    """FAILS IF: the pool path keys, links or populates differently from the serial path: a cold
    --workers 2 build must populate exactly what a serial warm build then hits, and a warm
    --workers 2 build must hit everything with hardlinks."""
    surveys = _two_surveys(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold_par", cache, workers=2)
    ser = _build(surveys, tmp_path / "warm_ser", cache, workers=1)
    par = _build(surveys, tmp_path / "warm_par", cache, workers=2)
    for out in (ser, par):
        assert (_kind(out, "station_h5")["hits"], _kind(out, "station_h5")["misses"]) == (2 * N, 0)
        assert (_kind(out, "survey_h5")["hits"], _kind(out, "survey_h5")["misses"]) == (2, 0)
    payload_inodes = {p.stat().st_ino for k in ("station_h5", "survey_h5") for p in _payloads(cache, k)}
    for rel, p in _served_h5(par).items():
        assert p.stat().st_ino in payload_inodes, rel
    assert (par / "manifest.json").read_bytes() == (ser / "manifest.json").read_bytes()


# ---- key completeness ----------------------------------------------------------------------------

def _bc(tmp_path, **over):
    base = dict(root=tmp_path / "c", engine_commit="commitA", source_digest="sourceA",
                lib_versions={"mt_metadata": "1.0.10", "mth5": "0.6.8"}, contract_digest="contractA",
                mode="rw", checkout_dir=None)
    base.update(over)
    return cache_mod.BuildCache(**base)


SMETA = {"cite": {"ti": "Title"}, "blurb": "b", "doi": "10.1234/x", "org": "Org", "lic": "CC-BY-4.0",
         "pubs": [{"doi": "10.5/y", "t": "Paper", "j": "J", "y": 2020}],
         "creators": [{"name": "Lead", "orcid": "0000-0002-1825-0097"}],
         "funders": [{"name": "Funder", "grant_id": "G1"}]}


def test_station_key_moves_with_every_component(tmp_path):
    """FAILS IF: any input that reaches a station MTH5 can change without moving its key: the
    source bytes, the source filename (it picks the reader), the survey digest, slug, label, final
    station id, declared source provenance, the h5-read SMETA fields, and every salt field."""
    edi = tmp_path / "S1.edi"
    edi.write_text(SAMPLE_EDIS[0].read_text(encoding="latin-1"), encoding="latin-1")
    r = {"id": "S1"}
    bc = _bc(tmp_path)

    def key(bc=bc, p=edi, r=r, slug="s", label="S", smeta=SMETA, dig="d0"):
        build_portal._SHA_CACHE.clear()
        return build_portal._station_h5_key(bc, p, r, slug, label, smeta, dig)
    k0 = key()
    assert k0 == key(), "the key is not stable"
    other = tmp_path / "S1b.edi"
    other.write_text(_one_byte_impedance_edit(edi.read_text(encoding="latin-1")), encoding="latin-1")
    renamed = tmp_path / "S1.xml"
    renamed.write_bytes(edi.read_bytes())
    variants = {
        "bytes": key(p=other), "filename": key(p=renamed), "digest": key(dig="d1"),
        "slug": key(slug="t"), "label": key(label="T"), "id": key(r={"id": "S2"}),
        "provenance": key(r={"id": "S1", "source_provenance": {"original_filename": "x.edi"}}),
        "smeta": key(smeta={**SMETA, "doi": "10.1234/z"}), "no smeta": key(smeta=None),
        "source digest": key(bc=_bc(tmp_path, source_digest="sourceB")),
        "libs": key(bc=_bc(tmp_path, lib_versions={"mt_metadata": "1.0.11", "mth5": "0.6.8"})),
        "contract": key(bc=_bc(tmp_path, contract_digest="contractB")),
    }
    for name, k in variants.items():
        assert k != k0, f"the station key ignores {name}"
    assert len(set(variants.values())) == len(variants), "two different inputs collided"


class _MovedDist:
    """An installed distribution whose version or VCS commit reads differently from the real one."""

    def __init__(self, real, version=None, commit=None):
        self._real, self._version, self._commit = real, version, commit

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def version(self):
        return self._version or self._real.version

    def read_text(self, filename):
        if filename == "direct_url.json" and self._commit:
            return json.dumps({"url": "https://example.invalid/fork.git",
                               "vcs_info": {"vcs": "git", "commit_id": self._commit}})
        return self._real.read_text(filename)


@pytest.mark.parametrize("dist,moved", [("mth5", {"commit": "0" * 40}),
                                        ("mt_metadata", {"commit": "1" * 40}),
                                        ("numpy", {"version": "0.0.0"})])
def test_keys_move_with_the_installed_library_commit_and_dependency_versions(tmp_path, monkeypatch,
                                                                              dist, moved):
    """FAILS IF: an entry written by one installed library stack is reused by another that reports
    the same mt_metadata / mth5 __version__: a fork pin moved to a new git commit, or a bump of a
    library in their dependency closure (numpy here). Both the MTH5 keys and the XML/parse keys
    move, since both products are written by that stack."""
    import importlib.metadata as md  # noqa: PLC0415
    edi = tmp_path / "S1.edi"
    edi.write_text(SAMPLE_EDIS[0].read_text(encoding="latin-1"), encoding="latin-1")

    def keys():
        build_portal._SHA_CACHE.clear()
        bc = _bc(tmp_path)
        return (build_portal._station_h5_key(bc, edi, {"id": "S1"}, "s", "S", SMETA, "d"),
                bc.key(edi_sha="e", survey_digest="d", kind="xml"))
    k0 = keys()
    assert keys() == k0, "the keys are not stable over one installed stack"
    real = md.distribution

    def _dist(name):
        d = real(name)
        return _MovedDist(d, **moved) if re.sub(r"[-_.]+", "-", name).lower() == dist.replace("_", "-") \
            else d
    monkeypatch.setattr(md, "distribution", _dist)
    k1 = keys()
    assert k1[0] != k0[0], f"the station MTH5 key ignores the installed {dist} identity"
    assert k1[1] != k0[1], f"the XML key ignores the installed {dist} identity"


def test_station_key_moves_with_the_hdf5_stack(tmp_path, monkeypatch):
    """FAILS IF: an h5py or HDF5 library upgrade reuses an entry written by the previous stack.
    lib_versions() names mt_metadata and mth5 only, so the h5 keys add the h5py/HDF5 pair."""
    edi = tmp_path / "S1.edi"
    edi.write_text(SAMPLE_EDIS[0].read_text(encoding="latin-1"), encoding="latin-1")
    bc = _bc(tmp_path)
    k0 = build_portal._station_h5_key(bc, edi, {"id": "S1"}, "s", "S", SMETA, "d")
    monkeypatch.setattr(build_portal, "_mth5_lib_fingerprint", lambda: "h5py=0;hdf5=0")
    assert build_portal._station_h5_key(bc, edi, {"id": "S1"}, "s", "S", SMETA, "d") != k0


def test_survey_key_is_the_sorted_member_keys_plus_digest_and_salt(tmp_path):
    """FAILS IF: the survey key depends on member ORDER (it is a set), ignores a member change, a
    member added or removed, the survey digest, or the salt."""
    a, b = tmp_path / "A.edi", tmp_path / "B.edi"
    a.write_text(SAMPLE_EDIS[0].read_text(encoding="latin-1"), encoding="latin-1")
    b.write_text(SAMPLE_EDIS[1].read_text(encoding="latin-1"), encoding="latin-1")
    ra, rb = {"id": "A"}, {"id": "B"}
    bc = _bc(tmp_path)

    def key(st, dig="d0", bc=bc):
        build_portal._SHA_CACHE.clear()
        return build_portal._survey_h5_key(bc, st, "s", "S", SMETA, dig)
    k0 = key([(a, ra), (b, rb)])
    assert key([(b, rb), (a, ra)]) == k0, "member order moved the survey key"
    assert key([(a, ra)]) != k0
    assert key([(a, ra), (b, {"id": "B2"})]) != k0
    assert key([(a, ra), (b, rb)], dig="d1") != k0
    assert key([(a, ra), (b, rb)], bc=_bc(tmp_path, source_digest="sourceB")) != k0
    st_key = build_portal._station_h5_key(bc, a, ra, "s", "S", SMETA, "d0")
    assert st_key != k0 and key([(a, ra)]) != st_key, "tiers share a key namespace"


def test_pid_status_and_unread_smeta_fields_cannot_reach_the_h5(tmp_path):
    """FAILS IF: an SMETA field the MTH5 mapping does not read (the --pid-status resolution facets,
    which come from a file OUTSIDE the survey package, or any other) changes the written file or its
    key, or the projection the key digests misses a field the mapping does read. Both are proven on
    real writes: the full SMETA and its projection alone write semantically identical files."""
    full = json.loads(json.dumps(SMETA))
    build_portal.apply_pid_resolution(full, {"10.1234/x": {"status": "resolved"},
                                             "10.5/y": {"status": "unregistered"}})
    full["slug"] = "s"
    full["access"] = "open"
    assert full.get("doi_resolution") == "ok", "fixture did not exercise the pid facets"
    proj = build_portal._mth5_survey_fields(full)
    assert proj == build_portal._mth5_survey_fields(SMETA), "pid facets entered the projection"
    assert build_portal._mth5_survey_fields(proj) == proj, "the projection is not idempotent"
    edi = SAMPLE_EDIS[0]
    bc = _bc(tmp_path)
    assert build_portal._station_h5_key(bc, edi, {"id": "S1"}, "s", "S", full, "d") == \
        build_portal._station_h5_key(bc, edi, {"id": "S1"}, "s", "S", SMETA, "d")
    h_full, h_proj = tmp_path / "full.h5", tmp_path / "proj.h5"
    assert build_portal._write_tf_mth5([(edi, {"id": "S1"})], "s", "S", h_full, smeta=full)
    assert build_portal._write_tf_mth5([(edi, {"id": "S1"})], "s", "S", h_proj, smeta=proj)
    assert _h5_semantic(h_full) == _h5_semantic(h_proj)
    h_none = tmp_path / "none.h5"
    assert build_portal._write_tf_mth5([(edi, {"id": "S1"})], "s", "S", h_none, smeta=None)
    assert _h5_semantic(h_none) != _h5_semantic(h_full), "the SMETA mapping wrote nothing"


def test_record_fields_outside_the_key_cannot_reach_the_h5(tmp_path):
    """FAILS IF: a station-record field the key does not bind (the coordinate mask, run facts,
    channel masks, anything but id and source_provenance) changes the written file."""
    edi = SAMPLE_EDIS[0]
    lean = {"id": "S1", "source_provenance": {"original_filename": "orig.edi"}}
    fat = {**lean, "lat": None, "lon": None, "elev": None, "variant": "v1", "components": ["Z"],
           "run_facts": {"x": 1}, "tipper_masked": True, "survey": "Other", "ausmt_id": "au.s.S1",
           "_survey": "other"}
    h1, h2 = tmp_path / "lean.h5", tmp_path / "fat.h5"
    assert build_portal._write_tf_mth5([(edi, lean)], "s", "S", h1, smeta=SMETA)
    assert build_portal._write_tf_mth5([(edi, fat)], "s", "S", h2, smeta=SMETA)
    assert _h5_semantic(h1) == _h5_semantic(h2)
    bc = _bc(tmp_path)
    assert build_portal._station_h5_key(bc, edi, lean, "s", "S", SMETA, "d") == \
        build_portal._station_h5_key(bc, edi, fat, "s", "S", SMETA, "d")


# ---- cache.py file entries -----------------------------------------------------------------------

def test_file_entry_roundtrip_and_prune_keeps_foreign_files(tmp_path):
    """FAILS IF: put_file/link_file do not round-trip a payload by hardlink with its meta, or the
    prune touches a file that is not a cache entry. deploy/Makefile keeps pid_status.json in the
    cache root, and an entry-blind prune would age it out or evict it under the size cap."""
    bc = _bc(tmp_path, max_mb=1)
    src = tmp_path / "src.h5"
    src.write_bytes(os.urandom(700 * 1024))
    k1 = bc.key_parts("station_h5", ["one"])
    k2 = bc.key_parts("station_h5", ["two"])
    bc.put_file(k1, "station_h5", src, {"n": 1})
    dest = tmp_path / "out" / "x.h5"
    assert bc.link_file(k1, "station_h5", dest) == {"n": 1}
    assert dest.stat().st_ino == src.stat().st_ino
    foreign = bc.root / "pid_status.json"
    foreign.write_text("{}", encoding="utf-8")
    old = 10 ** 9
    os.utime(foreign, (old, old))
    src2 = tmp_path / "src2.h5"
    src2.write_bytes(os.urandom(700 * 1024))
    bc.put_file(k2, "station_h5", src2, {"n": 1})
    summary = bc.prune()
    assert foreign.exists(), f"the prune deleted a foreign file: {summary}"
    assert summary["pruned_size"] == 1, summary
    remaining = sorted(p.name for p in bc.root.rglob("*") if p.is_file() and p != foreign)
    assert len(remaining) == 2 and all(n.startswith(k2) for n in remaining), \
        f"the size cap split an entry or evicted the newest: {remaining}"


def test_compose_default_cap_matches_the_engine_default():
    """FAILS IF: deploy/compose.yaml forwards a different default cap than cache.py declares. The
    compose default is what production runs under, so a raised engine default alone changes nothing
    on the box."""
    compose = REPO.parent / "deploy" / "compose.yaml"
    if not compose.is_file():
        pytest.skip("deploy/ is not shipped in this tree")
    m = re.search(r"AUSMT_CACHE_MAX_MB:\s*\$\{AUSMT_CACHE_MAX_MB:-(\d+)\}", compose.read_text(encoding="utf-8"))
    assert m, "compose.yaml no longer forwards AUSMT_CACHE_MAX_MB"
    assert int(m.group(1)) == cache_mod.CACHE_MAX_MB_DEFAULT


CAP_COPIES = (
    ("deploy/compose.yaml", r"CACHE_MAX_MB_DEFAULT=(\d+)"),
    ("deploy/.env.example", r"Default (\d+): the cache holds"),
    ("deploy/.env.example", r"# AUSMT_CACHE_MAX_MB=(\d+)"),
    ("deploy/README.md", r"`AUSMT_CACHE_MAX_MB` \(default (\d+)\)"),
    ("docs/docs/developer/build-lifecycle.md", r"`AUSMT_CACHE_MAX_MB` \(default (\d+)\)"),
    ("maintainer/C33-OperatorDocsDesign.md", r"`AUSMT_CACHE_MAX_MB`: C18 build-cache cap \(default (\d+)"),
    ("maintainer/C18-BuildCacheDesign.md", r"`CACHE_MAX_MB_DEFAULT = (\d+)`"),
)


@pytest.mark.parametrize("rel,pattern", CAP_COPIES)
def test_every_written_copy_of_the_default_cap_matches_the_engine_default(rel, pattern):
    """FAILS IF: an operator page, the env template or the design states a default cap other than
    cache.py's. The operator sizes the data volume from these pages, so a stale copy understates
    what the cache may hold on disk."""
    path = REPO.parent / rel
    if not (REPO.parent / "deploy").is_dir():
        pytest.skip("deploy/ is not shipped in this tree")
    assert path.is_file(), f"{rel} is gone; update CAP_COPIES"
    found = [int(v) for v in re.findall(pattern, path.read_text(encoding="utf-8"))]
    assert found, f"{rel} no longer states the default cap as /{pattern}/"
    assert set(found) == {cache_mod.CACHE_MAX_MB_DEFAULT}, (rel, found)


# ---- hardlink discipline, replayed diagnostics, inputs that are deliberately not key parts --------

FILE_KINDS = ("station_h5", "survey_h5")


def _payload_bytes(cache: Path) -> dict:
    return {p: p.read_bytes() for k in FILE_KINDS for p in _payloads(cache, k)}


def test_rewriting_a_served_tree_never_writes_through_to_the_cache(tmp_path, clean_salt):
    """FAILS IF: an MTH5 write into a build tree whose files are hardlinks to cache payloads writes
    INTO the shared inode (an in-place truncate) instead of replacing the name. The payload would
    then change under its sidecar and under every other tree that links it; the next build would
    find it corrupt at best."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    warm = _build(surveys, tmp_path / "warm", cache)
    before = _payload_bytes(cache)
    assert len(before) == N + 1
    inodes = {p.stat().st_ino for p in before}
    assert all(p.stat().st_ino in inodes for p in _served_h5(warm).values())
    _build(surveys, warm, None)   # no cache: every MTH5 is written fresh at the SAME paths
    assert _payload_bytes(cache) == before, "a write into a served tree changed a cache payload"
    for rel, p in _served_h5(warm).items():
        assert p.stat().st_ino not in inodes, f"{rel} was rewritten in place, not replaced"
    again = _build(surveys, tmp_path / "again", cache)
    for k, n in (("station_h5", N), ("survey_h5", 1)):
        c = _kind(again, k)
        assert (c["hits"], c["corrupt"]) == (n, 0), (k, c)


def test_evicting_every_entry_leaves_the_served_tree_intact(tmp_path, clean_salt):
    """FAILS IF: pruning a cache entry changes a build tree that links its payload. The prune only
    ever unlinks names, so a served file keeps its inode and bytes and the build still verifies."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    warm = _build(surveys, tmp_path / "warm", cache)
    served = {rel: (p.stat().st_ino, p.read_bytes()) for rel, p in _served_h5(warm).items()}
    summary = _bc(tmp_path, root=cache, max_mb=0).prune()
    assert summary["pruned_size"] > 0 and not _payload_bytes(cache), summary
    after = {rel: (p.stat().st_ino, p.read_bytes()) for rel, p in _served_h5(warm).items()}
    assert after == served, "evicting cache entries changed the served tree"
    proc = subprocess.run([sys.executable, str(REPO / "scripts" / "verify.py"), "--data-dir", str(warm)],
                          cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          check=False)
    assert proc.returncode == 0 and "VERIFY: PASS" in proc.stdout, proc.stdout[-3000:]


def test_a_hit_replays_the_populating_writes_diagnostics(tmp_path, monkeypatch, capfd):
    """FAILS IF: a cache hit loses what the populating write reported: its per-station failure rows
    (they fold into build_report.json) and its captured file-level stderr, or prints the rows as
    WARN lines when the caller keeps no ledger. failure_rows is an OUTPUT of the writer, never an
    input, so it is replayed from the entry's meta rather than keyed. Also fails if a withheld
    write (n == 0) is stored: the next build must write it again."""
    bc = _bc(tmp_path)
    rows = [{"producer": "h5", "file": "X.edi", "error": "ValueError", "message": "bad",
             "context": "survey bundle"}]
    calls = []

    def _task(stations, slug, label, hpath, smeta, context="station product"):
        calls.append(context)
        Path(hpath).parent.mkdir(parents=True, exist_ok=True)
        Path(hpath).write_bytes(b"payload")
        return 1, "  [h5] note file-level line\n", [dict(r) for r in rows]
    monkeypatch.setattr(build_portal, "_mth5_write_task", _task)
    key = bc.key_parts("survey_h5", ["replay"])
    st = [(SAMPLE_EDIS[0], {"id": "S1"})]
    # A real key derivation memoises each source's digest; the store checks the source against it.
    build_portal._SHA_CACHE.clear()
    build_portal.sha256(SAMPLE_EDIS[0])

    def run(dest, ledger):
        n = build_portal._write_tf_mth5_cached(st, "s", "S", tmp_path / dest / "s-tf.h5", None, ledger,
                                               "survey bundle", bc, key, "survey_h5")
        return n, capfd.readouterr().err
    capfd.readouterr()
    miss_rows, hit_rows = [], []
    n1, err1 = run("a", miss_rows)
    n2, err2 = run("b", hit_rows)
    assert len(calls) == 1, f"the second call wrote instead of hitting: {calls}"
    assert (n1, n2) == (1, 1) and miss_rows == hit_rows == rows, (miss_rows, hit_rows)
    assert err1 == err2 == "  [h5] note file-level line\n", (err1, err2)
    n3, err3 = run("c", None)
    assert n3 == 1 and "  [h5] WARN X.edi: ValueError: bad" in err3, err3

    def _withheld(stations, slug, label, hpath, smeta, context="station product"):
        calls.append("withheld")
        return 0, "  [h5] WITHHOLD s-tf.h5\n", []
    monkeypatch.setattr(build_portal, "_mth5_write_task", _withheld)
    key = bc.key_parts("survey_h5", ["withheld"])
    run("d", [])
    run("e", [])
    assert calls.count("withheld") == 2, "a withheld write was stored and replayed"


def test_source_directory_is_not_a_key_part_because_it_never_reaches_the_h5(tmp_path):
    """FAILS IF: the directory a source file is read from reaches the written file (the key binds
    the bytes and the file NAME only, so a surveys checkout moved to another path must not serve an
    entry naming the old one)."""
    src = SAMPLE_EDIS[0]
    a, b = tmp_path / "one" / "deep", tmp_path / "two"
    for d in (a, b):
        d.mkdir(parents=True)
        (d / src.name).write_bytes(src.read_bytes())
    ha, hb = tmp_path / "a.h5", tmp_path / "b.h5"
    assert build_portal._write_tf_mth5([(a / src.name, {"id": "S1"})], "s", "S", ha, smeta=SMETA)
    assert build_portal._write_tf_mth5([(b / src.name, {"id": "S1"})], "s", "S", hb, smeta=SMETA)
    assert _h5_semantic(ha) == _h5_semantic(hb)
    assert str(a).encode("utf-8") not in ha.read_bytes()
    bc = _bc(tmp_path)
    build_portal._SHA_CACHE.clear()
    assert build_portal._station_h5_key(bc, a / src.name, {"id": "S1"}, "s", "S", SMETA, "d") == \
        build_portal._station_h5_key(bc, b / src.name, {"id": "S1"}, "s", "S", SMETA, "d")


def test_raw_seed_meta_build_never_caches_an_mth5(tmp_path, clean_salt):
    """FAILS IF: a --raw build, whose survey metadata comes from --seed-meta (a file no key part
    digests), stores or reads an MTH5 entry, or a rebuild after a seed edit serves the OLD seed's
    organisation inside the survey MTH5."""
    raw_root = tmp_path / "raw"
    edir = raw_root / "survey1"
    edir.mkdir(parents=True)
    for src in SAMPLE_EDIS:
        (edir / src.name).write_bytes(src.read_bytes())
    coll = tmp_path / "collections.json"
    coll.write_text(json.dumps({"survey1": ["Raw Survey", "Org One"]}), encoding="utf-8")
    seed = tmp_path / "seed.json"
    cache = tmp_path / "cache"

    def raw_build(out, org):
        seed.write_text(json.dumps({"Raw Survey": {"org": org, "lic": "CC-BY-4.0", "edi": "ok"}}),
                        encoding="utf-8")
        assert build_portal.main([
            "--raw", str(raw_root), "--collections", str(coll), "--seed-meta", str(seed),
            "--out", str(out), "--bundle-edi", "--no-validate", "--survey-h5", "--station-h5",
            "--incremental", "--cache-dir", str(cache), "--cache-mode", "rw"]) == 0
        return out
    raw_build(tmp_path / "o1", "Org One")
    out2 = raw_build(tmp_path / "o2", "Org Two")
    assert not any(p.is_file() for p in cache.rglob("*")), "a --raw build persisted cache entries"
    for k in FILE_KINDS:
        assert all(v == 0 for v in _kind(out2, k).values()), (k, _kind(out2, k))
    bundles = sorted((out2 / "bundles").glob("*-tf.h5"))
    assert bundles, "the raw build wrote no survey MTH5 (test set-up wrong)"
    with h5py.File(bundles[0], "r") as f:
        orgs = [str(v) for name, grp in f["Experiment/Surveys"].items()
                for k, v in grp.attrs.items() if k == "acquired_by.organization"]
    assert orgs and all("Org Two" in o for o in orgs), orgs


# ---- temporaries, rejected metas, sources that move during a build -------------------------------

def test_relinking_a_dest_that_already_is_the_payload_leaves_no_temporary(tmp_path):
    """FAILS IF: placing an entry at a dest that already links the same payload (a second build into
    the same --out) leaves the temporary name behind. rename(2) between two names of one inode
    succeeds and does nothing, so the temporary must be removed explicitly."""
    bc = _bc(tmp_path)
    src = tmp_path / "src.h5"
    src.write_bytes(os.urandom(4096))
    key = "ab" * 32
    bc.put_file(key, "station_h5", src, {"n": 1})
    out = tmp_path / "out"
    out.mkdir()
    dest = out / "S1.h5"
    assert bc.link_file(key, "station_h5", dest) == {"n": 1}
    assert bc.link_file(key, "station_h5", dest) == {"n": 1}
    assert sorted(p.name for p in out.iterdir()) == ["S1.h5"]


def test_prune_removes_stale_put_temporaries_and_nothing_else(tmp_path):
    """FAILS IF: a temporary stranded by a put that was killed mid-write (an MTH5-sized hardlink or
    copy) is never removed, or the prune removes a temporary young enough to belong to a put that
    is still running, or any file that is not a cache temporary."""
    import time
    bc = _bc(tmp_path)
    key = "ab" * 32
    shard = bc.root / key[:2]
    shard.mkdir(parents=True, exist_ok=True)
    old = time.time() - 2 * 86400
    stale = shard / f".{key}.survey_h5.4242.1.tmp"
    live = shard / f".{key}.station_h5.4243.2.tmp"
    keep = shard / ".keep"
    foreign = bc.root / "pid_status.json"
    for p in (stale, live, keep, foreign):
        p.write_bytes(b"x" * 1024)
    for p in (stale, keep, foreign):
        os.utime(p, (old, old))
    bc.prune()
    assert not stale.exists(), "a stale put temporary survived the prune"
    assert live.exists() and keep.exists() and foreign.exists()


def test_a_hit_keeps_a_file_entry_whose_payload_is_older_than_the_age_window(tmp_path):
    """FAILS IF: the age rule reads a file entry's PAYLOAD mtime. A hit touches only the sidecar
    (the payload is also a served file whose mtime must not move), so a payload written 91 days ago
    and hit today belongs to a live entry; an age test on the payload would drop it and turn every
    long-lived hot MTH5 into a miss. The unhit twin pins that the window still ages entries out."""
    import time
    bc = _bc(tmp_path)
    old = time.time() - (cache_mod.PRUNE_MAX_AGE_DAYS + 1) * 86400
    keys = {}
    for name in ("hot", "cold"):
        src = tmp_path / f"{name}.h5"
        src.write_bytes(os.urandom(4096))
        keys[name] = bc.key_parts("station_h5", [name])
        bc.put_file(keys[name], "station_h5", src, {"n": 1})
        for p in (bc.root / keys[name][:2]).glob(f"{keys[name]}.*"):
            os.utime(p, (old, old))
    assert bc.link_file(keys["hot"], "station_h5", tmp_path / "out" / "hot.h5") == {"n": 1}
    hot = bc.root / keys["hot"][:2] / f"{keys['hot']}.station_h5"
    assert hot.stat().st_mtime == pytest.approx(old), "a hit moved the payload's mtime"
    summary = bc.prune()
    assert hot.exists() and hot.with_name(hot.name + ".ref").exists(), \
        f"the age rule dropped a file entry hit by this build: {summary}"
    assert not list((bc.root / keys["cold"][:2]).glob(f"{keys['cold']}.*")), \
        f"an unhit entry past the age window survived: {summary}"
    assert summary["pruned_age"] == 1, summary


def _rewrite_sidecar_meta(ref: Path, meta) -> None:
    """Replace a file entry's stored meta while keeping the sidecar self-verifying."""
    raw = ref.read_bytes()
    side = json.loads(raw.partition(b"\n")[2].decode("utf-8"))
    side["meta"] = meta
    body = json.dumps(side, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib  # noqa: PLC0415
    ref.write_bytes(hashlib.sha256(body).hexdigest().encode("ascii") + b"\n" + body)


@pytest.mark.parametrize("meta", [{"n": 0, "err": "", "rows": []}, {"err": "", "rows": []}])
def test_a_verified_entry_whose_meta_is_unusable_is_rejected_and_rewritten(tmp_path, clean_salt,
                                                                           meta):
    """FAILS IF: an entry whose checksums verify but whose stored meta cannot describe a written
    file (no station count, or a count below one) is served with an invented count, instead of
    being dropped, counted corrupt and a miss, and written fresh."""
    surveys = _one_survey(tmp_path)
    cache = tmp_path / "cache"
    _build(surveys, tmp_path / "cold", cache)
    ref = sorted(cache.rglob("*.survey_h5.ref"))
    assert len(ref) == 1, ref
    payload = ref[0].with_name(ref[0].name[:-len(".ref")])
    old_ino = payload.stat().st_ino
    _rewrite_sidecar_meta(ref[0], meta)
    warm = _build(surveys, tmp_path / "warm", cache)
    c = _kind(warm, "survey_h5")
    assert (c["corrupt"], c["misses"], c["hits"], c["writes"]) == (1, 1, 0, 1), c
    served = warm / "bundles" / "mc-a-tf.h5"
    assert served.stat().st_ino != old_ino, "the rejected payload was served"
    assert payload.stat().st_ino == served.stat().st_ino, "the fresh write was not stored"
    assert json.loads(ref[0].read_bytes().partition(b"\n")[2])["meta"]["n"] == N


def test_a_source_edited_after_its_key_was_derived_is_not_stored(tmp_path):
    """FAILS IF: an EDI edited between key derivation and the MTH5 write (a surveys checkout
    fast-forwarded mid-build) is stored under the key of its PRE-edit bytes. A later build over the
    pre-edit bytes would then hit and serve the post-edit impedances, with the gate skipped."""
    edi = tmp_path / "S1.edi"
    edi.write_text(SAMPLE_EDIS[0].read_text(encoding="latin-1"), encoding="latin-1")
    r = {"id": "S1"}
    bc = _bc(tmp_path)
    build_portal._SHA_CACHE.clear()
    key = build_portal._station_h5_key(bc, edi, r, "s", "S", SMETA, "d")
    edi.write_text(_one_byte_impedance_edit(edi.read_text(encoding="latin-1")), encoding="latin-1")
    n = build_portal._write_tf_mth5_cached([(edi, r)], "s", "S", tmp_path / "S1.h5", SMETA, None,
                                          "station product", bc, key, "station_h5")
    build_portal._SHA_CACHE.clear()
    assert n == 1, "the build must still serve the file it wrote and gated"
    assert bc.kinds["station_h5"]["writes"] == 0, bc.kinds["station_h5"]
    assert not _payloads(bc.root, "station_h5"), "a moved source was stored under its old key"
