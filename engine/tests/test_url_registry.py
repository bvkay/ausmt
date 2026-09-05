"""The published-URL id freeze.

/surveys/<slug>, /stations/<ausmt_id> and /collections/<id> are published URL contracts, so the id
vocabulary is FROZEN in portal/data/url_registry.json. Pinned here:

  * the freeze: an id REMOVED or CHANGED relative to the registry fails with the prescribed
    message (a rename surfaces as a removal beside an addition and fails on the removal);
    ADDITIONS pass and are auto-recorded;
  * the sitemap pin: every entity id the sitemap advertises (path form, and the legacy fragment
    form so a regression cannot smuggle ids past the pin) must appear in the registry;
  * the committed registry itself: well-formed, non-empty, sorted, and carrying the two ids other
    pins rely on (the doctor leg's vulcan-2022, the auslamp collection);
  * a real-data tier that checks the committed registry against an actual built data tree when
    one is available (AUSMT_URL_REGISTRY_DATA), skipping cleanly elsewhere.

FAILS PRE-CHANGE: extract.url_registry did not exist.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from extract import url_registry as ur   # noqa: E402

_COMMITTED = ROOT.parent / "portal" / "data" / "url_registry.json"

# Image-topology guard, the test_mtcat_version_parity.py pattern exactly: the engine image COPYs
# engine/ (+ one unrelated portal file), so the checked-in registry legitimately does not exist
# there. Probe a SET of OTHER portal surfaces -- if none is present this is the image and the
# committed-registry test skips with the allow-listed reason; if ANY is present a portal tree is
# meant to be here, the guard opens, and a missing registry FAILS loudly (a broken checkout must
# never skip). The registry itself is deliberately NOT in the probe set.
_PORTAL_TREE_PROBES = (
    ROOT.parent / "portal" / "portal.config.yaml",
    ROOT.parent / "portal" / "config.js",
    ROOT.parent / "portal" / "index.html",
)
IMAGE_TOPOLOGY_SKIP_REASON = ("engine image build: portal tree not shipped "
                              "(designed topology; the committed registry is pinned from the "
                              "checkout workflows)")
portal_tree = pytest.mark.skipif(not any(p.is_file() for p in _PORTAL_TREE_PROBES),
                                 reason=IMAGE_TOPOLOGY_SKIP_REASON)

_MTCAT = {
    "surveys": [{"survey_id": "vulcan-2022"}, {"survey_id": "olympic-dam-2004"}],
    "stations": [{"station_id": "au.vulcan-2022.MBV07"},
                 {"station_id": "au.olympic-dam-2004.OD01"}],
    "collections": [{"collection_id": "auslamp"}],
}


def _registry_of(mtcat) -> dict:
    reg = ur._empty_registry()
    ur.merge_additions(reg, ur.ids_from_mtcat(mtcat))
    return reg


def _sitemap(*locs) -> str:
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in locs)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>\n")


def test_ids_from_mtcat_extracts_all_three_kinds():
    ids = ur.ids_from_mtcat(_MTCAT)
    assert ids["surveys"] == ["olympic-dam-2004", "vulcan-2022"]
    assert ids["stations"] == ["au.olympic-dam-2004.OD01", "au.vulcan-2022.MBV07"]
    assert ids["collections"] == ["auslamp"]
    # Malformed rows are skipped, never crash: a row with no id publishes no URL.
    assert ur.ids_from_mtcat({"surveys": [{}, {"survey_id": ""}, "junk"]})["surveys"] == []


def test_freeze_green_when_registry_matches_the_build():
    violations, additions = ur.check_freeze(_registry_of(_MTCAT), ur.ids_from_mtcat(_MTCAT))
    assert violations == [] and additions == {}


def test_freeze_flags_a_removed_id_with_the_prescribed_message():
    """THE FREEZE, red side: drop one published slug from the build; the check must FAIL naming
    the id and prescribing the remedy verbatim (redirect entry + dated registry note, never a
    silent rename)."""
    current = ur.ids_from_mtcat(_MTCAT)
    current["surveys"] = [s for s in current["surveys"] if s != "vulcan-2022"]
    violations, _ = ur.check_freeze(_registry_of(_MTCAT), current)
    assert len(violations) == 1, violations
    assert "'vulcan-2022'" in violations[0] and violations[0].startswith("surveys:")
    assert ("a published URL id moved - add a redirect entry and a dated registry note, "
            "never rename silently.") in violations[0]


def test_freeze_treats_a_rename_as_removal_plus_addition_and_fails():
    """A CHANGED id is a rename: the old id is a violation (its published URL just died), the new
    id is an addition. The check fails on the removal; the addition alone never masks it."""
    current = ur.ids_from_mtcat(_MTCAT)
    current["stations"] = ["au.vulcan-2022.MBV07-reprocessed" if s == "au.vulcan-2022.MBV07" else s
                           for s in current["stations"]]
    violations, additions = ur.check_freeze(_registry_of(_MTCAT), current)
    assert len(violations) == 1 and "'au.vulcan-2022.MBV07'" in violations[0]
    assert ur.MOVED_MSG in violations[0]
    assert additions == {"stations": ["au.vulcan-2022.MBV07-reprocessed"]}


def test_additions_pass_the_freeze():
    current = ur.ids_from_mtcat(_MTCAT)
    current["surveys"] = sorted(current["surveys"] + ["brand-new-2026"])
    violations, additions = ur.check_freeze(_registry_of(_MTCAT), current)
    assert violations == []
    assert additions == {"surveys": ["brand-new-2026"]}


def test_sitemap_can_never_advertise_an_unpinned_id():
    """THE SITEMAP PIN: an advertised entity id absent from the registry is a violation, in the
    path form AND in the legacy fragment form (a regression to fragment emission must not smuggle
    ids past the pin). Pinned ids pass."""
    reg = _registry_of(_MTCAT)
    ok = ur.check_sitemap(reg, ur.sitemap_entity_ids(_sitemap(
        "https://x.test/", "https://x.test/surveys/vulcan-2022",
        "https://x.test/stations/au.vulcan-2022.MBV07", "https://x.test/collections/auslamp")))
    assert ok == []
    bad_path = ur.check_sitemap(reg, ur.sitemap_entity_ids(_sitemap(
        "https://x.test/surveys/unpinned-2027")))
    assert len(bad_path) == 1 and "'unpinned-2027'" in bad_path[0]
    assert "can never advertise an unpinned id" in bad_path[0]
    bad_frag = ur.check_sitemap(reg, ur.sitemap_entity_ids(_sitemap(
        "https://x.test/#/survey/frag-smuggled")))
    assert len(bad_frag) == 1 and "'frag-smuggled'" in bad_frag[0]


def _write_data_dir(tmp_path, mtcat, sitemap_text=None) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mtcat.json").write_text(json.dumps(mtcat), encoding="utf-8")
    if sitemap_text is not None:
        (d / "sitemap.xml").write_text(sitemap_text, encoding="utf-8")
    return d


def _cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "extract.url_registry", *args],
                          cwd=str(ROOT), capture_output=True, text=True)


def test_cli_update_seeds_then_check_is_green_and_auto_records_additions(tmp_path):
    """END TO END: --update seeds the registry from a built tree; --check then passes; a LATER
    build with a new survey passes --check AND auto-records the new id into the registry file
    (additions are fine and auto-recorded)."""
    data = _write_data_dir(tmp_path, _MTCAT)
    reg = tmp_path / "url_registry.json"
    r = _cli("--data", str(data), "--registry", str(reg), "--update")
    assert r.returncode == 0, r.stderr
    assert reg.is_file()
    r = _cli("--data", str(data), "--registry", str(reg), "--check")
    assert r.returncode == 0, r.stderr

    grown = json.loads(json.dumps(_MTCAT))
    grown["surveys"].append({"survey_id": "brand-new-2026"})
    data2 = _write_data_dir(tmp_path, grown)
    r = _cli("--data", str(data2), "--registry", str(reg), "--check")
    assert r.returncode == 0, r.stderr
    assert "recorded 1 new surveys id(s): brand-new-2026" in r.stdout
    assert "brand-new-2026" in json.loads(reg.read_text(encoding="utf-8"))["surveys"]


def test_cli_check_fails_on_a_mutated_slug_with_the_prescribed_message(tmp_path):
    """THE FREEZE, end to end (the module's RED proof): mutate one published slug in the build; the
    committed-registry check must exit non-zero and print the prescribed message."""
    data = _write_data_dir(tmp_path, _MTCAT)
    reg = tmp_path / "url_registry.json"
    assert _cli("--data", str(data), "--registry", str(reg), "--update").returncode == 0
    mutated = json.loads(json.dumps(_MTCAT))
    mutated["surveys"][0]["survey_id"] = "vulcan-2022-renamed"
    data2 = _write_data_dir(tmp_path / "b", mutated)
    r = _cli("--data", str(data2), "--registry", str(reg), "--check")
    assert r.returncode == 1
    assert "'vulcan-2022'" in r.stderr
    assert ("a published URL id moved - add a redirect entry and a dated registry note, "
            "never rename silently.") in r.stderr
    # --update must refuse to bless the rename too.
    r = _cli("--data", str(data2), "--registry", str(reg), "--update")
    assert r.returncode == 1 and "refuses" in r.stderr


def test_cli_check_fails_on_an_unpinned_sitemap_id(tmp_path):
    """A sitemap advertising an id the (fresh) build does not produce and the registry does not
    pin must fail the check: nothing reaches the published surface unfrozen."""
    reg = tmp_path / "url_registry.json"
    data = _write_data_dir(tmp_path, _MTCAT)
    assert _cli("--data", str(data), "--registry", str(reg), "--update").returncode == 0
    data2 = _write_data_dir(tmp_path / "b", _MTCAT,
                            _sitemap("https://x.test/surveys/never-built-2027"))
    r = _cli("--data", str(data2), "--registry", str(reg), "--check")
    assert r.returncode == 1 and "'never-built-2027'" in r.stderr


def test_cli_check_without_a_registry_refuses(tmp_path):
    data = _write_data_dir(tmp_path, _MTCAT)
    r = _cli("--data", str(data), "--registry", str(tmp_path / "missing.json"), "--check")
    assert r.returncode == 2 and "seed it with --update" in r.stderr


@portal_tree
def test_committed_registry_is_well_formed_and_carries_the_cross_pinned_ids():
    """The CHECKED-IN registry: all three kinds present, non-empty, sorted, station ids in the
    au.<slug>.<station> shape, and the two ids other pins rely on are frozen (doctor.sh probes
    /surveys/vulcan-2022; the collection pages ship auslamp). FAILS IF the registry is missing,
    empty, unsorted, or loses either cross-pinned id. Skips ONLY in the engine image (no portal
    tree at all); on any checkout a missing registry fails loudly."""
    assert _COMMITTED.is_file(), "portal/data/url_registry.json must be checked in"
    reg = json.loads(_COMMITTED.read_text(encoding="utf-8"))
    for kind in ("surveys", "stations", "collections"):
        ids = reg[kind]
        assert ids and ids == sorted(ids), f"{kind} must be non-empty and sorted"
        assert len(ids) == len(set(ids)), f"{kind} must be duplicate-free"
    assert "vulcan-2022" in reg["surveys"], "the doctor leg's pinned slug must stay frozen"
    assert "auslamp" in reg["collections"]
    assert all(s.startswith("au.") for s in reg["stations"]), "ausmt_ids carry the au. prefix"
    assert ur.MOVED_MSG in reg["_meta"]["contract"], "the registry must carry the freeze rule"
    assert isinstance(reg["_meta"]["redirects"], dict) and isinstance(reg["_meta"]["notes"], list)


def test_committed_registry_against_a_real_built_tree():
    """REAL-DATA TIER: when AUSMT_URL_REGISTRY_DATA names a built portal data dir (mtcat.json,
    optionally sitemap.xml), the committed registry must pass the freeze and sitemap checks
    against it. Skips cleanly where no built tree exists (dev boxes, CI): the fixture-driven tests
    above prove the checker itself, and the publish flow runs the CLI against the real
    build."""
    data = os.environ.get("AUSMT_URL_REGISTRY_DATA", "").strip()
    if not data or not (Path(data) / "mtcat.json").is_file():
        pytest.skip("AUSMT_URL_REGISTRY_DATA does not name a built data dir (mtcat.json)")
    current = ur.ids_from_data_dir(Path(data))
    registry = ur.load_registry(_COMMITTED)
    violations, additions = ur.check_freeze(registry, current)
    assert violations == [], "a published URL id moved or vanished:\n" + "\n".join(violations)
    sm = Path(data) / "sitemap.xml"
    if sm.is_file():
        merged = ur.merge_additions(json.loads(json.dumps(registry)), additions)
        sviol = ur.check_sitemap(merged, ur.sitemap_entity_ids(sm.read_text(encoding="utf-8")))
        assert sviol == [], "\n".join(sviol)


def test_the_hand_off_namespace_can_never_reach_the_registry_or_the_sitemap():
    """NEGATIVE PIN (THREDDS). `/go/ts/<survey>/<station>/<level>` is a front-door redirect into
    the NCI archive, NOT a published entity URL: it resolves through a generated table whose
    membership is the access decision, so an id reaching this registry through it would freeze a
    route the access gate is entitled to withdraw.

    Two closed things already make that impossible and neither is stated anywhere a reader would
    find it: KINDS is frozen at three, and the path/fragment patterns match only those three
    prefixes. This pin says so out loud, because the hand-off routes DO carry a survey slug and a
    station id in their path, which is exactly the shape a future 'just add the new prefix' change
    would be tempted by.

    FAILS IF a fourth kind appears, or if a `/go/ts/` URL in a sitemap yields any entity id
    (control: the real /surveys/ and /stations/ forms in the same document still do)."""
    assert ur.KINDS == ("surveys", "stations", "collections")
    assert set(ur._PATH_RE) == set(ur.KINDS) and set(ur._FRAG_RE) == set(ur.KINDS)
    xml = (
        "<urlset>"
        "<url><loc>https://example.org/go/ts/vulcan-2022/MBV07/raw_packed</loc></url>"
        "<url><loc>https://example.org/go/ts/vulcan-2022/MBV07/level1_mth5</loc></url>"
        "</urlset>")
    assert ur.sitemap_entity_ids(xml) == {"surveys": [], "stations": [], "collections": []}, \
        "a hand-off route must advertise no entity id at all"
    control = ("<urlset><url><loc>https://example.org/surveys/vulcan-2022</loc></url>"
               "<url><loc>https://example.org/stations/au.vulcan-2022.MBV07</loc></url></urlset>")
    assert ur.sitemap_entity_ids(control) == {
        "surveys": ["vulcan-2022"], "stations": ["au.vulcan-2022.MBV07"], "collections": []}, \
        "the published forms must still be picked up, or this pin is vacuous"
