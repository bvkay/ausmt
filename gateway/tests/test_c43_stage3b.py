"""C43 Stage 3b — the collections batch editor WRITE path (record D5-A A6, D13 pins; Invariant 10).

Every write-path pin states its failure criterion and is mutation-proof (shown able to fail). The
gate-scrutinised four — atomicity (#1), rollback (#2), single-flight/re-validate-under-lock (#3),
diff-minimality/N-commits (#4) — are proven RED-then-GREEN (the RED capture is documented in the
lane report; each assertion below genuinely fails if its gate is removed).

Two seams (conftest): the in-process edit runner (the runner's REAL job dispatch, no yaml in the
gateway process) and FakeGit (an in-memory surveys-live model that RAISES on any unmodeled verb and
tracks branch/ref/rollback so the atomicity + rollback guarantees are observable without real git).
The real-git lane (test_publish_real_git.py) proves byte-level diff-minimality + byte-restoration.
"""
from __future__ import annotations

import hashlib
import re

import pytest

from gateway import publish
from gateway.tests.conftest import (
    FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    validator_fail, validator_pass,
)


# --------------------------------------------------------------------------------------------------
# Fixtures: a real surveys-live corpus of collection-bearing survey packages.
# --------------------------------------------------------------------------------------------------
def _write_survey(surveys_live, slug, *, name, collection=None, version="1.0.0", n_edi=1):
    d = surveys_live / "surveys" / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True, exist_ok=True)
    for i in range(n_edi):
        (d / "transfer_functions" / "edi" / f"S{i:02d}.edi").write_text(
            ">HEAD\n>END\n", encoding="utf-8")
    body = f"slug: {slug}\nname: \"{name}\"\nversion: {version}\ncountry: Australia\n"
    if collection:
        body += collection
    with open(d / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    return d


def _coll(cid, *, title=None, ctype="programme", status="active", extra=""):
    out = f"collection:\n  id: {cid}\n"
    if title is not None:
        out += f"  title: {title}\n"
    if ctype is not None:
        out += f"  type: {ctype}\n"
    if status is not None:
        out += f"  status: {status}\n"
    return out + extra


def _seed_auslamp(surveys_live):
    """A 3-member auslamp with a title divergence on 2 members + a clean capricorn + a collection-less
    loner (a candidate). auslamp-a declares the canonical title 'AusLAMP'; -b and -c diverge."""
    _write_survey(surveys_live, "auslamp-a", name="A", n_edi=3,
                  collection=_coll("auslamp", title="AusLAMP"))
    _write_survey(surveys_live, "auslamp-b", name="B", n_edi=2,
                  collection=_coll("auslamp", title="AusLAMP Project"))
    _write_survey(surveys_live, "auslamp-c", name="C", n_edi=4,
                  collection=_coll("auslamp", title="AusLAMP Project"))
    _write_survey(surveys_live, "capricorn-1", name="Cap", n_edi=5,
                  collection=_coll("capricorn", title="Capricorn", status="completed"))
    _write_survey(surveys_live, "loner", name="Loner", collection=None, n_edi=6)


def _n_commits(git: FakeGit) -> int:
    return sum(1 for c in git.calls if "commit" in c)


def _commit_bodies(git: FakeGit) -> list[str]:
    """The -m BODY of every commit invocation (the second -m), for the shared-note assertion."""
    bodies = []
    for c in git.calls:
        if "commit" in c:
            ms = [c[i + 1] for i, tok in enumerate(c) if tok == "-m" and i + 1 < len(c)]
            if len(ms) >= 2:
                bodies.append(ms[1])
    return bodies


def _added_paths(git: FakeGit) -> list[str]:
    """Every `git add -- <path>` target, to assert per-survey scoping (diff-minimality)."""
    paths = []
    for c in git.calls:
        if c and c[0] == "add":
            paths += [a for a in c[2:] if not a.startswith("-")]
    return paths


def _change(slug: str, new_yaml: bytes, *, has_fail=False, effect="edit") -> dict:
    return {"slug": slug, "new_yaml": new_yaml,
            "expected_sha256": hashlib.sha256(new_yaml).hexdigest(),
            "has_fail": has_fail, "effect": effect}


# --------------------------------------------------------------------------------------------------
# Editor-flow helpers (drive the real POST routes).
# --------------------------------------------------------------------------------------------------
def _grab(text: str, name: str) -> str:
    import html as _h
    m = re.search(r'name="%s" value="([^"]*)"' % re.escape(name), text)
    assert m, f"hidden field {name!r} not found in the preview page"
    return _h.unescape(m.group(1))


async def _preview_edit(client, cid, form):
    return await client.post(f"/gateway/curator/collections/{cid}/preview", data=form)


async def _publish_from_preview(client, cid, preview_text, csrf):
    return await client.post(
        f"/gateway/curator/collections/{cid}/publish",
        data={"csrf_token": csrf, "spec_json": _grab(preview_text, "spec_json"),
              "expected_shas_json": _grab(preview_text, "expected_shas_json"),
              "note": _grab(preview_text, "note")})


# ==================================================================================================
# PIN 1 — ATOMICITY (D13): a batch where one member's patched yaml FAILs validation lands ZERO
# commits, git status clean, HEAD unmoved. FAILS IF any commit lands when a member fails.
# RED (documented): without the validate-all-then-commit-all gate the whole batch (incl. the failing
# member) commits — `_n_commits` > 0, the assertion below goes red.
# ==================================================================================================
def test_atomicity_one_member_fail_zero_commits(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    originals = {s: (surveys_live / "surveys" / s / "survey.yaml").read_bytes()
                 for s in ("auslamp-a", "auslamp-b", "auslamp-c")}
    git = FakeGit()
    changes = [
        _change("auslamp-a", b"slug: auslamp-a\nversion: 1.0.1\n", has_fail=False),
        _change("auslamp-b", b"slug: auslamp-b\nversion: 1.0.1\n", has_fail=True),   # the failing one
        _change("auslamp-c", b"slug: auslamp-c\nversion: 1.0.1\n", has_fail=False),
    ]
    pre = publish.preflight(git, surveys_live)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_collection_batch(git, surveys_live, "auslamp", changes,
                                        curator_name="curator1", note="normalise", pre=pre)
    assert ei.value.phase == "validator", ei.value.phase
    assert "auslamp-b" in ei.value.message
    # ZERO commits landed (the load-bearing invariant).
    assert _n_commits(git) == 0, git.calls
    # HEAD unmoved; the checkout is untouched.
    assert git.head_ref == git.start_ref
    # The gate fires BEFORE any write, so NO passing member's bytes reached disk either.
    for slug, original in originals.items():
        assert (surveys_live / "surveys" / slug / "survey.yaml").read_bytes() == original


# ==================================================================================================
# PIN 2 — ROLLBACK (parametrised, like commit_metadata_edit's rollback tests): an injected git failure
# at each mutating step rolls surveys-live back (reset --hard to the pre ref + the branch deleted) and
# re-raises with the right phase — zero net commits. FAILS IF the rollback is skipped on any step.
# RED: without the `except PublishError: _rollback(...)` guard, `git.rolled_back` stays False.
# ==================================================================================================
@pytest.mark.parametrize("fail_verb,phase", [
    ("commit", "git-commit"), ("merge", "git-merge"), ("push", "git-push")])
def test_rollback_restores_on_git_failure_at_each_step(tmp_path, fail_verb, phase):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit(fail_on={fail_verb: (1, f"{fail_verb} boom")})
    changes = [_change("auslamp-b", b"slug: auslamp-b\nversion: 1.0.1\n"),
               _change("auslamp-c", b"slug: auslamp-c\nversion: 1.0.1\n")]
    pre = publish.preflight(git, surveys_live)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_collection_batch(git, surveys_live, "auslamp", changes,
                                        curator_name="curator1", note="n", pre=pre)
    assert ei.value.phase == phase
    # Rollback ran: reset --hard to the captured pre ref, and the batch branch was deleted.
    assert git.rolled_back, f"rollback did not reset to pre-state on {fail_verb} failure: {git.calls}"
    assert git.start_ref in git.reset_targets
    assert any(c[:2] == ["branch", "-D"] for c in git.calls), "batch branch not deleted on rollback"


# ==================================================================================================
# PIN 4 — N-COMMITS / ONE-NOTE / DIFF-MINIMALITY: a field edit to a 3-member collection where 2 members
# diverge produces EXACTLY 2 commits (one per CHANGED member, each version-bumped), sharing one note;
# the already-canonical member gets NO commit. Each commit's `git add` is scoped to that one survey.
# FAILS IF an unchanged member commits, the count is wrong, or the note is not shared.
# RED: without the runner's per-member `changed` gate, the canonical member also commits (count 3).
# ==================================================================================================
def test_field_edit_commits_only_changed_members_sharing_one_note(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)   # auslamp-a canonical 'AusLAMP'; -b,-c diverge 'AusLAMP Project'
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"],
                    "note": "normalise auslamp title"}
            pv = await _preview_edit(client, "auslamp", form)
            assert pv.status_code == 200
            # Only the 2 divergent members are in the batch (auslamp-a canonical -> not shown).
            assert "auslamp-b" in pv.text and "auslamp-c" in pv.text
            r = await _publish_from_preview(client, "auslamp", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            # EXACTLY 2 commits — the 2 changed members; the canonical member did NOT commit.
            assert _n_commits(git) == 2, git.calls
            # One SHARED note across every commit body.
            bodies = _commit_bodies(git)
            assert len(bodies) == 2
            assert all("normalise auslamp title" in b for b in bodies)
            # Per-survey diff-minimality: every `git add` names exactly one survey's survey.yaml.
            added = _added_paths(git)
            assert sorted(added) == ["surveys/auslamp-b/survey.yaml",
                                     "surveys/auslamp-c/survey.yaml"], added
            # The canonical member stayed byte-identical (no version bump, no commit).
            a = (surveys_live / "surveys" / "auslamp-a" / "survey.yaml").read_text(encoding="utf-8")
            assert "version: 1.0.0" in a and "1.0.1" not in a
            # The changed members were normalised + bumped.
            for slug in ("auslamp-b", "auslamp-c"):
                y = (surveys_live / "surveys" / slug / "survey.yaml").read_text(encoding="utf-8")
                assert "title: AusLAMP\n" in y and "AusLAMP Project" not in y
                assert "version: 1.0.1" in y
    run(_body())


def test_runner_diff_touches_only_collection_and_version_lines(tmp_path):
    """Byte-level diff-minimality (D13 pin 4) at the runner: a title normalise emits a diff whose ADDED/
    REMOVED lines are ONLY the collection title, the version, and the appended release_notes — never an
    untouched sibling (slug/name/country/type/status). FAILS IF the emitter rewrites untouched lines."""
    from gateway.runner import edit as edit_mod
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    res = edit_mod.run_collection_batch_job(
        surveys_live, operations=[{"slug": "auslamp-b", "op": "set",
                                   "block": {"id": "auslamp", "title": "AusLAMP", "type": "programme",
                                             "status": "active"}}],
        note="normalise", today="2026-07-12", validator_path="", scratch_dir=tmp_path / "scratch")
    r = res["results"][0]
    assert r["changed"] is True
    changed_lines = [ln[1:].strip() for ln in r["diff"].splitlines()
                     if (ln.startswith("+") or ln.startswith("-"))
                     and not ln.startswith(("+++", "---"))]
    # Every changed line is a title / version / release-note line — NOT slug/name/country/type/status.
    for ln in changed_lines:
        assert not ln.startswith(("slug:", "name:", "country:", "type:", "status:", "id:")), ln
    joined = "\n".join(changed_lines)
    assert "title:" in joined and "version:" in joined


# ==================================================================================================
# PIN 3 — SINGLE-FLIGHT / RE-VALIDATE-UNDER-LOCK (the C41 TOCTOU class): the publish/confirm RE-RUNS the
# batch under the lock and 409s a STALE preview — it does NOT trust the preview's bytes. FAILS IF a
# survey that changed between preview and publish is committed against the stale preview.
# RED: if publish committed the preview's carried bytes directly (no re-run + sha recheck), the drift
# below would land silently instead of 409ing.
# ==================================================================================================
def test_publish_refuses_stale_preview_after_underlying_change(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "normalise"}
            pv = await _preview_edit(client, "auslamp", form)
            assert pv.status_code == 200
            # A CONCURRENT edit lands on auslamp-b between preview and publish: bump its version so the
            # under-lock recompute yields DIFFERENT bytes (a new sha) than the preview captured.
            b = surveys_live / "surveys" / "auslamp-b" / "survey.yaml"
            b.write_text(b.read_text(encoding="utf-8").replace("version: 1.0.0", "version: 1.5.0"),
                         encoding="utf-8", newline="")
            r = await _publish_from_preview(client, "auslamp", pv.text, csrf)
            assert r.status_code == 409, r.status_code
            assert "stale" in r.text.lower()
            # Nothing committed — the drift was refused.
            assert _n_commits(git) == 0, git.calls
    run(_body())


def test_publish_re_runs_the_runner_under_lock_not_trusting_preview(tmp_path):
    """Prove the confirm RE-APPLIES under the lock (does not trust the preview): a counting edit-seam
    shows the collection_batch job is dispatched AGAIN at publish time. FAILS IF publish commits the
    preview's carried bytes without re-running the runner (the call count would not grow)."""
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()
    inner = inproc_edit_runner(surveys_live)
    calls = {"batch": 0}

    def counting(job):
        if job.get("kind") == "collection_batch":
            calls["batch"] += 1
        return inner(job)

    async def _body():
        async with app_client(tmp_path, git_runner=git, edit_runner=counting,
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "normalise"}
            pv = await _preview_edit(client, "auslamp", form)
            assert calls["batch"] == 1, "preview should run the batch job once"
            r = await _publish_from_preview(client, "auslamp", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            assert calls["batch"] == 2, "publish must RE-RUN the batch under the lock (re-validate)"
    run(_body())


# ==================================================================================================
# PIN 5 — MOVE SEMANTICS: adding a survey currently in collection X to Y rewrites its collection.id
# X->Y (one commit on it). FAILS IF the moved survey keeps its old id or is not committed.
# ==================================================================================================
def test_add_survey_from_another_collection_is_a_move(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # Open auslamp; keep its members; ADD capricorn-1 (currently in 'capricorn' -> a move).
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "add": ["capricorn-1"],
                    "note": "move capricorn survey into auslamp"}
            pv = await _preview_edit(client, "auslamp", form)
            assert pv.status_code == 200
            assert "capricorn-1" in pv.text and "moved" in pv.text
            r = await _publish_from_preview(client, "auslamp", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            moved = (surveys_live / "surveys" / "capricorn-1" / "survey.yaml").read_text(encoding="utf-8")
            assert "id: auslamp\n" in moved and "id: capricorn" not in moved
    run(_body())


# ==================================================================================================
# PIN 6 — CREATE-REQUIRES-MEMBER (record A5): a new collection with zero members is refused (400),
# nothing staged. FAILS IF a memberless create is accepted.
# ==================================================================================================
def test_create_with_zero_members_is_refused(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": "[]", "f_title": "New Programme",
                    "f_id": "new-programme", "f_type": "programme", "f_status": "active",
                    "f_start_year": "", "f_description": "", "note": "start it"}
            r = await client.post("/gateway/curator/collections/new/preview", data=form)
            assert r.status_code == 400, r.status_code
            assert "at least one member" in r.text.lower()
            assert _n_commits(git) == 0
    run(_body())


def test_create_with_members_commits_the_block(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": "[]", "f_title": "Delamerian",
                    "f_id": "delamerian", "f_type": "release", "f_status": "active",
                    "f_start_year": "2020", "f_description": "New release.", "add": ["loner"],
                    "note": "create delamerian"}
            pv = await client.post("/gateway/curator/collections/new/preview", data=form)
            assert pv.status_code == 200, pv.text[:300]
            assert "loner" in pv.text and "added" in pv.text
            r = await client.post(
                "/gateway/curator/collections/new/publish",
                data={"csrf_token": csrf, "spec_json": _grab(pv.text, "spec_json"),
                      "expected_shas_json": _grab(pv.text, "expected_shas_json"),
                      "note": _grab(pv.text, "note")})
            assert r.status_code == 200, r.text[:300]
            y = (surveys_live / "surveys" / "loner" / "survey.yaml").read_text(encoding="utf-8")
            assert "collection:" in y and "id: delamerian\n" in y and "type: release\n" in y
            assert _n_commits(git) == 1
    run(_body())


# ==================================================================================================
# PIN 7 — RENAME FAN-OUT: changing the id rewrites EVERY member's collection.id (N commits). FAILS IF
# any member keeps the old id or a member is missed.
# ==================================================================================================
def test_rename_id_rewrites_all_members(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp-national", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "rename to national"}
            pv = await _preview_edit(client, "auslamp", form)
            assert pv.status_code == 200
            r = await _publish_from_preview(client, "auslamp", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            # All 3 members rewritten to the new id => 3 commits.
            assert _n_commits(git) == 3, git.calls
            for slug in ("auslamp-a", "auslamp-b", "auslamp-c"):
                y = (surveys_live / "surveys" / slug / "survey.yaml").read_text(encoding="utf-8")
                assert "id: auslamp-national\n" in y and "id: auslamp\n" not in y
    run(_body())


# ==================================================================================================
# PIN 8 — VALIDATOR-GATE: a preview whose patched result FAILs validation shows FAIL + NO publish
# button; a forced publish is caught server-side (409). Reuses report_has_fail. FAILS IF a FAIL slips
# to a commit.
# ==================================================================================================
def test_validator_fail_blocks_preview_and_publish(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()
    # FAIL only auslamp-c's patched package; the others PASS.
    def per_survey(package_root):
        return validator_fail(package_root) if package_root.name == "auslamp-c" \
            else validator_pass(package_root)

    async def _body():
        async with app_client(
                tmp_path, git_runner=git,
                edit_runner=inproc_edit_runner(surveys_live, validator_override=per_survey),
                surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "normalise"}
            pv = await _preview_edit(client, "auslamp", form)
            assert pv.status_code == 200
            assert "FAIL" in pv.text and "cannot be published" in pv.text
            # The preview offers NO publish form/button when a member fails (the UX gate).
            assert 'name="spec_json"' not in pv.text
            assert 'action="/gateway/curator/collections/auslamp/publish"' not in pv.text
            # Even a CRAFTED publish (payload built by hand, bypassing the withheld button) is caught
            # server-side by report_has_fail under the lock -> 409, ZERO commits. Build the exact
            # spec/shas the under-lock recompute produces (the sha is validation-independent).
            import json as _json
            import time as _time

            from gateway.runner import edit as edit_mod
            ops = [{"slug": s, "op": "set",
                    "block": {"id": "auslamp", "title": "AusLAMP", "type": "programme",
                              "status": "active"}}
                   for s in ("auslamp-a", "auslamp-b", "auslamp-c")]
            probe = edit_mod.run_collection_batch_job(
                surveys_live, operations=ops, note="normalise",
                today=_time.strftime("%Y-%m-%d", _time.gmtime()), validator_path="",
                scratch_dir=tmp_path / "probe")
            changed = [r for r in probe["results"] if r["changed"]]
            spec_json = _json.dumps({"cid": "auslamp", "is_new": False, "operations": ops})
            shas_json = _json.dumps({r["slug"]: r["new_sha256"] for r in changed})
            r = await client.post(
                "/gateway/curator/collections/auslamp/publish",
                data={"csrf_token": csrf, "spec_json": spec_json,
                      "expected_shas_json": shas_json, "note": "normalise"})
            assert r.status_code == 409, r.status_code
            assert _n_commits(git) == 0, git.calls
    run(_body())


# ==================================================================================================
# PIN 9 — CSP SWEEP on every new page (editor, create, preview, confirm): no inline <script>, no on*.
# FAILS IF any new surface ships inline JS.
# ==================================================================================================
def _assert_csp_clean(html: str) -> None:
    for m in re.finditer(r"<script\b[^>]*>", html):
        assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script> under the CSP: {m.group(0)}"
    handlers = re.findall(r"<[^>]*\son\w+\s*=", html)
    assert handlers == [], f"inline on* handlers under the CSP: {handlers}"
    assert 'src="/gateway/curator/ui.js"' in html


def test_all_new_pages_are_csp_clean(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            _assert_csp_clean((await client.get("/gateway/curator/collections/auslamp")).text)
            _assert_csp_clean((await client.get("/gateway/curator/collections/new")).text)
            form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                    "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                    "f_status": "active", "f_start_year": "", "f_description": "",
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "normalise"}
            pv = await _preview_edit(client, "auslamp", form)
            _assert_csp_clean(pv.text)   # the batch-diff confirm page
    run(_body())


# ==================================================================================================
# PIN 12 — SESSION / CSRF: every POST route rejects a missing session (401) and a bad CSRF (403).
# FAILS IF a write route is reachable without a valid session + CSRF.
# ==================================================================================================
def test_write_routes_require_session_and_csrf(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()
    routes = ("/gateway/curator/collections/auslamp/preview",
              "/gateway/curator/collections/auslamp/publish",
              "/gateway/curator/collections/new/preview",
              "/gateway/curator/collections/new/publish")

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            # No session at all -> 401 on every write route.
            for path in routes:
                r = await client.post(path, data={"csrf_token": "x"})
                assert r.status_code == 401, (path, r.status_code)
            # Logged in but a BAD csrf token -> 403.
            await curator_login(client)
            for path in routes:
                r = await client.post(path, data={"csrf_token": "wrong-token", "f_id": "auslamp",
                                                  "note": "x", "rendered_members": "[]"})
                assert r.status_code == 403, (path, r.status_code)
            assert _n_commits(git) == 0
    run(_body())
