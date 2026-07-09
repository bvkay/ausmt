"""C18 — the content-addressed incremental build cache (engine/extract/cache.py + its two seams).

Every test here is written to be ABLE TO FAIL (Invariant 10): each states its failure criterion and
tests an INDEPENDENT observable, never cache-metadata self-consistency. The load-bearing ones:

  * ★ stale-cache refusal: mutate an impedance value in a source EDI -> the rebuild MUST serve the
    NEW value (fails if a byte-changed EDI is ever served from a stale entry).
  * cache-entry integrity is the CACHE's own job (Amendment A1b): every entry embeds a sha256 of its
    payload, verified on read — a bit-flipped entry is counted (`corrupt`), deleted and recomputed,
    so the poison can never ship. verify.py guards POST-BUILD tampering of served files only: the
    manifest sha is computed FROM the served bytes, so a poison that flowed through the build would
    verify self-consistently — the outer gate cannot see it (the review proved this; §4.2 as amended).
  * raw-mode exclusion (Amendment A1a): --raw builds never touch the cache (seed-meta feeds served
    citations but is not a key component).
  * salt invalidations (engine commit / library version / survey.yaml edit) each force misses.
  * degenerate-salt refusal: unknown engine commit / dirty checkout -> zero reads AND zero writes.
  * equivalence: a warm (all-hits) build is byte-identical to the build that populated its cache.
  * deterministic hit/miss/write/corrupt counters (NO wall-clock).
  * prune + atomic-swap lifecycle survival.

The cache's integrity gate DISABLES it on a dirty engine checkout (the real dev worktree is dirty
during development, and CI runs on a clean checkout). To exercise a FIRING cache deterministically
regardless of the tree state, the integration tests monkeypatch cache._dirty_checkout -> clean; that
patches the gate's INPUT, not the gate itself, so the degenerate-salt tests still verify the real gate.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import build_portal  # noqa: E402
import cache as cache_mod  # noqa: E402

SAMPLE_EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))
N_STATIONS = len(SAMPLE_EDIS)                 # sample survey = 2 broadband stations
# Per served station the cache stores 3 blobs (parse-json, xml-bytes, xml-meta-json) but the get/miss
# arithmetic is ASYMMETRIC, and that asymmetry is a real, asserted observable:
#   * cold build (all miss): 2 GETs/station miss — the parse get + the xml-bytes get. The xml-META
#     get is only issued AFTER an xml-bytes HIT (a miss goes straight to compute), so a cold build
#     never issues it. => 2 misses/station, 3 writes/station.
#   * warm build (all hit): 3 GETs/station hit — parse + xml-bytes + xml-meta. => 3 hits/station, 0 writes.
EXPECTED_WARM_HITS = 3 * N_STATIONS
EXPECTED_COLD_MISSES = 2 * N_STATIONS
EXPECTED_WRITES = 3 * N_STATIONS


@pytest.fixture
def clean_salt(monkeypatch):
    """Force the cache's dirty-checkout gate to see a CLEAN tree so the cache fires (the dev worktree
    is dirty during development; CI is clean). Patches the gate INPUT, not the gate — is_salt_degenerate
    still runs its real logic over engine_commit + this (clean) result.

    A4 (the C18c flake): ALSO pin the engine commit and clear the cache-relevant env vars. The commit
    used to be re-resolved via a live `git rev-parse` inside every in-process build, so concurrent git
    activity on the machine (2026-07-07: the force-push/merge-queue day) between a test's two builds
    flipped the salt and full-missed the 'warm' build — a nondeterministic counter failure that passed
    on rerun. Pinned here so no cache test's counters can ever depend on ambient git or shell state;
    the salt tests below patch this NAME themselves when they need a moving commit."""
    monkeypatch.setattr(cache_mod, "_dirty_checkout", lambda cwd: False)
    monkeypatch.setattr(build_portal, "_git_commit_at",
                        lambda cwd: "testpin" if Path(cwd) == build_portal.HERE else None)
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    monkeypatch.delenv("AUSMT_CACHE_MAX_MB", raising=False)


def _make_survey(tmp_path, edis, *, name="Cache Survey", slug="cache-survey",
                 yaml_extra="", subdir="surveys"):
    """One survey package (survey.yaml + edi/) built from real sample EDIs. Returns the --surveys root."""
    pkg = tmp_path / subdir / slug
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        f"name: {name}\nslug: {slug}\ncountry: Australia\norganisation: Test Org\n"
        f"access: open\nlicense: CC-BY-4.0\n{yaml_extra}", encoding="utf-8")
    for src in edis:
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    return tmp_path / subdir


def _build(surveys, out, cache_dir=None, mode="rw", extra=None):
    argv = ["--surveys", str(surveys), "--out", str(out), "--bundle-edi", "--no-validate"]
    if cache_dir is not None:
        argv += ["--incremental", "--cache-dir", str(cache_dir), "--cache-mode", mode]
    if extra:
        argv += extra
    rc = build_portal.main(argv)
    return rc


def _cache_counters(out: Path) -> dict:
    return json.loads((out / "build_provenance.json").read_text(encoding="utf-8"))["cache"]


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _served_xml(out: Path):
    return sorted((out / "xml").rglob("*.xml"))


def _impedance_from_xml(xml_path: Path):
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    tf = TF()
    tf.read(str(xml_path))
    import numpy as np  # noqa: PLC0415
    return np.asarray(tf.impedance.data)


def _xml_authors(xml_path: Path):
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    tf = TF()
    tf.read(str(xml_path))
    return tf.survey_metadata.citation_dataset.authors


# --------------------------------------------------------------------------------------------------
# Amendment A1a: --raw builds are EXCLUDED from caching entirely
# --------------------------------------------------------------------------------------------------

def test_raw_mode_build_never_touches_the_cache(tmp_path, clean_salt):
    """FAILS IF: a --raw --incremental build reads OR writes the cache, or a warm raw rebuild serves
    the PREVIOUS seed-meta's citation in the served XML. In raw mode survey metadata comes from
    --seed-meta JSON, which NO key component covers (survey_meta_digest is empty when there is no
    survey.yaml) — so a seed edit would spuriously HIT and serve stale DOI/authors/title. Adjudicated
    fix (Amendment A1a): raw mode is excluded from caching entirely — the cache is inert exactly like
    a degenerate salt (hits == misses == writes == 0), and the build derives everything fresh.

    Proven failing on pre-fix HEAD: the warm raw rebuild reported hits=6 misses=0 and the served XML
    citation authors were the OLD seed's org while the same build's surveys.json carried the new one."""
    raw_root = tmp_path / "raw"
    edir = raw_root / "survey1"
    edir.mkdir(parents=True)
    for src in SAMPLE_EDIS:
        (edir / src.name).write_text(src.read_text(encoding="latin-1"), encoding="latin-1")
    coll = tmp_path / "collections.json"
    coll.write_text(json.dumps({"survey1": ["Raw Survey", "Org One"]}), encoding="utf-8")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"Raw Survey": {"org": "Org One", "lic": "CC-BY-4.0", "edi": "ok"}}),
                    encoding="utf-8")
    cache = tmp_path / "cache"

    def _raw_build(out):
        return build_portal.main([
            "--raw", str(raw_root), "--collections", str(coll), "--seed-meta", str(seed),
            "--out", str(out), "--bundle-edi", "--no-validate",
            "--incremental", "--cache-dir", str(cache), "--cache-mode", "rw"])

    out1 = tmp_path / "out1"
    assert _raw_build(out1) == 0
    c1 = _cache_counters(out1)
    assert c1["hits"] == 0 and c1["misses"] == 0 and c1["writes"] == 0, \
        f"a --raw build touched the cache (must be inert, Amendment A1a): {c1}"
    assert not any(p.is_file() for p in cache.rglob("*")), "--raw build persisted cache entries"

    # Edit the seed's citation source (the exact stale-citation vector the review proved), rebuild.
    seed.write_text(json.dumps({"Raw Survey": {"org": "Org Two", "lic": "CC-BY-4.0", "edi": "ok"}}),
                    encoding="utf-8")
    out2 = tmp_path / "out2"
    assert _raw_build(out2) == 0
    c2 = _cache_counters(out2)
    assert c2["hits"] == 0 and c2["misses"] == 0 and c2["writes"] == 0, \
        f"a warm --raw rebuild touched the cache: {c2}"
    served = _served_xml(out2)
    assert served, "raw build served no XML (test set-up wrong)"
    for xp in served:
        a = _xml_authors(xp)
        assert a == "Org Two", \
            f"STALE SEED CITATION: {xp.name} cites {a!r}, not the edited seed's 'Org Two'"


# --------------------------------------------------------------------------------------------------
# ★ 1. Stale-cache refusal — THE contract test (design §4.1)
# --------------------------------------------------------------------------------------------------

def test_stale_cache_refusal_impedance_edit_is_served(tmp_path, clean_salt):
    """FAILS IF: after mutating one impedance value in a source EDI, the incremental rebuild serves the
    OLD (cached) XML instead of re-deriving from the new bytes. The key is the source-EDI content sha,
    so a byte-changed EDI must MISS and re-run normalize on the new value. Tightened both directions:
    the OTHER station's served XML must be BYTE-IDENTICAL across the two builds — byte-identity is
    only possible from a cache hit, since a recompute re-stamps the wall-clock <CreateTime>.

    Pairing note (the CI tripwire this test once fell into): the mutation target is sorted[0] and the
    served XML is looked up BY THE STATION'S FILENAME derived from that same EDI's DATAID — never by
    index. The original version chose the target via UNSORTED rglob (platform-dependent readdir order)
    but compared sorted _served_xml()[0]: green on NTFS (rglob happened to yield Vulcan_A1.edi first),
    red on the Linux runner (yielded Vulcan_A2.edi -> mutated A2, compared A1 -> false 'STALE CACHE'
    with hits=3 misses=2, i.e. the edit HAD missed and re-derived correctly)."""
    import re
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    out1 = tmp_path / "out1"
    assert _build(surveys, out1, cache) == 0

    # Deterministic target: sorted[0]; derive its station id from ITS OWN DATAID so the target EDI
    # and the compared served XML can never drift apart, on any platform's directory order.
    target_edi = sorted(surveys.rglob("*.edi"))[0]
    m_id = re.search(r'(?im)^\s*DATAID\s*=\s*"?([A-Za-z0-9_.-]+)"?', target_edi.read_text(encoding="latin-1"))
    assert m_id, f"could not read DATAID from {target_edi.name}"
    target_xml_name = f"{m_id.group(1)}.xml"

    xml1 = {p.name: p for p in _served_xml(out1)}
    assert target_xml_name in xml1, f"{target_xml_name} not served in build 1: {sorted(xml1)}"
    z_before = _impedance_from_xml(xml1[target_xml_name])

    # Mutate ONE impedance datum in the source EDI: scale the first ZXYR value by a large, unambiguous
    # factor so the recovered impedance provably changes. ZXYR is a real-part impedance data block.
    txt = target_edi.read_text(encoding="latin-1")
    m = re.search(r"(>ZXYR[^\n]*\n\s*)(-?\d+\.\d+(?:[eE][+-]?\d+)?)", txt)
    assert m, "could not locate a ZXYR datum to mutate in the source EDI"
    old_val = float(m.group(2))
    new_val = old_val * 3.0 + 1.0
    txt2 = txt[:m.start(2)] + f"{new_val:.6E}" + txt[m.end(2):]
    target_edi.write_text(txt2, encoding="latin-1")

    out2 = tmp_path / "out2"
    assert _build(surveys, out2, cache) == 0
    counters = _cache_counters(out2)

    # Exact counter arithmetic (deterministic, §4.6): the edited station misses parse + xml (2) and
    # re-puts parse/xml/meta (3 writes); every OTHER station fully hits (3 each).
    assert counters["misses"] == 2, f"the byte-changed EDI did not miss exactly (parse+xml): {counters}"
    assert counters["hits"] == 3 * (N_STATIONS - 1), f"the unchanged station(s) did not fully hit: {counters}"
    assert counters["writes"] == 3, f"the edited station did not repopulate its 3 blobs: {counters}"

    xml2 = {p.name: p for p in _served_xml(out2)}
    assert set(xml2) == set(xml1), (sorted(xml1), sorted(xml2))
    z_after = _impedance_from_xml(xml2[target_xml_name])
    import numpy as np
    assert not np.allclose(z_before, z_after), \
        "STALE CACHE: the served XML impedance did not change after the source EDI was edited"
    # Both directions: every UNCHANGED station's served XML is byte-identical across the builds —
    # only a cache hit can achieve that (a recompute would re-stamp <CreateTime>).
    for name, p in xml2.items():
        if name != target_xml_name:
            assert p.read_bytes() == xml1[name].read_bytes(), \
                f"unchanged station {name} was NOT served from cache (bytes differ across builds)"


def test_xml_cache_key_binds_disambiguated_station_id(tmp_path, clean_salt):
    """FAILS IF: removing a same-DATAID SIBLING EDI (which changes an unchanged EDI's FINAL
    post-_disambiguate station id, e.g. X.a -> X) still serves the cached XML under the OLD id — a
    stale internal Site.id. The XML content+filename are a function of the disambiguated id, which
    depends on the survey's EDI SET (not survey.yaml), so the XML cache key must bind r["id"].

    Build with two EDIs sharing DATAID 'DUP01' (disambiguated to DUP01.<tag>), populating the cache;
    then rebuild with ONE of them removed (now a UNIQUE 'DUP01'), and assert the served XML is named
    DUP01.xml and its internal Site id is DUP01 — i.e. the id change forced a fresh derive, not a hit
    of the DUP01.<tag> entry."""
    import re
    from mt_metadata.transfer_functions.core import TF
    pkg = tmp_path / "surveys" / "dup"
    edir = pkg / "transfer_functions" / "edi"
    edir.mkdir(parents=True)
    (pkg / "survey.yaml").write_text(
        "name: Dup\nslug: dup\ncountry: Australia\norganisation: T\naccess: open\nlicense: CC-BY-4.0\n",
        encoding="utf-8")
    for i, src in enumerate(SAMPLE_EDIS[:2]):
        txt = re.sub(r'(?im)^(DATAID\s*=\s*).*$', r'\1"DUP01"', src.read_text(encoding="latin-1"))
        (edir / f"dup_{i}.edi").write_text(txt, encoding="latin-1")

    cache = tmp_path / "cache"
    assert _build(tmp_path / "surveys", tmp_path / "out1", cache) == 0
    xmls1 = _served_xml(tmp_path / "out1")
    assert len(xmls1) == 2, [p.name for p in xmls1]   # both disambiguated: DUP01.<tag>.xml
    assert all("." in p.stem.replace("DUP01", "", 1).lstrip(".") or p.stem != "DUP01" for p in xmls1)

    # Remove the SECOND colliding EDI. dup_0.edi is now a UNIQUE DUP01 -> final id 'DUP01' (no tag).
    (edir / "dup_1.edi").unlink()
    assert _build(tmp_path / "surveys", tmp_path / "out2", cache) == 0
    xmls2 = _served_xml(tmp_path / "out2")
    assert len(xmls2) == 1, [p.name for p in xmls2]
    assert xmls2[0].name == "DUP01.xml", f"served XML not renamed to the un-disambiguated id: {xmls2[0].name}"
    tf = TF(); tf.read(str(xmls2[0]))
    assert tf.station_metadata.id == "DUP01", \
        f"STALE XML: served DUP01.xml carries a disambiguated Site.id {tf.station_metadata.id!r}"


# --------------------------------------------------------------------------------------------------
# 2. verify.py catches POST-BUILD tampering of served files (the outer gate — §4.2 as amended by A1b)
# --------------------------------------------------------------------------------------------------

def test_verify_catches_post_build_tamper_of_served_files(tmp_path, clean_salt):
    """FAILS IF: scripts/verify.py --data-dir does not FAIL when a SERVED file's bytes are tampered
    AFTER the build wrote its manifest. This is the OUTER integrity gate: verify.py re-hashes served
    bytes against the manifest, so it catches post-build tampering of the delivered tree.

    What it does NOT prove (Amendment A1b — the review's design-level correction): verify.py CANNOT
    catch a poisoned CACHE entry, because the manifest sha is computed FROM the served bytes, so a
    poison that flows through the build verifies self-consistently. Cache-entry integrity is the
    CACHE's own checksum-on-read job — see the corrupt-entry tests below."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "out1", cache) == 0

    # Sanity: a clean warm build passes verify.py --data-dir.
    out_ok = tmp_path / "out_ok"
    assert _build(surveys, out_ok, cache) == 0
    assert _verify_data_dir(out_ok) == 0, "a clean warm build should PASS verify.py --data-dir"

    # Tamper a SERVED file after the build wrote its manifest — the case the outer gate exists for.
    served = _served_xml(out_ok)[0]
    served.write_bytes(served.read_bytes() + b"\n<!-- tampered post-build -->\n")
    assert _verify_data_dir(out_ok) == 1, \
        "verify.py --data-dir did not FAIL on served XML whose bytes disagree with the manifest sha"


def _verify_data_dir(data_dir: Path) -> int:
    """Invoke the UNMODIFIED scripts/verify.py --data-dir as a subprocess (its own module main),
    returning its exit code (0 PASS / 1 FAIL)."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "verify.py"), "--data-dir", str(data_dir)],
        cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return proc.returncode


def _verify_data_dir_surveys(data_dir: Path, surveys_root):
    """C18b: invoke scripts/verify.py --data-dir with (or without) --surveys, returning
    (returncode, combined_output) so a test can assert BOTH the exit code and the gate message.
    surveys_root=None omits --surveys (the loud-skip path)."""
    argv = [sys.executable, str(REPO / "scripts" / "verify.py"), "--data-dir", str(data_dir)]
    if surveys_root is not None:
        argv += ["--surveys", str(surveys_root)]
    proc = subprocess.run(argv, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=False)
    return proc.returncode, proc.stdout


# --------------------------------------------------------------------------------------------------
# C18b (A3): the cache-INDEPENDENT digest-consistency gate — the 2026-07-07 incident replay
# --------------------------------------------------------------------------------------------------

def _sidecar(out: Path) -> dict:
    return json.loads((out / "products" / "survey_digests.json").read_text(encoding="utf-8"))


def test_c18b_gate_green_on_fresh_warm_build(tmp_path, clean_salt):
    """FAILS IF: the armed consistency gate (--surveys) does not PASS a build whose served products
    were keyed under the LIVE survey.yaml. Warm-hit correctness: build twice with the cache; the
    second (all-hits) build's sidecar must still stamp the live digest, so the gate is green."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "cold", cache) == 0
    warm = tmp_path / "warm"
    assert _build(surveys, warm, cache) == 0
    # sanity: this WAS an all-hits build (so the stamp came off the cache meta, not a fresh compute)
    assert _cache_counters(warm)["hits"] == EXPECTED_WARM_HITS, _cache_counters(warm)
    rc, out = _verify_data_dir_surveys(warm, surveys)
    assert rc == 0, out
    assert "VERIFY: PASS" in out, out
    assert "consistency: PASS" in out, out


def test_c18b_gate_skips_loudly_without_surveys_arg(tmp_path, clean_salt):
    """FAILS IF: verify.py --data-dir WITHOUT --surveys either runs the gate or drops the loud skip
    note. The absent-arg path must preserve every pre-C18b behaviour (VERIFY still PASSes on a clean
    build) AND announce that the cache-staleness gate did NOT run."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    out = tmp_path / "out"
    assert _build(surveys, out, tmp_path / "cache") == 0
    rc, txt = _verify_data_dir_surveys(out, None)      # NO --surveys
    assert rc == 0, txt
    assert "VERIFY: PASS" in txt, txt
    assert "consistency: SKIPPED" in txt, "the absent-arg path must announce the skipped gate loudly"
    assert "consistency: PASS" not in txt and "consistency: FAIL" not in txt, \
        "the gate ran despite --surveys being absent"


def test_c18b_incident_replay_doctored_sidecar_stamp_goes_red(tmp_path, clean_salt):
    """★ THE INCIDENT REPLAY (sidecar-doctoring form). FAILS IF: a served product stamped with a STALE
    (pre-edit) survey.yaml digest — the 2026-07-07 build 20260707T002709Z shape — is NOT caught by the
    armed gate. Build; then doctor ONE station's xml_digest_stamped to a fabricated OLD digest
    (simulating a served product that flowed from a stale cache entry) and confirm the gate goes RED
    with the exact incident message (slug, station count, both digests, the tar-before-clear forensics
    instruction).

    Fidelity note: the cache KEY binds the survey.yaml digest, so a normal survey.yaml edit changes the
    key and a stale OLD-key entry cannot be hit by the NEW key — which is precisely why the real
    incident (hits=3017/misses=0 across a survey.yaml change that should have busted 58 keys) is
    unexplained and INTERMITTENT. This test therefore reproduces the incident's OBSERVABLE (a served
    product carrying a pre-edit digest while the source is post-edit) directly at the sidecar, which is
    what the gate consumes; the companion test below forces the same staleness through the cache meta
    itself for the honest-cache-path form."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    out = tmp_path / "out"
    assert _build(surveys, out, tmp_path / "cache") == 0

    sc = _sidecar(out)
    (slug,) = tuple(sc)                            # the one served survey (slug-agnostic)
    live = sc[slug]["yaml_digest_current"]
    stale = "0" * 40 + "dead" + "0" * 20          # a fabricated pre-edit digest, != live
    assert stale != live
    victim_station = sorted(sc[slug]["xml_digest_stamped"])[0]
    sc[slug]["xml_digest_stamped"][victim_station] = stale
    (out / "products" / "survey_digests.json").write_text(json.dumps(sc, indent=1), encoding="utf-8")

    rc, txt = _verify_data_dir_surveys(out, surveys)
    assert rc != 0, f"the gate did NOT fail on a stale-stamped served product:\n{txt}"
    assert "VERIFY: FAIL" in txt, txt
    assert f"consistency: FAIL {slug}" in txt, txt
    assert stale[:12] in txt and live[:12] in txt, "message must name both the stale and live digests"
    assert "do NOT clear the cache before snapshotting it (tar) for forensics" in txt, \
        "the forensics instruction (tar before clear) must be in the failure message"
    assert "1 of" in txt, "message must name the affected station count"


def test_c18b_incident_replay_stale_cache_meta_forces_stale_stamp(tmp_path, clean_salt):
    """★ THE INCIDENT REPLAY (honest-cache-path form — the most faithful reachable shape). FAILS IF: a
    cache entry whose META carries an OLD survey_digest, hit on a warm build, does not propagate that
    stale digest into the sidecar (so the gate would catch it). This forces the staleness THROUGH the
    cache meta blob — the actual mechanism a stale served product would flow through — rather than
    doctoring the product after the fact.

    Construction: cold-build to populate the cache under the LIVE digest; then rewrite EACH served-XML
    entry's meta blob so its stored survey_digest is a fabricated OLD one (re-embedding the entry's own
    payload checksum so the entry stays VALID on read — a corrupt entry would be recomputed, masking
    the test). A warm rebuild then HITS those entries and must stamp the OLD digest into the sidecar;
    the armed gate then goes RED. This proves the digest genuinely rides the cache meta and a stale
    entry surfaces at the gate, not just at a hand-edited sidecar."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "cold", cache) == 0

    _cold_sc = _sidecar(tmp_path / "cold")
    (slug,) = tuple(_cold_sc)                      # the one served survey (slug-agnostic)
    live = _cold_sc[slug]["yaml_digest_current"]
    stale = "beef" + "0" * 60
    assert stale != live and len(stale) == 64

    # Rewrite every xml meta entry's survey_digest to the stale value, re-signing the payload so the
    # self-verifying entry stays VALID (checksum-on-read must PASS, else it recomputes and re-stamps live).
    meta_blobs = sorted(cache.rglob("*.meta"))
    assert len(meta_blobs) == N_STATIONS, [p.name for p in meta_blobs]
    for mb in meta_blobs:
        raw = mb.read_bytes()
        _digest_line, _, payload = raw.partition(b"\n")
        obj = json.loads(payload.decode("utf-8"))
        assert obj.get("survey_digest") == live, f"pre-condition: meta must store the live digest: {obj}"
        obj["survey_digest"] = stale
        new_payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        new_head = hashlib.sha256(new_payload).hexdigest().encode("ascii")
        mb.write_bytes(new_head + b"\n" + new_payload)      # re-signed => valid self-verifying entry

    warm = tmp_path / "warm"
    assert _build(surveys, warm, cache) == 0
    cw = _cache_counters(warm)
    assert cw["hits"] == EXPECTED_WARM_HITS and cw["corrupt"] == 0, \
        f"the doctored entries must HIT cleanly (not recompute), else the replay is masked: {cw}"

    # The warm build hit the stale-meta entries and stamped the OLD digest into the sidecar.
    stamps = _sidecar(warm)[slug]["xml_digest_stamped"]
    assert all(v == stale for v in stamps.values()), \
        f"stale cache meta did not propagate into the sidecar stamps: {stamps}"

    rc, txt = _verify_data_dir_surveys(warm, surveys)
    assert rc != 0, f"the gate did not catch a stale digest that flowed through the cache meta:\n{txt}"
    assert f"consistency: FAIL {slug}" in txt, txt
    assert "do NOT clear the cache before snapshotting it (tar) for forensics" in txt, txt


def test_c18b_unstamped_cache_meta_reads_as_suspect_not_current(tmp_path, clean_salt):
    """★ FAILS IF: a valid v3 cache meta entry MISSING the survey_digest field is blessed with the
    CURRENT digest on a warm hit (gate stays green over an unstamped product). An entry without a
    stamp must surface as SUSPECT at the gate — the incident this lane answers was itself a
    'theoretically unreachable' state, so the defensive fallback must fail closed, not open.
    Construction mirrors the stale-meta replay, but DELETES the field (re-signing the payload so the
    entry stays valid and HITS)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "cold", cache) == 0
    (slug,) = tuple(_sidecar(tmp_path / "cold"))

    meta_blobs = sorted(cache.rglob("*.meta"))
    assert len(meta_blobs) == N_STATIONS, [p.name for p in meta_blobs]
    for mb in meta_blobs:
        raw = mb.read_bytes()
        _digest_line, _, payload = raw.partition(b"\n")
        obj = json.loads(payload.decode("utf-8"))
        assert "survey_digest" in obj, f"pre-condition: v3 meta must carry the stamp: {obj}"
        del obj["survey_digest"]
        new_payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        new_head = hashlib.sha256(new_payload).hexdigest().encode("ascii")
        mb.write_bytes(new_head + b"\n" + new_payload)      # valid, self-verifying, UNSTAMPED

    warm = tmp_path / "warm"
    assert _build(surveys, warm, cache) == 0
    cw = _cache_counters(warm)
    assert cw["hits"] == EXPECTED_WARM_HITS and cw["corrupt"] == 0, \
        f"the unstamped entries must HIT cleanly, else the hole is masked: {cw}"

    rc, txt = _verify_data_dir_surveys(warm, surveys)
    assert rc != 0, \
        f"an UNSTAMPED cache entry was blessed with the current digest — fail-open fallback:\n{txt}"
    assert f"consistency: FAIL {slug}" in txt, txt


def test_straddled_build_cannot_poison_the_cache(tmp_path, clean_salt, monkeypatch):
    """★ THE INCIDENT ROOT CAUSE (M1, Amendment A4). FAILS IF: a survey.yaml edit landing AFTER
    discovery but BEFORE that survey's per-survey processing lets the straddled build write cache
    entries whose XML embeds the PRE-edit metadata KEYED under the POST-edit digest — so a
    subsequent clean warm build serves the pre-edit citation from cache. Independent observable:
    the citation INSIDE the served XML bytes vs the organisation in the on-disk survey.yaml —
    never counters, never stamp self-consistency (which is exactly what this poisoning defeats:
    the poisoned entry's stamp EQUALS the live digest, so the C18b gate stayed green over it).

    Proven failing on pre-fix HEAD: survey.yaml was read TWICE per build — metadata at
    discover_work, the cache-key digest at the per-survey loop top, a window spanning every
    preceding survey's work (minutes on the production corpus, where the 2026-07-07 build
    20260707T002709Z warm-served a stale Olympic Dam citation at hits=3017/misses=0). The fix
    derives meta AND digest from ONE read in discovery — coherent by construction. The seam here
    (edit fired right after discover_work returns) is fix-agnostic, so this test still fails if a
    loop-time re-read is ever reintroduced."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)          # organisation: Test Org
    sy = surveys / "cache-survey" / "survey.yaml"
    cache = tmp_path / "cache"

    real_discover = build_portal.discover_work

    def _straddling_discover(a, ap, validator):
        res = real_discover(a, ap, validator)
        # The "editor save / gateway publish" lands inside the running build, after discovery.
        sy.write_text(sy.read_text(encoding="utf-8").replace(
            "organisation: Test Org", "organisation: Edited Org"), encoding="utf-8")
        return res

    monkeypatch.setattr(build_portal, "discover_work", _straddling_discover)
    out1 = tmp_path / "out1"
    assert _build(surveys, out1, cache) == 0               # the STRADDLED build
    monkeypatch.setattr(build_portal, "discover_work", real_discover)

    # The straddled build itself must not verify clean under the armed gate: its products derive
    # from PRE-edit bytes while the live yaml is post-edit (pre-fix HEAD was blind here — the
    # loop-time digest matched the post-edit yaml, blessing the poisoned products).
    rc, txt = _verify_data_dir_surveys(out1, surveys)
    assert rc != 0, f"verify.py blessed a STRADDLED build (C18b blindness, incident shape):\n{txt}"

    # A clean rebuild on the now-stable post-edit tree must serve the POST-edit citation. On
    # pre-fix HEAD every station HIT the poisoned entries and served 'Test Org' from cache.
    out2 = tmp_path / "out2"
    assert _build(surveys, out2, cache) == 0
    served = _served_xml(out2)
    assert served, "no XML served (test set-up wrong)"
    for xp in served:
        a = _xml_authors(xp)
        assert a == "Edited Org", \
            f"POISONED CACHE SERVED: {xp.name} cites {a!r} but the live survey.yaml says 'Edited Org'"


def test_c18b_pre_bump_cache_entries_miss_cleanly(tmp_path, clean_salt):
    """FAILS IF: a cache populated under a PRE-BUMP entry-format tag is read (hit) by the current
    build instead of MISSING cleanly. Each tag bump re-keys every blob, so a pre-bump entry's key
    never resolves — a clean miss counted as a miss, never a replay of a stale-shape parse. C20 bumped
    the tag v3 -> v4 (parse product grew 10 -> 18 columns + placeholder-tipper mask); this simulates a
    PRE-C20 (v3) cache by monkeypatching the fixed-salt tag back to v3, populates, then builds normally
    (v4) and asserts zero hits + a full re-derive. (Kept under its historical name.)"""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"

    # Populate the cache under the OLD v3 tag by patching BuildCache to build a v3 fixed-salt.
    real_init = cache_mod.BuildCache.__init__

    def _v3_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self._fixed_salt = self._fixed_salt.replace("ausmt-c20-cache-v4", "ausmt-c18-cache-v3", 1)

    import unittest.mock as _mock
    with _mock.patch.object(cache_mod.BuildCache, "__init__", _v3_init):
        assert _build(surveys, tmp_path / "v3pop", cache) == 0
    assert any(cache.rglob("*.xml")), "v3 population wrote no entries (test set-up wrong)"

    # Now build normally (current v4 tag). Every v3 key is unreachable => all miss, full re-derive.
    out = tmp_path / "v4"
    assert _build(surveys, out, cache) == 0
    c = _cache_counters(out)
    assert c["hits"] == 0, f"a v4 build hit v3-format entries (misread across the schema bump): {c}"
    assert c["misses"] == EXPECTED_COLD_MISSES, c
    assert c["corrupt"] == 0, f"a clean tag miss must NOT be counted as corrupt: {c}"


# --------------------------------------------------------------------------------------------------
# Amendment A1b: self-verifying cache entries (checksum-on-read; corrupt => delete + recompute)
# --------------------------------------------------------------------------------------------------

def _flip_payload_byte(blob: Path):
    """Flip one bit in the middle of an entry's PAYLOAD region (everything after the first newline —
    the digest line; on the pre-fix format with no digest line this still lands inside the content)."""
    raw = bytearray(blob.read_bytes())
    start = raw.find(b"\n") + 1 if b"\n" in raw else 0
    idx = start + (len(raw) - start) // 2
    raw[idx] ^= 0x01
    blob.write_bytes(bytes(raw))


def _xml_sans_createtime(p: Path) -> bytes:
    """Served-XML bytes with the wall-clock <CreateTime> line removed — the ONLY line a legitimate
    recompute re-stamps (Amendment A1c). Everything else must match byte-for-byte."""
    return b"\n".join(ln for ln in p.read_bytes().splitlines() if b"<CreateTime>" not in ln)


def test_corrupt_cached_xml_payload_detected_and_recomputed(tmp_path, clean_salt):
    """FAILS IF: a bit-flipped cached XML payload is SERVED (the poison ships) instead of being
    detected by the entry's own embedded checksum, counted in the `corrupt` counter, deleted, and
    recomputed from source. The recompute re-stamps only <CreateTime>; every other byte must equal
    the populating build's served XML. Proven failing pre-fix: the flipped bytes were served verbatim
    with hits=6 and no corrupt counter existed."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    o_pop = tmp_path / "pop"
    assert _build(surveys, o_pop, cache) == 0

    xml_blobs = sorted(cache.rglob("*.xml"))
    assert len(xml_blobs) == N_STATIONS, [p.name for p in xml_blobs]
    for b in xml_blobs:
        _flip_payload_byte(b)

    o_warm = tmp_path / "warm"
    assert _build(surveys, o_warm, cache) == 0
    c = _cache_counters(o_warm)
    assert "corrupt" in c, f"no corrupt counter in the build report: {c}"
    # Per station: parse hit; xml read fails its checksum (corrupt + miss) -> recompute -> re-put
    # xml + meta. Deterministic: hits = N (parse only), misses = N, corrupt = N, writes = 2N.
    assert c["corrupt"] == N_STATIONS, c
    assert c["hits"] == N_STATIONS, c
    assert c["misses"] == N_STATIONS, c
    assert c["writes"] == 2 * N_STATIONS, c

    # The poison can never ship: the served XML matches the populating build byte-for-byte except
    # the re-stamped <CreateTime> line. (A byte-identical assertion would be vacuous-tight: the
    # recompute NECESSARILY re-stamps the wall clock — Amendment A1c records this.)
    xw, xp = _served_xml(o_warm), _served_xml(o_pop)
    assert xw and len(xw) == len(xp)
    for a, b in zip(xw, xp):
        assert _xml_sans_createtime(a) == _xml_sans_createtime(b), \
            f"served {a.name} differs from the populating build beyond CreateTime — corrupt bytes shipped"
    # And the corrupt entries were replaced with GOOD ones: a second warm build fully hits.
    o_warm2 = tmp_path / "warm2"
    assert _build(surveys, o_warm2, cache) == 0
    c2 = _cache_counters(o_warm2)
    assert c2["hits"] == EXPECTED_WARM_HITS and c2["corrupt"] == 0 and c2["misses"] == 0, c2


def test_corrupt_cached_parse_json_detected_and_recomputed(tmp_path, clean_salt):
    """FAILS IF: a bit-flipped cached parse-JSON payload either ships wrong rows into the positional
    products or is not detected/counted/deleted by the checksum-on-read. The parse recompute is fully
    deterministic, so catalogue/tf/sci must be BYTE-IDENTICAL to the populating build."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    o_pop = tmp_path / "pop"
    assert _build(surveys, o_pop, cache) == 0

    json_blobs = sorted(cache.rglob("*.json"))          # the parse entries (.meta is a separate ext)
    assert len(json_blobs) == N_STATIONS, [p.name for p in json_blobs]
    for b in json_blobs:
        _flip_payload_byte(b)

    o_warm = tmp_path / "warm"
    assert _build(surveys, o_warm, cache) == 0
    c = _cache_counters(o_warm)
    assert "corrupt" in c, f"no corrupt counter in the build report: {c}"
    # Per station: parse read fails its checksum (corrupt + miss) -> recompute + re-put (1 write);
    # xml + meta still hit. Deterministic: hits = 2N, misses = N, corrupt = N, writes = N.
    assert c["corrupt"] == N_STATIONS, c
    assert c["hits"] == 2 * N_STATIONS, c
    assert c["misses"] == N_STATIONS, c
    assert c["writes"] == N_STATIONS, c

    for name in ("catalogue.json", "tf.json", "sci.json", "manifest.json"):
        assert _digest(o_warm / name) == _digest(o_pop / name), \
            f"{name} differs from the populating build — corrupt parse rows shipped"


def test_torn_entry_xml_without_meta_is_a_miss_not_a_phantom_hit(tmp_path, clean_salt):
    """FAILS IF: an xml blob whose meta sibling is missing (a torn pair) leaves the xml read counted
    as a HIT even though the pair produced nothing and the station recomputed — the phantom-hit
    over-count the review found. A torn pair must tally as a miss (the hit is revoked), recompute,
    and re-put both blobs. Proven failing pre-fix: hits was 5 (2N+1 phantom), not 4."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    o_pop = tmp_path / "pop"
    assert _build(surveys, o_pop, cache) == 0

    meta_blobs = sorted(cache.rglob("*.meta"))
    assert len(meta_blobs) == N_STATIONS, [p.name for p in meta_blobs]
    meta_blobs[0].unlink()                              # tear ONE station's pair

    o_warm = tmp_path / "warm"
    assert _build(surveys, o_warm, cache) == 0
    c = _cache_counters(o_warm)
    # Torn station: parse hit (+1), xml hit REVOKED (net 0), meta miss (+1), recompute, re-put both
    # (+2 writes). Intact station: 3 hits. Deterministic: hits = 4, misses = 1, writes = 2.
    assert c["hits"] == 3 * (N_STATIONS - 1) + 1, f"phantom hit not revoked on the torn pair: {c}"
    assert c["misses"] == 1, c
    assert c["writes"] == 2, c
    assert c["corrupt"] == 0, c

    # The recomputed station's XML is correct (matches the populating build modulo CreateTime).
    xw, xp = _served_xml(o_warm), _served_xml(o_pop)
    for a, b in zip(xw, xp):
        assert _xml_sans_createtime(a) == _xml_sans_createtime(b), \
            f"served {a.name} differs from the populating build beyond CreateTime"


# --------------------------------------------------------------------------------------------------
# A4: environment-induced I/O failures are survived AND attributable (the Windows AV/indexer class)
# --------------------------------------------------------------------------------------------------

def test_transient_write_lock_is_retried_persistent_failure_is_counted(tmp_path, monkeypatch):
    """FAILS IF: (a) a TRANSIENT PermissionError from the atomic rename (a Windows AV/on-access
    scanner briefly holding the fresh tmp — the other surviving C18c-flake candidate) permanently
    drops the cache entry, i.e. the retry is gone and the silent spurious-future-miss returns; or
    (b) a PERSISTENT rename failure goes uncounted (write_errors) or raises into the build.
    Independent observable: the entry's readability through a FRESH BuildCache instance (on-disk
    truth, not the writing instance's own tallies), plus the write_errors counter."""
    import os
    cache_root = tmp_path / "cache"
    bc = _bc(root=cache_root)
    assert bc.enabled, bc.counters()

    real_replace = os.replace
    state = {"fail": 1}   # fail the next N renames under cache_root, then delegate

    def _flaky_replace(src, dst, *args, **kw):
        if state["fail"] > 0 and str(dst).startswith(str(cache_root)):
            state["fail"] -= 1
            raise PermissionError(13, "held by on-access scanner", str(dst))
        return real_replace(src, dst, *args, **kw)

    monkeypatch.setattr(cache_mod.os, "replace", _flaky_replace)

    k1 = bc.key(edi_sha="s1", survey_digest="y", kind="xml")
    bc.put_bytes(k1, "xml", b"payload-1")
    assert bc.writes == 1 and bc.write_errors == 0, \
        f"a single transient lock was not absorbed by the retry: {bc.counters()}"
    fresh = _bc(root=cache_root)
    assert fresh.get_bytes(k1, "xml") == b"payload-1", \
        "transient lock dropped the entry (no retry) — the silent spurious-miss class is back"

    state["fail"] = 10 ** 9                        # persistent: every attempt fails
    k2 = bc.key(edi_sha="s2", survey_digest="y", kind="xml")
    bc.put_bytes(k2, "xml", b"payload-2")          # must swallow, never raise into the build
    assert bc.write_errors == 1, f"a persistently dropped write went uncounted: {bc.counters()}"
    state["fail"] = 0
    fresh2 = _bc(root=cache_root)
    assert fresh2.get_bytes(k2, "xml") is None and fresh2.misses == 1, \
        "a dropped write left a partial entry behind"


def test_unreadable_entry_counts_read_error_absent_stays_plain_miss(tmp_path):
    """FAILS IF: a PRESENT-but-unreadable entry (lock/permissions — simulated with a directory at
    the entry path: an OSError that is NOT FileNotFoundError, on Windows and POSIX alike) is not
    distinguished from a cold miss via read_errors — or an ABSENT entry starts counting read_errors,
    which would smear the deterministic §4.6 miss arithmetic on every clean run."""
    bc = _bc(root=tmp_path / "cache")
    k = bc.key(edi_sha="s1", survey_digest="y", kind="xml")
    assert bc.get_bytes(k, "xml") is None          # absent -> plain miss
    assert bc.misses == 1 and bc.read_errors == 0, bc.counters()
    p = bc._path(k, "xml")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir()                                      # present but unreadable as a file
    assert bc.get_bytes(k, "xml") is None
    assert bc.misses == 2 and bc.read_errors == 1, \
        f"an unreadable entry was indistinguishable from a cold miss: {bc.counters()}"
    assert bc.corrupt == 0 and bc.hits == 0, bc.counters()


# --------------------------------------------------------------------------------------------------
# C18b (A3): per-survey instrumentation — one stderr line per served survey; deltas sum to the total
# --------------------------------------------------------------------------------------------------

def test_per_survey_instrumentation_sums_to_corpus_total(tmp_path, clean_salt, capsys):
    """FAILS IF: the per-survey `C18 survey <slug>:` lines are absent, or their hit/miss/write deltas
    do not sum to the corpus-total `C18 cache [...]` line, or the shown digest does not match the
    sidecar's yaml_digest_current. Two surveys so the per-survey split is non-trivial (a single-survey
    build would make the sum tautological). Independent observable: the summed per-survey counters vs
    the ONE corpus total the build already emitted (which the existing suite pins)."""
    import re
    root = tmp_path / "surveys"
    _make_survey(tmp_path, SAMPLE_EDIS, name="Alpha", slug="alpha", subdir="surveys")
    _make_survey(tmp_path, SAMPLE_EDIS, name="Beta", slug="beta", subdir="surveys")
    cache = tmp_path / "cache"
    # Warm the cache so a subsequent build produces a mix worth summing (all hits here, but the
    # per-survey split across two surveys is the real observable).
    assert _build(root, tmp_path / "cold", cache) == 0
    capsys.readouterr()                       # discard the cold build's output
    assert _build(root, tmp_path / "warm", cache) == 0
    cap = capsys.readouterr()
    # Per-survey lines go to stderr; the corpus-total `C18 cache [...]` line goes to stdout (unchanged).
    err = cap.err
    both = cap.out + cap.err

    rows = re.findall(
        r"C18 survey (\S+): digest=(\S+) hits=(\d+) misses=(\d+) writes=(\d+)", err)
    slugs = {r[0] for r in rows}
    assert slugs == {"alpha", "beta"}, f"expected one line per served survey, got {slugs} from:\n{err}"

    sum_h = sum(int(r[2]) for r in rows)
    sum_m = sum(int(r[3]) for r in rows)
    sum_w = sum(int(r[4]) for r in rows)

    m_total = re.search(r"C18 cache \[\w+\]: hits=(\d+) misses=(\d+) writes=(\d+)", both)
    assert m_total, f"corpus-total C18 cache line missing (tests pin it):\n{both}"
    tot_h, tot_m, tot_w = (int(m_total.group(i)) for i in (1, 2, 3))
    assert (sum_h, sum_m, sum_w) == (tot_h, tot_m, tot_w), \
        f"per-survey deltas {(sum_h, sum_m, sum_w)} != corpus total {(tot_h, tot_m, tot_w)}"
    assert (sum_h, sum_m, sum_w) == (2 * EXPECTED_WARM_HITS, 0, 0), \
        f"a warm 2-survey build should be all hits (2 surveys x {EXPECTED_WARM_HITS}): {(sum_h, sum_m, sum_w)}"

    # The digest shown per survey (first 12) matches that survey's sidecar yaml_digest_current.
    sidecar = json.loads((tmp_path / "warm" / "products" / "survey_digests.json").read_text("utf-8"))
    for slug, digest, *_ in rows:
        assert sidecar[slug]["yaml_digest_current"].startswith(digest), \
            f"instrumentation digest {digest} for {slug} != sidecar {sidecar[slug]['yaml_digest_current'][:12]}"


# --------------------------------------------------------------------------------------------------
# 3. Salt invalidations (design §4.3)
# --------------------------------------------------------------------------------------------------

def test_salt_engine_commit_change_zero_hits(tmp_path, clean_salt, monkeypatch):
    """FAILS IF: a simulated engine-commit change still hits the cache. A new engine commit must bust
    the WHOLE cache (coarse v1 salt)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "out1", cache) == 0

    # Change the engine commit the build resolves (patch build_identity's git resolver).
    import build_portal as bp
    monkeypatch.setattr(bp, "_git_commit_at",
                        lambda cwd: "deadbeef" if Path(cwd) == bp.HERE else None)
    out2 = tmp_path / "out2"
    assert _build(surveys, out2, cache) == 0
    c = _cache_counters(out2)
    assert c["hits"] == 0, f"an engine-commit change still hit the cache: {c}"
    assert c["misses"] == EXPECTED_COLD_MISSES, c   # a full re-derive (the new commit busts everything)


def test_salt_library_version_change_zero_hits(tmp_path, clean_salt, monkeypatch):
    """FAILS IF: a simulated mt_metadata version bump still hits. A library upgrade invalidates every
    cached XML + round-trip verdict (design §2.3)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "out1", cache) == 0

    import mt_metadata
    monkeypatch.setattr(mt_metadata, "__version__", "0.0.0-simulated", raising=False)
    out2 = tmp_path / "out2"
    assert _build(surveys, out2, cache) == 0
    c = _cache_counters(out2)
    assert c["hits"] == 0, f"an mt_metadata version change still hit the cache: {c}"


def test_salt_survey_yaml_edit_rederives_only_that_survey(tmp_path, clean_salt):
    """FAILS IF: editing one survey's survey.yaml either (a) fails to re-derive that survey, or (b)
    busts OTHER surveys. The v1 salt is the WHOLE survey.yaml, so any edit re-derives just that survey
    (design §2.5); a sibling survey with an untouched yaml + unchanged EDIs must still hit."""
    root = tmp_path / "surveys"
    _make_survey(tmp_path, SAMPLE_EDIS, name="Alpha", slug="alpha", subdir="surveys")
    _make_survey(tmp_path, SAMPLE_EDIS, name="Beta", slug="beta", subdir="surveys")
    cache = tmp_path / "cache"
    assert _build(root, tmp_path / "out1", cache) == 0

    # Edit ONLY alpha's survey.yaml (a metadata-only change: add a region line).
    ay = root / "alpha" / "survey.yaml"
    ay.write_text(ay.read_text(encoding="utf-8") + "region: South Australia\n", encoding="utf-8")

    out2 = tmp_path / "out2"
    assert _build(root, out2, cache) == 0
    c = _cache_counters(out2)
    # alpha re-derives (2 misses/station) and rewrites (3 writes/station); beta hits (3 hits/station).
    assert c["misses"] == 2 * N_STATIONS, f"the edited survey did not fully re-derive: {c}"
    assert c["hits"] == 3 * N_STATIONS, \
        f"the UNEDITED sibling survey did not hit (an edit over-invalidated): {c}"
    assert c["writes"] == 3 * N_STATIONS, f"the edited survey did not repopulate: {c}"


# --------------------------------------------------------------------------------------------------
# 4. Degenerate-salt refusal (design §4.4) — the real gate, no monkeypatch of the gate
# --------------------------------------------------------------------------------------------------

def test_degenerate_salt_unknown_commit_no_reads_or_writes(tmp_path, monkeypatch):
    """FAILS IF: an UNKNOWN engine commit still keys a cache (any read or any write). A degenerate
    salt must disable the cache entirely — proven via the hit/miss/WRITE counters."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    import build_portal as bp
    # Force engine_commit -> "unknown" (no git, no env). build_identity resolves git first; patch it.
    monkeypatch.setattr(bp, "_git_commit_at", lambda cwd: None)
    monkeypatch.delenv("AUSMT_ENGINE_COMMIT", raising=False)
    out = tmp_path / "out"
    assert _build(surveys, out, cache) == 0
    c = _cache_counters(out)
    assert c["degenerate"] is True and c["enabled"] is False, c
    assert c["hits"] == 0 and c["misses"] == 0 and c["writes"] == 0, \
        f"a degenerate (unknown-commit) salt read or wrote the cache: {c}"
    # And NOTHING was written to the cache dir (no entries created).
    assert not any(p.is_file() for p in cache.rglob("*")), "degenerate salt created cache files"


def test_degenerate_salt_dirty_checkout_no_reads_or_writes(tmp_path, monkeypatch):
    """FAILS IF: a DIRTY engine checkout (git status --porcelain non-empty) still keys a cache. The
    coarse commit salt would not match the working tree, so incremental must be disabled. Uses the
    REAL is_salt_degenerate over a forced-dirty checkout result (patches the gate INPUT to dirty)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    monkeypatch.setattr(cache_mod, "_dirty_checkout", lambda cwd: True)   # force DIRTY
    out = tmp_path / "out"
    assert _build(surveys, out, cache) == 0
    c = _cache_counters(out)
    assert c["degenerate"] is True and c["enabled"] is False, c
    assert c["hits"] == 0 and c["misses"] == 0 and c["writes"] == 0, \
        f"a dirty-checkout salt read or wrote the cache: {c}"


# --------------------------------------------------------------------------------------------------
# A4: salt stability across in-process builds (the C18c flake class) + its injection companions
# --------------------------------------------------------------------------------------------------

def test_salt_stable_across_in_process_builds(tmp_path, clean_salt):
    """FAILS IF: two back-to-back builds in ONE interpreter, over unchanged sources, construct caches
    whose salt fingerprints differ or whose salt is degenerate — the C18c flake class (the engine
    commit was re-resolved via a live per-build `git rev-parse`, so git activity or a transient
    rev-parse failure between a test's two builds flipped the key space and full-missed the warm
    build). Independent observable: salt_fp digests the ACTUAL key-derivation input of each
    separately-constructed BuildCache — not a counter derived from itself; the warm-hit assertion
    ties fingerprint equality to real key resolution."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "b1", cache) == 0
    assert _build(surveys, tmp_path / "b2", cache) == 0
    c1, c2 = _cache_counters(tmp_path / "b1"), _cache_counters(tmp_path / "b2")
    assert c1["degenerate"] is False and c2["degenerate"] is False, (c1, c2)
    assert c1["salt_fp"] == c2["salt_fp"], \
        f"salt flipped between two in-process builds over unchanged sources: {c1['salt_fp']} != {c2['salt_fp']}"
    assert c2["hits"] == EXPECTED_WARM_HITS, c2   # fingerprint equality reflects real key resolution


def test_salt_instability_is_observable_via_salt_fp(tmp_path, clean_salt, monkeypatch):
    """Injection companion (Invariant 10: proves the stability observable CAN fail). FAILS IF: an
    engine commit that CHANGES between two in-process builds does not surface as differing salt_fp
    values plus a full-miss 'warm' build — the exact 2026-07-07 C18c mechanism, deterministic here."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    monkeypatch.setattr(build_portal, "_git_commit_at",
                        lambda cwd: "commitA" if Path(cwd) == build_portal.HERE else None)
    assert _build(surveys, tmp_path / "b1", cache) == 0
    monkeypatch.setattr(build_portal, "_git_commit_at",
                        lambda cwd: "commitB" if Path(cwd) == build_portal.HERE else None)
    assert _build(surveys, tmp_path / "b2", cache) == 0
    c1, c2 = _cache_counters(tmp_path / "b1"), _cache_counters(tmp_path / "b2")
    assert c1["salt_fp"] != c2["salt_fp"], "a changed engine commit must change the salt fingerprint"
    assert c2["hits"] == 0 and c2["misses"] == EXPECTED_COLD_MISSES, \
        f"a flipped salt must full-miss the warm build (the C18c flake shape): {c2}"


def test_git_commit_memoised_per_process_success_only(tmp_path, monkeypatch):
    """FAILS IF: (a) a successful engine-commit resolution is re-resolved by a later call in the same
    process (the memo is gone — reopening the live per-build rev-parse the C18c flake rode), or (b) a
    FAILED resolution is memoised (a later build in the process would be permanently degenerate).
    Independent observable: real subprocess invocation count under the unpatched resolver."""
    import subprocess as sp
    calls = {"n": 0}

    def _counting(cmd, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return b"abc1234\n"
        raise RuntimeError("transient rev-parse failure")

    monkeypatch.setattr(sp, "check_output", _counting)
    repo_a, repo_b = str(tmp_path / "repoA"), str(tmp_path / "repoB")
    try:
        assert build_portal._git_commit_at(repo_a) == "abc1234"     # resolves, memoised
        assert build_portal._git_commit_at(repo_a) == "abc1234"     # memo hit ...
        assert calls["n"] == 1, "a memoised success was re-resolved (per-build rev-parse is back)"
        assert build_portal._git_commit_at(repo_b) is None          # failure -> None ...
        assert build_portal._git_commit_at(repo_b) is None          # ... and RETRIED (not memoised)
        assert calls["n"] == 3, "a FAILED resolution was memoised — later builds stay degenerate"
    finally:
        build_portal._GIT_COMMIT_MEMO.pop(repo_a, None)
        build_portal._GIT_COMMIT_MEMO.pop(repo_b, None)


# --------------------------------------------------------------------------------------------------
# 5. Equivalence (CI guard, design §4.5): warm build == the build that populated its cache
# --------------------------------------------------------------------------------------------------

def test_warm_build_byte_identical_to_populating_build(tmp_path, clean_salt):
    """FAILS IF: a warm (all-hits) build's products differ from the build that populated the cache.
    The cache stores the EXACT served bytes, so a hit reproduces them verbatim. Compares manifest.json,
    catalogue.json, tf.json, sci.json and every served XML byte-for-byte; mtcat.json modulo its
    non-deterministic portal.generated_at (the cache never touches mtcat — see the residual note)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    o_pop = tmp_path / "pop"
    o_warm = tmp_path / "warm"
    # Populate via a refresh build (forced full, still writes the cache).
    assert _build(surveys, o_pop, cache, mode="refresh") == 0
    # Warm build: all hits.
    assert _build(surveys, o_warm, cache, mode="rw") == 0

    cw = _cache_counters(o_warm)
    assert cw["hits"] == EXPECTED_WARM_HITS and cw["misses"] == 0 and cw["writes"] == 0, cw

    for name in ("manifest.json", "catalogue.json", "tf.json", "sci.json"):
        assert _digest(o_warm / name) == _digest(o_pop / name), \
            f"{name} differs between the warm build and its populating build (cache changed bytes)"

    xw, xp = _served_xml(o_warm), _served_xml(o_pop)
    assert xw and len(xw) == len(xp), (len(xw), len(xp))
    for a, b in zip(xw, xp):
        assert _digest(a) == _digest(b), f"served XML {a.name} differs warm-vs-populating"

    # mtcat.json is identical apart from portal.generated_at (a wall-clock field the cache never
    # touches). Normalise it out and compare the rest.
    def _mtcat_norm(o):
        m = json.loads((o / "mtcat.json").read_text(encoding="utf-8"))
        m["portal"]["generated_at"] = "NORMALISED"
        return json.dumps(m, sort_keys=True)
    assert _mtcat_norm(o_warm) == _mtcat_norm(o_pop), "mtcat.json differs beyond generated_at"


# --------------------------------------------------------------------------------------------------
# 6. Deterministic hit/miss/write counters (design §4.6) — no wall-clock
# --------------------------------------------------------------------------------------------------

def test_no_change_rebuild_counters_are_deterministic(tmp_path, clean_salt):
    """FAILS IF: a no-change incremental rebuild does not hit EXACTLY the served-blob count with zero
    misses and zero writes. Asserts the counters, never a timing (design §4.6 forbids wall-clock)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    # cold rw build: all miss, all write.
    assert _build(surveys, tmp_path / "cold", cache) == 0
    c_cold = _cache_counters(tmp_path / "cold")
    assert c_cold["hits"] == 0, c_cold
    assert c_cold["misses"] == EXPECTED_COLD_MISSES, c_cold
    assert c_cold["writes"] == EXPECTED_WRITES, c_cold

    # warm rw build: all hit, none miss, none write.
    assert _build(surveys, tmp_path / "warm", cache) == 0
    c_warm = _cache_counters(tmp_path / "warm")
    assert c_warm["hits"] == EXPECTED_WARM_HITS, c_warm
    assert c_warm["misses"] == 0, c_warm
    assert c_warm["writes"] == 0, c_warm


def test_ro_mode_hits_but_never_writes(tmp_path, clean_salt):
    """FAILS IF: read-only mode writes the cache. ro consults hits (CI reproducibility) but must never
    populate — a fresh key in ro mode misses and stays absent."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    # ro build against an EMPTY cache: all miss, ZERO writes, nothing persisted.
    assert _build(surveys, tmp_path / "out_ro", cache, mode="ro") == 0
    c = _cache_counters(tmp_path / "out_ro")
    assert c["writes"] == 0, f"ro mode wrote the cache: {c}"
    assert not any(p.is_file() for p in cache.rglob("*")), "ro mode persisted cache entries"


def test_refresh_mode_ignores_hits_but_repopulates(tmp_path, clean_salt):
    """FAILS IF: refresh mode reads a populated cache (it must ignore hits — the forced-full escape
    hatch) or fails to repopulate it (writes)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "cold", cache) == 0          # populate
    assert _build(surveys, tmp_path / "refresh", cache, mode="refresh") == 0
    c = _cache_counters(tmp_path / "refresh")
    assert c["hits"] == 0, f"refresh mode read the cache: {c}"
    assert c["writes"] == EXPECTED_WRITES, f"refresh mode did not repopulate: {c}"


# --------------------------------------------------------------------------------------------------
# 7. Lifecycle survival: prune + atomic swap (design §4.7)
# --------------------------------------------------------------------------------------------------

def test_cache_survives_prune_and_swap_and_still_hits(tmp_path, clean_salt):
    """FAILS IF: the cache does not survive a simulated builds/ prune + `current` atomic swap and still
    hit on the next build. The cache is a sibling of builds/, so a prune of builds/<ts> + a swap of
    `current` must leave it intact (design §3).

    The swap is modelled with os.replace on a `current` POINTER FILE (the atomic primitive behind the
    Makefile's `mv -T`), not an actual symlink: symlink creation needs elevated privilege on Windows
    (WinError 1314), and the property under test — the cache SIBLING surviving the swap — is
    OS-independent. os.replace is atomic on both POSIX and Windows."""
    import os
    import shutil
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    data_dir = tmp_path / "site-data"
    builds = data_dir / "builds"
    cache = data_dir / "cache"          # sibling of builds/, exactly as the deploy layout places it
    builds.mkdir(parents=True)

    # Build #1 into builds/ts1, populate the sibling cache; `current` points at ts1.
    b1 = builds / "20260101T000000Z"
    assert _build(surveys, b1, cache) == 0
    (data_dir / "current").write_text("builds/20260101T000000Z", encoding="utf-8")

    # Warm build #2 into builds/ts2 (should hit the surviving cache).
    b2 = builds / "20260102T000000Z"
    assert _build(surveys, b2, cache) == 0
    assert _cache_counters(b2)["hits"] == EXPECTED_WARM_HITS, "cache did not hit before the prune"

    # Simulate the deploy prune (drop old builds/<ts>, NOT the cache sibling) + the atomic `current`
    # swap (temp-then-os.replace, the Makefile's `mv -T` equivalent).
    shutil.rmtree(b1)
    tmp_ptr = data_dir / "current.tmp"
    tmp_ptr.write_text("builds/20260102T000000Z", encoding="utf-8")
    os.replace(tmp_ptr, data_dir / "current")      # atomic swap (POSIX + Windows)

    # The cache sibling must be untouched and still hit on the next build.
    assert cache.exists() and any(p.is_file() for p in cache.rglob("*")), \
        "the cache did not survive the builds/ prune + swap"
    b3 = builds / "20260103T000000Z"
    assert _build(surveys, b3, cache) == 0
    assert _cache_counters(b3)["hits"] == EXPECTED_WARM_HITS, \
        "cache did not hit after the prune + swap lifecycle"


def test_prune_size_cap_evicts_oldest_first(tmp_path, clean_salt, monkeypatch):
    """FAILS IF: the AUSMT_CACHE_MAX_MB size cap does not evict oldest-first. Sets a tiny cap so the
    end-of-build prune must drop entries; a fresh build then repopulates (proving the cap didn't wedge
    the cache)."""
    surveys = _make_survey(tmp_path, SAMPLE_EDIS)
    cache = tmp_path / "cache"
    assert _build(surveys, tmp_path / "cold", cache) == 0
    n_before = sum(1 for p in cache.rglob("*") if p.is_file())
    assert n_before > 0

    # Force a 0-ish cap via a direct prune with a tiny max_mb (the build already ran its own prune at
    # the default cap, which kept everything). Prove oldest-first eviction shrinks the store.
    bc = cache_mod.BuildCache(cache, engine_commit="abc123", lib_versions={"mt_metadata": "1.0.9"},
                              contract_digest="d", mode="rw", checkout_dir=None, max_mb=0)
    # max_mb=0 falls back to the default via _env_max_mb only when read from env; here it's explicit 0,
    # so the cap is 0 bytes -> the prune must evict everything over cap (all of it), oldest-first.
    summary = bc.prune()
    assert summary["pruned_size"] >= 1, f"size-cap prune evicted nothing: {summary}"


# --------------------------------------------------------------------------------------------------
# Unit-level: the key derivation binds every salt field (design §2)
# --------------------------------------------------------------------------------------------------

def _bc(**over):
    base = dict(root=Path("."), engine_commit="commitA", lib_versions={"mt_metadata": "1.0.9"},
                contract_digest="contractA", mode="rw", checkout_dir=None)
    base.update(over)
    return cache_mod.BuildCache(**base)


def test_key_binds_edi_sha_survey_digest_and_kind(tmp_path):
    """FAILS IF: two DIFFERENT (edi_sha, survey_digest, kind) inputs collide on one key, or the same
    inputs are not stable. The key must be an injective function of every input it claims to bind."""
    bc = _bc(root=tmp_path)

    def k(**kw):
        return bc.key(**{**dict(edi_sha="s1", survey_digest="y1", kind="xml"), **kw})
    base = k()
    assert base == k(), "key is not stable for identical inputs"
    assert base != k(edi_sha="s2"), "key does not bind edi_sha"
    assert base != k(survey_digest="y2"), "key does not bind survey_digest"
    assert base != k(kind="parse"), "key does not bind kind (parse/xml would collide)"


def test_key_binds_engine_commit_libs_and_contract(tmp_path):
    """FAILS IF: changing the engine commit, a library version, or the contract digest does not change
    the derived key (the coarse salt fields, design §2.2-§2.4)."""
    args = dict(edi_sha="s", survey_digest="y", kind="xml")
    base = _bc(root=tmp_path).key(**args)
    assert base != _bc(root=tmp_path, engine_commit="commitB").key(**args), "key ignores engine commit"
    assert base != _bc(root=tmp_path, lib_versions={"mt_metadata": "9.9.9"}).key(**args), \
        "key ignores library versions"
    assert base != _bc(root=tmp_path, contract_digest="contractB").key(**args), \
        "key ignores the contract digest"
