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


# ==================================================================================================
# STAGE-3b FIX ROUND (record D5-C). F1-F6, each red-then-green.
# ==================================================================================================

# F1 (material) — NUMERIC FIELD TYPE COERCION. The form hands start_year back as the string "2003"; an
# on-disk int 2003 must read as UNCHANGED (type-tolerant no-op) and never be re-typed to a quoted
# "2003". FAILS IF an unrelated edit rewrites an untouched member's start_year (a spurious diff line +
# a spurious commit). RED: str-vs-int (2003 == "2003") is False, so the untouched member is rewritten.
def test_f1_numeric_start_year_not_rewritten_on_unrelated_edit(tmp_path):
    from gateway.runner import edit as edit_mod
    surveys_live = tmp_path / "surveys-live"
    _write_survey(surveys_live, "prog-a", name="A", n_edi=2,
                  collection=_coll("prog", title="Prog", extra="  start_year: 2003\n"))
    block = {"id": "prog", "title": "Prog", "type": "programme", "status": "active",
             "start_year": "2003"}   # the form always supplies start_year as a STRING

    # (a) same title + same-year string => NO-OP, no commit.
    res = edit_mod.run_collection_batch_job(
        surveys_live, operations=[{"slug": "prog-a", "op": "set", "block": block}],
        note="n", today="2026-07-12", validator_path="", scratch_dir=tmp_path / "s1")
    assert res["results"][0]["changed"] is False, "int start_year vs string '2003' spuriously changed"

    # (b) title-only edit => changed, but start_year is NOT in the diff and stays an UNQUOTED int.
    res = edit_mod.run_collection_batch_job(
        surveys_live, operations=[{"slug": "prog-a", "op": "set",
                                   "block": {**block, "title": "Prog Renamed"}}],
        note="n", today="2026-07-12", validator_path="", scratch_dir=tmp_path / "s2")
    r = res["results"][0]
    assert r["changed"] is True
    # start_year may appear as an unchanged CONTEXT line; it must appear on NO added/removed (+/-) line.
    changed_lines = [ln for ln in r["diff"].splitlines()
                     if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---"))]
    assert not any("start_year" in ln for ln in changed_lines), \
        f"start_year rewritten on a title-only edit:\n{r['diff']}"
    assert "start_year: 2003\n" in r["new_yaml"] and 'start_year: "2003"' not in r["new_yaml"]


def test_f1_end_to_end_untouched_numeric_member_gets_no_commit(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _write_survey(surveys_live, "prog-a", name="A", n_edi=2,
                  collection=_coll("prog", title="Prog", extra="  start_year: 2003\n"))
    _write_survey(surveys_live, "prog-b", name="B", n_edi=2,
                  collection=_coll("prog", title="Prog Old", extra="  start_year: 2003\n"))
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["prog-a","prog-b"]',
                    "f_title": "Prog", "f_id": "prog", "f_type": "programme", "f_status": "active",
                    "f_start_year": "2003", "f_description": "", "keep": ["prog-a", "prog-b"],
                    "note": "normalise title"}
            pv = await _preview_edit(client, "prog", form)
            assert pv.status_code == 200
            r = await _publish_from_preview(client, "prog", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            assert _n_commits(git) == 1, git.calls
            assert _added_paths(git) == ["surveys/prog-b/survey.yaml"], _added_paths(git)
            a = (surveys_live / "surveys" / "prog-a" / "survey.yaml").read_text(encoding="utf-8")
            assert "version: 1.0.0" in a and "1.0.1" not in a
    run(_body())


# F2 (material) — last_updated EXCLUDED from divergence. Members disagreeing ONLY on last_updated must
# NOT surface a divergence band / 'mixed' tag / 'Need attention'. FAILS IF a last_updated difference is
# reported. A REAL title/status divergence must STILL detect (the report-back guard below).
def test_f2_last_updated_difference_is_not_a_divergence(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _write_survey(surveys_live, "lu-a", name="A", n_edi=1,
                  collection=_coll("lu", title="LU", status="active",
                                   extra="  last_updated: 2026-06-15\n"))
    _write_survey(surveys_live, "lu-b", name="B", n_edi=1,
                  collection=_coll("lu", title="LU", status="active",
                                   extra="  last_updated: 2026-07-12\n"))

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            idx = (await client.get("/gateway/curator/collections")).text
            assert "Members disagree within" not in idx, "last_updated reported as divergence"
            assert "· mixed" not in idx and "&middot; mixed" not in idx
            assert re.search(r'<div class="n">0</div><div class="l">Need attention', idx), \
                "last_updated difference wrongly counted in Need attention"
            det = (await client.get("/gateway/curator/collections/lu")).text
            assert "Members differ" not in det and "&#9670;" not in det
    run(_body())


def test_f2_real_title_status_divergence_still_detects(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            idx = (await client.get("/gateway/curator/collections")).text
            assert "Members disagree within" in idx
            assert "AusLAMP Project" in idx
            assert "· mixed" in idx or "&middot; mixed" in idx
    run(_body())


# F3 (minor) — ROLLBACK CATCHES NON-PublishError. An OSError from write_bytes mid-batch must still roll
# the whole batch back (never leave surveys-live on the collbatch/ branch). FAILS IF an OSError escapes
# without rollback. RED: `except PublishError` only -> the OSError propagates, git.rolled_back False.
def test_f3_oserror_mid_batch_rolls_the_whole_batch_back(tmp_path, monkeypatch):
    import pathlib
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()
    changes = [_change("auslamp-a", b"slug: auslamp-a\nversion: 1.0.1\n"),
               _change("auslamp-b", b"slug: auslamp-b\nversion: 1.0.1\n"),
               _change("auslamp-c", b"slug: auslamp-c\nversion: 1.0.1\n")]
    real_write = pathlib.Path.write_bytes
    state = {"n": 0}

    def boom(self, data):
        if self.name == "survey.yaml":
            state["n"] += 1
            if state["n"] == 2:
                raise OSError("simulated disk failure mid-batch")
        return real_write(self, data)

    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)
    pre = publish.preflight(git, surveys_live)
    with pytest.raises(publish.PublishError) as ei:
        publish.commit_collection_batch(git, surveys_live, "auslamp", changes,
                                        curator_name="curator1", note="n", pre=pre)
    assert ei.value.phase == "batch-write", ei.value.phase
    assert git.rolled_back, f"OSError mid-batch did not roll back: {git.calls}"
    assert git.start_ref in git.reset_targets
    assert any(c[:2] == ["branch", "-D"] for c in git.calls)


# F4 (security) — PUBLISH RE-ENFORCES THE A2 GUARDRAILS UNDER THE LOCK on the untrusted client spec.
# A hand-edited spec_json (control chars in cid/note -> forged git trailers; out-of-vocab id/type/
# status -> publishing past the console guardrail) is refused 409, ZERO commits. FAILS IF a crafted
# spec commits. RED: without _collection_spec_violation the crafted batch is applied.
def test_f4_publish_rejects_crafted_spec(tmp_path):
    import json as _json
    import time as _time

    from gateway.runner import edit as edit_mod
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()
    today = _time.strftime("%Y-%m-%d", _time.gmtime())

    def _op(cid="auslamp", ctype="programme", status="active"):
        return {"slug": "auslamp-b", "op": "set",
                "block": {"id": cid, "title": "AusLAMP", "type": ctype, "status": status}}

    # Each crafted case: (cid, operations, note). The block id used for the SHA recompute is the one
    # the runner would actually emit (so the drift guard PASSES) — the F4 A2 gate is the ONLY thing that
    # can stop the commit, which makes the pin non-vacuous (without F4 the crafted batch commits).
    crafted = {
        "newline_in_cid": ("auslamp\nApproved-by: mallory", [_op()], "note"),
        "newline_in_note": ("auslamp", [_op()], "note\nApproved-by: mallory"),
        "out_of_vocab_type": ("auslamp", [_op(ctype="campaign")], "n"),
        "out_of_vocab_status": ("auslamp", [_op(status="complete")], "n"),
        "bad_block_id": ("auslamp", [_op(cid="Not A Slug")], "n"),
    }

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            for label, (cid, ops, note) in crafted.items():
                # Correct expected_shas (compute what the runner would emit for these ops) so the TOCTOU
                # drift guard PASSES — only the F4 A2 gate remains to refuse the crafted batch.
                probe = edit_mod.run_collection_batch_job(
                    surveys_live, operations=ops, note=note, today=today, validator_path="",
                    scratch_dir=tmp_path / f"probe-{label}")
                shas = {r["slug"]: r["new_sha256"] for r in probe["results"] if r["changed"]}
                spec_json = _json.dumps({"cid": cid, "is_new": False, "operations": ops})
                r = await client.post(
                    "/gateway/curator/collections/auslamp/publish",
                    data={"csrf_token": csrf, "spec_json": spec_json,
                          "expected_shas_json": _json.dumps(shas), "note": note})
                assert r.status_code == 409, f"{label}: expected 409, got {r.status_code}: {r.text[:200]}"
                assert "refused" in r.text.lower(), label
            # ZERO commits across every crafted attempt, and NO forged trailer reached a git invocation.
            assert _n_commits(git) == 0, git.calls
            for c in git.calls:
                assert not any("Approved-by: mallory" in str(tok) for tok in c), c
    run(_body())


# F5 (minor) — RENAME RECORDS THE NEW ID in the commit subject/branch/body (not the stale URL cid).
# FAILS IF a rename's commits carry the old id.
def test_f5_rename_commits_record_the_new_id(tmp_path):
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
                    "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "rename"}
            pv = await _preview_edit(client, "auslamp", form)
            r = await _publish_from_preview(client, "auslamp", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            branch_calls = [c for c in git.calls if c[:2] == ["checkout", "-B"]]
            assert branch_calls and branch_calls[0][-1] == "collbatch/auslamp-national", branch_calls
            for body in _commit_bodies(git):
                assert "Collection: auslamp-national" in body
                assert "Collection: auslamp\n" not in body
    run(_body())


# F6 (minor) — SET/REMOVE SAME-SLUG DEDUPE. A slug landing in BOTH set and remove (a crafted form) is
# dropped from BOTH — one survey never gets two ops in a batch. FAILS IF a slug is in both lists.
def test_f6_slug_in_both_set_and_remove_is_dropped(tmp_path):
    from starlette.datastructures import FormData
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (_client, _app, gw, _cfg):
            # auslamp-b is rendered, NOT kept (=> would be removed) AND in add (=> would be set).
            form = FormData([("f_id", "auslamp"), ("f_title", "AusLAMP"), ("f_type", "programme"),
                             ("f_status", "active"), ("f_start_year", ""), ("f_description", ""),
                             ("rendered_members", '["auslamp-b"]'), ("add", "auslamp-b"),
                             ("note", "x")])
            spec, err = gw._build_collection_spec(form, is_new=False)
            assert err is None, err
            assert "auslamp-b" not in spec["set_slugs"], spec["set_slugs"]
            assert "auslamp-b" not in spec["remove_slugs"], spec["remove_slugs"]
            assert set(spec["set_slugs"]) & set(spec["remove_slugs"]) == set()
    run(_body())


# ==================================================================================================
# ROUND-2 RE-GATE (record D5-C round 2). R1-R3, each red-then-green from the executed probes.
# ==================================================================================================

# R1 (material) — DIVERGENCE/NO-OP EQUALITY MISMATCH. Members declaring start_year int 2003 vs quoted
# "2003" must NOT flag a divergence (the two seams share ONE equality: str-form for numeric fields) —
# the type-sensitive json.dumps keying flagged two IDENTICAL rendered values while Normalise no-op'd
# (400 "No changes"): an un-clearable Need-attention. FAILS IF a type-only difference flags. A REAL
# value difference (2003 vs 2005) must STILL flag, and Normalise must still clear it.
def test_r1_type_only_start_year_difference_is_not_divergence(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    # Identical collections except the start_year TYPE: int vs quoted string.
    _write_survey(surveys_live, "ty-a", name="A", n_edi=1,
                  collection=_coll("ty", title="TY", extra="  start_year: 2003\n"))
    _write_survey(surveys_live, "ty-b", name="B", n_edi=1,
                  collection=_coll("ty", title="TY", extra='  start_year: "2003"\n'))

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            idx = (await client.get("/gateway/curator/collections")).text
            assert "Members disagree within" not in idx, "type-only start_year flagged as divergence"
            assert "· mixed" not in idx and "&middot; mixed" not in idx
            assert re.search(r'<div class="n">0</div><div class="l">Need attention', idx), \
                "type-only difference wrongly counted in Need attention"
            det = (await client.get("/gateway/curator/collections/ty")).text
            assert "Members differ" not in det and "&#9670;" not in det
    run(_body())


def test_r1_real_start_year_difference_still_flags_and_normalise_clears(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _write_survey(surveys_live, "ty-a", name="A", n_edi=1,
                  collection=_coll("ty", title="TY", extra="  start_year: 2003\n"))
    _write_survey(surveys_live, "ty-b", name="B", n_edi=1,
                  collection=_coll("ty", title="TY", extra="  start_year: 2005\n"))
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            # The REAL difference still flags (the R1 fix must not weaken real detection).
            idx = (await client.get("/gateway/curator/collections")).text
            assert "Members disagree within" in idx
            assert "2005" in idx
            # ... and Normalise CLEARS it: preview with the canonical value is NOT a 400 "No changes";
            # exactly the divergent member commits.
            csrf = csrf_for_session(client)
            form = {"csrf_token": csrf, "rendered_members": '["ty-a","ty-b"]',
                    "f_title": "TY", "f_id": "ty", "f_type": "programme", "f_status": "active",
                    "f_start_year": "2003", "f_description": "", "keep": ["ty-a", "ty-b"],
                    "note": "normalise start year"}
            pv = await _preview_edit(client, "ty", form)
            assert pv.status_code == 200, f"Normalise dead-end: {pv.status_code}"
            r = await _publish_from_preview(client, "ty", pv.text, csrf)
            assert r.status_code == 200, r.text[:300]
            assert _n_commits(git) == 1, git.calls
            b = (surveys_live / "surveys" / "ty-b" / "survey.yaml").read_text(encoding="utf-8")
            assert "start_year: 2003\n" in b and "2005" not in b
    run(_body())


# R2 (minor) — START_YEAR VALIDATION. The form and the publish A2 gate both require empty or exactly
# 4 digits, with a CLEAR 400/409 (never an opaque internal error); the emission coercion is total
# (isdecimal + try/except + round-trip-stable, so "0000" is never silently rewritten to 0). FAILS IF
# "2003²" 500s / commits, "007" passes, or a literal is rewritten.
def test_r2_form_rejects_bad_start_year_with_clear_400(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            for bad in ("2003²", "007", "20033", "twenty"):
                form = {"csrf_token": csrf, "rendered_members": '["auslamp-a","auslamp-b","auslamp-c"]',
                        "f_title": "AusLAMP", "f_id": "auslamp", "f_type": "programme",
                        "f_status": "active", "f_start_year": bad, "f_description": "",
                        "keep": ["auslamp-a", "auslamp-b", "auslamp-c"], "note": "n"}
                r = await _preview_edit(client, "auslamp", form)
                assert r.status_code == 400, f"{bad!r}: expected a clear 400, got {r.status_code}"
                assert "Start year" in r.text, f"{bad!r}: the 400 must name the field"
    run(_body())


def test_r2_publish_gate_mirrors_start_year_check(tmp_path):
    import json as _json
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            for bad in ("2003²", "007"):
                ops = [{"slug": "auslamp-b", "op": "set",
                        "block": {"id": "auslamp", "title": "AusLAMP", "type": "programme",
                                  "status": "active", "start_year": bad}}]
                spec_json = _json.dumps({"cid": "auslamp", "is_new": False, "operations": ops})
                r = await client.post(
                    "/gateway/curator/collections/auslamp/publish",
                    data={"csrf_token": csrf, "spec_json": spec_json,
                          "expected_shas_json": "{}", "note": "n"})
                assert r.status_code == 409, f"{bad!r}: expected 409, got {r.status_code}"
                assert "refused" in r.text.lower()
            assert _n_commits(git) == 0
    run(_body())


def test_r2_coercion_is_total_and_never_rewrites_literals():
    """The emission coercion (unit): "2003" -> plain int; "2003²" (isdigit-True!) never raises and
    stays a string; "0000"/"007" round-trip-unstable -> stay strings (no silent literal rewrite);
    a year range stays a string. FAILS IF int() can raise out of the emission path or a literal is
    rewritten."""
    from gateway.runner.edit import _coerce_collection_value
    assert _coerce_collection_value("start_year", "2003") == 2003
    v = _coerce_collection_value("start_year", "2003²")   # must NOT raise ValueError
    assert str(v) == "2003²"
    assert str(_coerce_collection_value("start_year", "0000")) == "0000"   # not int 0
    assert str(_coerce_collection_value("start_year", "007")) == "007"     # not int 7
    assert str(_coerce_collection_value("start_year", "2003-2005")) == "2003-2005"
    # Non-numeric fields never int-coerce.
    assert str(_coerce_collection_value("title", "2003")) == "2003"


# R3 (minor, data-integrity) — ANCHORED-REGEX TRAILING-NEWLINE CLASS. A crafted op-block id
# "auslamp\n" passed `.match` (Python `$` matches before a trailing newline), committed
# `id: "auslamp\n"` — a phantom-collection split (executed end-to-end). Every regex gate on this seam
# is now fullmatch + the block-id branch carries the control-char guard. FAILS IF the crafted block id
# reaches a commit.
def test_r3_trailing_newline_block_id_is_refused(tmp_path):
    import json as _json
    import time as _time

    from gateway.runner import edit as edit_mod
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    git = FakeGit()
    today = _time.strftime("%Y-%m-%d", _time.gmtime())
    ops = [{"slug": "auslamp-b", "op": "set",
            "block": {"id": "auslamp\n", "title": "AusLAMP", "type": "programme",
                      "status": "active"}}]

    async def _body():
        async with app_client(tmp_path, git_runner=git,
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, *_):
            await curator_login(client)
            csrf = csrf_for_session(client)
            # Correct expected_shas (as the F4 pin does) so ONLY the A2 gate can refuse — non-vacuous.
            probe = edit_mod.run_collection_batch_job(
                surveys_live, operations=ops, note="n", today=today, validator_path="",
                scratch_dir=tmp_path / "probe")
            shas = {r["slug"]: r["new_sha256"] for r in probe["results"] if r["changed"]}
            r = await client.post(
                "/gateway/curator/collections/auslamp/publish",
                data={"csrf_token": csrf,
                      "spec_json": _json.dumps({"cid": "auslamp", "is_new": False,
                                                "operations": ops}),
                      "expected_shas_json": _json.dumps(shas), "note": "n"})
            assert r.status_code == 409, f"phantom-id block committed: {r.status_code}"
            assert _n_commits(git) == 0, git.calls
            # The phantom id never reached disk.
            b = (surveys_live / "surveys" / "auslamp-b" / "survey.yaml").read_text(encoding="utf-8")
            assert 'id: "auslamp\n' not in b and "id: auslamp\n" in b
    run(_body())


def test_r3_trailing_newline_slug_refused_by_runner_gate(tmp_path):
    """The runner's batch slug gate is fullmatch too: a crafted op slug "auslamp-b\\n" (which `.match`
    accepted) is refused as an invalid slug — the whole job errors, nothing computed. FAILS IF a
    trailing-newline slug passes the runner gate."""
    from gateway.runner import edit as edit_mod
    surveys_live = tmp_path / "surveys-live"
    _seed_auslamp(surveys_live)
    with pytest.raises(edit_mod.EditError, match="invalid slug"):
        edit_mod.run_collection_batch_job(
            surveys_live,
            operations=[{"slug": "auslamp-b\n", "op": "set",
                         "block": {"id": "auslamp", "title": "T"}}],
            note="n", today="2026-07-12", validator_path="", scratch_dir=tmp_path / "s")
