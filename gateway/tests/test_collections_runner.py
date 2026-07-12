"""C43 Stage-3a collections read-job pins (record D5-A / D13, Invariant 10).

These exercise gateway.runner.edit.run_collections_job DIRECTLY (the same in-suite-reaches-the-runner
pattern as test_edit_runner.py). Each pin states its failure criterion in one line; the parity,
divergence and slug pins are mutation-provable (the red-then-green evidence is in the C43 Stage-3a
report). The rollup/near-dup PARITY pins import the engine's own _group_collections /
_near_duplicate_collection_ids and assert the runner AGREES with them for a real fixture tree — so the
console can never disagree with the portal. Importing the engine pulls the mt_metadata extractor
stack, so those two pins skipif on a stack-less env (the gateway CI lane), with the one skip reason the
gateway lane's tripwire allows; every OTHER pin here is engine-free and RUNS in that lane.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from gateway.runner import edit

_ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"


def _has_engine_stack() -> bool:
    """True when the engine's build_portal is importable — it needs the mt_metadata extractor stack
    (the module imports _mtm at load). The stack-less gateway CI lane legitimately lacks it, so the
    two parity pins skip there with the gateway lane's one allowed reason."""
    return importlib.util.find_spec("mt_metadata") is not None and _ENGINE_DIR.is_dir()


def _engine_collections():
    """Import the engine rollup functions (adds engine/ to sys.path like the engine runs itself). The
    caller has already skipif-guarded on the stack, so a bare ImportError here is a real breakage."""
    if str(_ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(_ENGINE_DIR))
    from extract.build_portal import _group_collections, _near_duplicate_collection_ids
    return _group_collections, _near_duplicate_collection_ids


def _mk(surveys_root: Path, slug: str, *, name: str, collection: str | None, n_edi: int = 1,
        raw: str | None = None) -> None:
    """Materialise one published survey package: survey.yaml (slug + name + optional collection block)
    and `n_edi` EDI files (the station list is the files themselves — a directory listing, never a
    parse). `collection` is the raw YAML block text (e.g. 'collection:\\n  id: auslamp\\n...') or None.
    `raw`, when given, is written as the ENTIRE survey.yaml verbatim (for the malformed/non-mapping
    negative controls) instead of the templated body."""
    d = surveys_root / "surveys" / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True, exist_ok=True)
    for i in range(n_edi):
        (d / "transfer_functions" / "edi" / f"S{i:02d}.edi").write_text(">HEAD\n>END\n", encoding="utf-8")
    if raw is not None:
        body = raw
    else:
        body = f"slug: {slug}\nname: \"{name}\"\nversion: 1.0.0\ncountry: Australia\n"
        if collection:
            body += collection
    with open(d / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(body)


_AUSLAMP_FULL = ("collection:\n  id: auslamp\n  title: AusLAMP\n  type: programme\n"
                 "  status: active\n  start_year: 2003\n  last_updated: 2026-06-15\n"
                 "  description: National MT programme.\n")


# --------------------------------------------------------------------------------------------------
# Pin 1 — ROLLUP PARITY. FAILS IF the console's rolled-up programme fields disagree with the portal's
# (engine _group_collections) for the same tree — i.e. the curator would see a different title/type/
# status/start_year/last_updated/description/n_surveys than the portal serves readers.
# --------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not _has_engine_stack(),
                    reason="real engine stack / sample survey / validator not present")
def test_rollup_parity_with_engine_group_collections(tmp_path):
    import yaml as pyyaml
    sroot = tmp_path / "surveys-live"
    # Distinct LABELS (names) so the engine's surveys_meta (keyed by label) does not collapse two
    # members — that label-collision is an engine quirk, not what this parity pin is measuring. The
    # first member (sorted-slug order) declares the full block; the second DIVERGES on title + status,
    # so first-declarer is genuinely exercised (a naive last-wins would red this).
    _mk(sroot, "auslamp-a", name="AusLAMP SA Gawler", collection=_AUSLAMP_FULL, n_edi=3)
    _mk(sroot, "auslamp-b", name="AusLAMP SA NE",
        collection="collection:\n  id: auslamp\n  title: AusLAMP Project\n  status: completed\n", n_edi=2)
    _mk(sroot, "cap", name="Capricorn 2010",
        collection="collection:\n  id: capricorn\n  title: Capricorn\n  type: programme\n"
                   "  status: completed\n", n_edi=4)
    # F1 edge (D5-B): an out-of-vocab status FIRST (wamt-a sorts first) then a VALID status LATER. The
    # engine drops the invalid status inside the per-member fold, re-opening the slot, so the rollup
    # lands on 'active' — the runner must agree (this reds the pre-F1 end-of-loop drop).
    _mk(sroot, "wamt-a", name="WA MT A",
        collection="collection:\n  id: wamt\n  title: WA MT\n  status: complete\n", n_edi=1)
    _mk(sroot, "wamt-b", name="WA MT B",
        collection="collection:\n  id: wamt\n  status: active\n", n_edi=1)
    # F2 edge (D5-B): a falsy id (unquoted 0) is dropped by BOTH the engine (truthiness) and the runner
    # — so it forms no collection on either side (same-input parity holds).
    _mk(sroot, "zero-id", name="Zero Id",
        collection="collection:\n  id: 0\n  title: Zero\n", n_edi=1)
    _mk(sroot, "lone", name="Lone Survey", collection=None)  # no block -> absent from the rollup

    group_collections, _ = _engine_collections()
    # Build surveys_meta EXACTLY as build_portal does: sorted(iterdir()) order, keyed by y['name'].
    surveys_meta = {}
    for d in sorted((sroot / "surveys").iterdir()):
        y = pyyaml.safe_load((d / "survey.yaml").read_text(encoding="utf-8"))
        surveys_meta[y.get("name", d.name)] = y
    engine_out, _ = group_collections(surveys_meta, [])

    runner_out = edit.run_collections_job(sroot)["collections"]
    # SAME-INPUT parity (D5-B narrowing): the runner's rollup logic equals the engine's given the same
    # member set — the same collections, and every rolled-up field identical.
    assert set(runner_out) == set(engine_out), (set(runner_out), set(engine_out))
    assert "wamt" in runner_out and "auslamp" in runner_out
    assert "0" not in runner_out and 0 not in runner_out, "a falsy id must not form a collection (F2)"

    def _norm(v):  # collections.json stringifies a YAML date exactly this way (default=str)
        return json.loads(json.dumps(v, default=str))

    for cid in engine_out:
        for fld in ("title", "type", "status", "start_year", "last_updated", "description",
                    "n_surveys"):
            assert _norm(engine_out[cid].get(fld)) == runner_out[cid].get(fld), \
                f"{cid}.{fld}: engine={engine_out[cid].get(fld)!r} runner={runner_out[cid].get(fld)!r}"
    # Explicit F1 assertion (make the edge visible even if the engine's own value ever shifts).
    assert runner_out["wamt"]["status"] == "active", runner_out["wamt"]["status"]


# --------------------------------------------------------------------------------------------------
# Pin 2 — NEAR-DUPLICATE PARITY. FAILS IF the runner's near_duplicates disagrees with the engine's
# _near_duplicate_collection_ids over the same distinct ids (auslamp + AusLAMP must form ONE group).
# --------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not _has_engine_stack(),
                    reason="real engine stack / sample survey / validator not present")
def test_near_duplicate_parity_with_engine(tmp_path):
    import yaml as pyyaml
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "auslamp-a", name="A", collection=_AUSLAMP_FULL, n_edi=1)
    _mk(sroot, "auslamp-b", name="B",
        collection="collection:\n  id: auslamp\n  title: AusLAMP Project\n", n_edi=1)
    _mk(sroot, "vulcan", name="V", collection="collection:\n  id: AusLAMP\n  title: AusLAMP\n", n_edi=1)

    group_collections, near_dup = _engine_collections()
    surveys_meta = {}
    for d in sorted((sroot / "surveys").iterdir()):
        y = pyyaml.safe_load((d / "survey.yaml").read_text(encoding="utf-8"))
        surveys_meta[y.get("name", d.name)] = y
    coll_by_id, _ = group_collections(surveys_meta, [])
    engine_groups = near_dup(list(coll_by_id))          # the engine calls it over the DISTINCT ids
    runner_groups = edit.run_collections_job(sroot)["near_duplicates"]
    assert runner_groups == engine_groups == [["AusLAMP", "auslamp"]]


def test_near_duplicate_behavioural_case_fold(tmp_path):
    """Engine-free near-dup behaviour: ids differing only by case/whitespace form ONE group; distinct
    ids never collide. FAILS IF the case-fold is dropped (the red mutation: group by the raw id) — then
    'auslamp' and 'AusLAMP' would NOT collide and this returns []."""
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "a", name="A", collection="collection:\n  id: auslamp\n", n_edi=1)
    _mk(sroot, "b", name="B", collection="collection:\n  id: AusLAMP\n", n_edi=1)
    _mk(sroot, "c", name="C", collection="collection:\n  id: capricorn\n", n_edi=1)
    groups = edit.run_collections_job(sroot)["near_duplicates"]
    assert groups == [["AusLAMP", "auslamp"]], groups


# --------------------------------------------------------------------------------------------------
# F1 (D5-B) — out-of-vocab status drop happens INSIDE the per-member fold. FAILS IF an invalid status
# on the first member permanently nulls the field: an invalid-first + valid-later corpus must roll up
# to the VALID status (the pre-fix end-of-loop drop yielded None here — red-proven vs the engine).
# --------------------------------------------------------------------------------------------------
def test_invalid_status_first_valid_later_rolls_up_valid(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "wamt-a", name="WA A",  # sorts first, declares an out-of-vocab status
        collection="collection:\n  id: wamt\n  title: WA MT\n  status: complete\n", n_edi=1)
    _mk(sroot, "wamt-b", name="WA B",  # a later member declares a VALID status
        collection="collection:\n  id: wamt\n  status: active\n", n_edi=1)
    c = edit.run_collections_job(sroot)["collections"]["wamt"]
    assert c["status"] == "active", c["status"]


def test_out_of_vocab_status_with_no_valid_member_is_none(tmp_path):
    """When NO member declares a valid status, the rollup status is None (the invalid value is never
    surfaced) — the other half of the in-fold drop."""
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "m1", name="M1", collection="collection:\n  id: wamt\n  status: ongoing\n", n_edi=1)
    c = edit.run_collections_job(sroot)["collections"]["wamt"]
    assert c["status"] is None, c["status"]


# --------------------------------------------------------------------------------------------------
# F2 (D5-B) — membership predicate is the engine's truthiness. FAILS IF a falsy id (unquoted 0/False)
# forms a collection: such a member must be dropped exactly as the engine drops it.
# --------------------------------------------------------------------------------------------------
def test_falsy_id_member_is_excluded(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "zero", name="Zero", collection="collection:\n  id: 0\n  title: Zero\n", n_edi=1)
    _mk(sroot, "real", name="Real", collection="collection:\n  id: capricorn\n", n_edi=1)
    out = edit.run_collections_job(sroot)["collections"]
    assert list(out) == ["capricorn"], list(out)
    assert 0 not in out and "0" not in out


# --------------------------------------------------------------------------------------------------
# F3 (D5-B) — malformed-YAML resilience (NEGATIVE CONTROL). FAILS IF one unparseable survey.yaml blanks
# the WHOLE projection: a malformed member is dropped and the OTHER collections still project (mirrors
# build_portal.py:810-817 dropping just the one bad package). Red-proven: catching only OSError before
# let the ruamel YAMLError propagate to {ok:False} and the gateway's empty state.
# --------------------------------------------------------------------------------------------------
def test_one_malformed_survey_does_not_blank_the_projection(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "good-a", name="Good A", collection=_AUSLAMP_FULL, n_edi=2)
    _mk(sroot, "good-b", name="Good B",
        collection="collection:\n  id: capricorn\n  title: Capricorn\n", n_edi=1)
    # A structurally broken YAML (unclosed flow + stray colons) — ruamel raises a YAMLError on load.
    _mk(sroot, "broken", name="Broken", collection=None,
        raw="name: [unclosed\n  : : :\nbad indent here\n")
    res = edit.run_collections_job(sroot)
    assert res["ok"] is True
    assert set(res["collections"]) == {"auslamp", "capricorn"}, set(res["collections"])


def test_non_mapping_survey_yaml_is_dropped(tmp_path):
    """A survey.yaml that parses to a non-mapping (a bare scalar / list) is dropped like the engine
    drops it (build_portal.py:1966-1969), not crashed on."""
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "scalar", name="S", collection=None, raw="just-a-scalar\n")
    _mk(sroot, "real", name="R", collection="collection:\n  id: capricorn\n", n_edi=1)
    res = edit.run_collections_job(sroot)
    assert res["ok"] is True and list(res["collections"]) == ["capricorn"]


# --------------------------------------------------------------------------------------------------
# F5 (D5-B) — PUBLISHED-SOURCE behaviour (documents the intentional non-served semantics). A member
# carrying a collection.id but ZERO EDIs (a build-dropped-class survey) IS included in the console
# rollup — the console reads the published survey.yaml, not the served post-gate build. FAILS IF the
# runner silently drops a 0-station member (which would make it a served mirror, not the edit truth).
# --------------------------------------------------------------------------------------------------
def test_zero_station_member_is_included_published_source(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "empty-member", name="Empty",
        collection="collection:\n  id: auslamp\n  title: AusLAMP\n", n_edi=0)
    _mk(sroot, "full-member", name="Full",
        collection="collection:\n  id: auslamp\n", n_edi=5)
    c = edit.run_collections_job(sroot)["collections"]["auslamp"]
    assert c["n_surveys"] == 2, c["n_surveys"]
    by_slug = {m["slug"]: m["n_stations"] for m in c["members"]}
    assert by_slug == {"empty-member": 0, "full-member": 5}, by_slug
    assert c["n_stations"] == 5, c["n_stations"]


# --------------------------------------------------------------------------------------------------
# Pin 3 — DIVERGENCE DETECTION (both directions, mutation-provable). FAILS IF a real divergence is
# MISSED (disagreement -> names both members + both values) OR falsely reported on agreement.
# --------------------------------------------------------------------------------------------------
def test_divergence_detected_when_members_disagree(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "m1", name="M1",
        collection="collection:\n  id: auslamp\n  title: AusLAMP\n  status: active\n", n_edi=1)
    _mk(sroot, "m2", name="M2",
        collection="collection:\n  id: auslamp\n  title: AusLAMP Project\n  status: active\n", n_edi=1)
    div = edit.run_collections_job(sroot)["collections"]["auslamp"]["divergence"]
    assert "title" in div, div
    values = {b["value"]: sorted(b["members"]) for b in div["title"]}
    assert values == {"AusLAMP": ["m1"], "AusLAMP Project": ["m2"]}, values
    # status AGREES across members (active/active) -> must NOT be reported (the false-positive guard).
    assert "status" not in div, div


def test_no_divergence_when_all_members_agree(tmp_path):
    """FAILS IF divergence is falsely reported when every declared value agrees (an absent field on one
    member is NOT a disagreement — it inherits the rollup value)."""
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "m1", name="M1", collection=_AUSLAMP_FULL, n_edi=1)
    _mk(sroot, "m2", name="M2",
        collection="collection:\n  id: auslamp\n  title: AusLAMP\n", n_edi=1)  # omits the rest
    div = edit.run_collections_job(sroot)["collections"]["auslamp"]["divergence"]
    assert div == {}, div


# --------------------------------------------------------------------------------------------------
# Pin 4 — SLUG-JOIN (the labels-vs-slugs trap, hotfix #33). FAILS IF membership is joined by the
# display label rather than the survey slug: two members sharing a NAME but with distinct slugs must
# BOTH be members (n_surveys == 2). A label-keyed join would collapse them to one.
# --------------------------------------------------------------------------------------------------
def test_membership_resolves_by_slug_not_label(tmp_path):
    sroot = tmp_path / "surveys-live"
    # Same display name, different slugs — the exact shape a label-join silently collapses.
    _mk(sroot, "auslamp-sa-2014", name="AusLAMP",
        collection="collection:\n  id: auslamp\n  title: AusLAMP\n", n_edi=5)
    _mk(sroot, "auslamp-vic-2015", name="AusLAMP",
        collection="collection:\n  id: auslamp\n  title: AusLAMP\n", n_edi=7)
    c = edit.run_collections_job(sroot)["collections"]["auslamp"]
    assert c["n_surveys"] == 2, c["n_surveys"]
    slugs = sorted(m["slug"] for m in c["members"])
    assert slugs == ["auslamp-sa-2014", "auslamp-vic-2015"], slugs
    # And station counts sum per SLUG (5 + 7), not deduped to one label's count.
    assert c["n_stations"] == 12, c["n_stations"]


# --------------------------------------------------------------------------------------------------
# Pin 5 — n_stations. Per-member station count is its EDI-file count (a directory listing); the
# collection total is the SUM. FAILS IF either miscounts.
# --------------------------------------------------------------------------------------------------
def test_n_stations_is_edi_count_summed(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "m1", name="M1", collection="collection:\n  id: auslamp\n", n_edi=3)
    _mk(sroot, "m2", name="M2", collection="collection:\n  id: auslamp\n", n_edi=8)
    c = edit.run_collections_job(sroot)["collections"]["auslamp"]
    by_slug = {m["slug"]: m["n_stations"] for m in c["members"]}
    assert by_slug == {"m1": 3, "m2": 8}, by_slug
    assert c["n_stations"] == 11, c["n_stations"]


# --------------------------------------------------------------------------------------------------
# Pin 6 — READ-ONLY. FAILS IF the job writes/mutates anything: the surveys tree is byte-identical (same
# paths, same content hashes, no new files) after the job runs.
# --------------------------------------------------------------------------------------------------
def _tree_snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_collections_job_mutates_nothing(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "m1", name="M1", collection=_AUSLAMP_FULL, n_edi=2)
    _mk(sroot, "m2", name="M2", collection="collection:\n  id: capricorn\n  title: Capricorn\n", n_edi=1)
    before = _tree_snapshot(sroot)
    edit.run_collections_job(sroot)
    after = _tree_snapshot(sroot)
    assert after == before, "the collections read-job changed the surveys tree"


# --------------------------------------------------------------------------------------------------
# Pin 10 — BACKWARDS-COMPAT. A corpus with NO collection blocks rolls up to the empty projection
# (matches the engine's collections.json == {}). FAILS IF an empty corpus errors or invents a group.
# --------------------------------------------------------------------------------------------------
def test_zero_collection_corpus_is_empty(tmp_path):
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "lone-a", name="Lone A", collection=None, n_edi=1)
    _mk(sroot, "lone-b", name="Lone B", collection=None, n_edi=1)
    res = edit.run_collections_job(sroot)
    assert res == {"ok": True, "collections": {}, "near_duplicates": []}, res


def test_missing_surveys_dir_is_empty(tmp_path):
    """A surveys-live with no surveys/ dir at all (fresh box) returns the empty projection, not a
    crash."""
    res = edit.run_collections_job(tmp_path / "surveys-live")
    assert res == {"ok": True, "collections": {}, "near_duplicates": []}, res


def test_collections_job_dispatches_without_a_slug(tmp_path):
    """The whole-corpus job carries NO slug; _dispatch_edit must route it BEFORE the per-survey slug
    validation (which would reject the empty slug). FAILS IF the collections branch regresses behind the
    slug guard."""
    from gateway.runner.runner import RunnerConfig
    sroot = tmp_path / "surveys-live"
    _mk(sroot, "m1", name="M1", collection=_AUSLAMP_FULL, n_edi=1)
    cfg = RunnerConfig(incoming_dir=tmp_path / "in", quarantine_dir=tmp_path / "q",
                       jobs_dir=tmp_path / "jobs", validator_path="", surveys_root=sroot)
    res = edit._dispatch_edit(cfg, {"kind": "collections"}, tmp_path / "jobs" / "edit" / "scratch" / "t")
    assert res["ok"] is True and "auslamp" in res["collections"]
