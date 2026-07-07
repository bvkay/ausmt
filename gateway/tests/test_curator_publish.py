"""Approve -> commit-to-surveys-live flow + fail-closed rollback (design §5 v2/§8), with git faked
at its injected seam (no real git). v2 is COMMIT-AND-PUSH ONLY — NO rebuild: PUBLISHED means
committed+pushed, not served.

Guards under test, each with a stated failure criterion + proven-failing evidence:
- happy path: VALIDATED -> PUBLISHING -> PUBLISHED (committed); package staged into a temp surveys-
  live; commit author is the FIXED gateway identity; submitter email ABSENT from the commit.
- blocking-FAIL: an approve on a submission with a blocking FAIL => 409, no PUBLISHING, no git.
- pre-flight abort: a dirty surveys-live checkout => PUBLISH_FAILED, nothing staged (design §5 step 1).
- rollback on ANY git step (commit hook rejection, push rejection) => surveys-live restored, PUBLISH_
  FAILED. Rollback restores the CAPTURED branch/ref even when HEAD started on a stale submit branch.
- retry from PUBLISH_FAILED works for the git-only flow.
- confirm_overwrite parsed as an EXACT token (design §5.2 / review #7): "0" does NOT overwrite.
- reconciliation: a PUBLISHING row with no live task => poll loop moves it to PUBLISH_FAILED.
"""
from __future__ import annotations

from gateway import publish, states
from gateway.tests.conftest import (
    COMMIT_AUTHOR_MARKERS, FakeGit, app_client, csrf_for_session, curator_login,
    run, seed_validated, settle_publish,
)


def _approve(client, sid, *, note="approved for publication", overwrite=None, ack_pii=None):
    data = {"note": note, "csrf_token": csrf_for_session(client)}
    if overwrite is not None:
        data["confirm_overwrite"] = overwrite
    if ack_pii is not None:
        data["ack_pii"] = ack_pii
    return client.post(f"/gateway/curator/submission/{sid}/approve", data=data,
                       follow_redirects=False)


def test_happy_path_commits_and_stages(tmp_path):
    # Failure criterion: fails if the submission does not reach PUBLISHED, or the package was not
    # staged under surveys-live/surveys/<slug>, or the commit author was not the fixed identity, or a
    # rebuild was invoked (there must be no rebuild in the v2 flow).
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="demoslug")
            await curator_login(client)
            r = await _approve(client, sid)
            assert r.status_code == 303
            assert gw.db.get(sid).state == states.PUBLISHING  # returns immediately in PUBLISHING
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
            staged = cfg.surveys_live_dir / "surveys" / "demoslug" / "survey.yaml"
            assert staged.exists()
            commit_calls = [c for c in git.calls if "commit" in c]
            assert commit_calls, "no git commit was issued"
            assert any(m in " ".join(commit_calls[0]) for m in COMMIT_AUTHOR_MARKERS)
            # v2: PUBLISHED reason states it is committed, NOT served.
            reason = gw.db.transitions_for(sid)[-1]["reason"].lower()
            assert "committed" in reason and "rebuild-data" in reason
    run(_body())


def test_published_status_pages_say_not_yet_served(tmp_path):
    # design §5 v2: both the curator detail page AND the public status page must say PUBLISHED means
    # committed, not live. Failure criterion: fails if the "rebuild-data" guidance is absent.
    async def _body():
        import hashlib

        from gateway import db as db_mod
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = db_mod.new_id()
            token = "served-check-token-abc"
            gw.db.insert_submission(
                submission_id=sid, zip_sha256="f" * 64, zip_bytes=10, submitter_name="N",
                submitter_email="n@x.org", submitter_orcid=None,
                token_hash=hashlib.sha256(token.encode()).hexdigest())
            gw.db.transition(sid, states.SCANNED, actor="gateway", reason="clean")
            gw.db.transition(sid, states.VALIDATED, actor="runner", reason="ok", slug="srv")
            # materialise a package so staging works
            pkg = cfg.quarantine_dir / sid / "package" / "srv"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "survey.yaml").write_text("survey:\n  slug: srv\n", encoding="utf-8")
            (cfg.quarantine_dir / sid / "reports").mkdir(parents=True, exist_ok=True)
            await curator_login(client)
            await _approve(client, sid)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
            detail = await client.get(f"/gateway/curator/submission/{sid}")
            assert "rebuild-data" in detail.text
            public = await client.get(f"/gateway/status/{token}")
            assert "rebuild" in public.text.lower()
            assert "live map" in public.text.lower()
    run(_body())


def test_commit_carries_no_submitter_email(tmp_path):
    # THE PII guarantee for publish (house rule / design §8): the submitter email appears in NO git
    # argument. proven failing 2026-07-06: injecting the submitter email into the commit body made
    # this assertion break (verified by patching a leak in).
    async def _body():
        git = FakeGit()
        secret_email = "leak-canary-2938@private.test"
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email=secret_email)
            await curator_login(client)
            await _approve(client, sid, note="fine")
            await settle_publish(gw, sid)
            all_git_text = " ".join(" ".join(c) for c in git.calls)
            assert secret_email not in all_git_text
    run(_body())


def test_git_runner_env_scrubs_secrets(tmp_path, monkeypatch):
    # review #6: the env handed to git must NOT carry AUSMT_SUBMIT_KEY / AUSMT_CURATOR_KEYS (a hook
    # could read them). Failure criterion: fails if either secret var is present in scrubbed_env().
    # proven failing 2026-07-06: real_git_runner passed env=None → git inherited os.environ including
    # both secrets; scrubbed_env() drops them.
    monkeypatch.setenv("AUSMT_SUBMIT_KEY", "submit-secret")
    monkeypatch.setenv("AUSMT_CURATOR_KEYS", "curator1:curator-secret")
    monkeypatch.setenv("PATH", "/usr/bin")  # a benign var that MUST survive
    env = publish.scrubbed_env()
    assert "AUSMT_SUBMIT_KEY" not in env
    assert "AUSMT_CURATOR_KEYS" not in env
    assert env.get("PATH") == "/usr/bin"


def test_blocking_fail_refuses_approve_409(tmp_path):
    # proven failing 2026-07-06: disabling has_blocking_fail (if False:) let an approve on a FAIL
    # submission transition to PUBLISHING and run git (verified earlier).
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, fail_item=True)
            await curator_login(client)
            r = await _approve(client, sid)
            assert r.status_code == 409
            assert gw.db.get(sid).state == states.VALIDATED
            assert git.calls == []
    run(_body())


def test_pii_in_preview_blocks_approve(tmp_path):
    # The submitter's OWN email in the built preview is a blocking FAIL (design §4).
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, pii_in_preview=True)
            await curator_login(client)
            r = await _approve(client, sid)
            assert r.status_code == 409
            assert gw.db.get(sid).state == states.VALIDATED
            assert git.calls == []
    run(_body())


def test_foreign_email_in_preview_blocks_approve(tmp_path):
    # review #5: the PII sweep must ALSO fire on a DIFFERENT person's email via the generic pattern,
    # not only the submitter's own. Failure criterion: fails if a package containing a stranger's
    # email is approvable. proven failing 2026-07-06: the generic _EMAIL_RE was defined but never
    # used — only the submitter-email needle was checked, so a co-author's email sailed through.
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="submitter@example.org",
                                 foreign_email_in_preview="someone.else@other.test")
            await curator_login(client)
            r = await _approve(client, sid)
            assert r.status_code == 409
            assert gw.db.get(sid).state == states.VALIDATED
            assert git.calls == []
    run(_body())


def test_dirty_checkout_aborts_before_staging(tmp_path):
    # review #2 / design §5 step 1: a dirty surveys-live checkout => pre-flight ABORT, PUBLISH_FAILED,
    # NOTHING staged. Failure criterion: fails if a survey was staged, or if the state is not
    # PUBLISH_FAILED. proven failing 2026-07-06: with no pre-flight, staging proceeded on a dirty tree
    # and the survey dir appeared under surveys-live before the (unrelated) later steps.
    async def _body():
        git = FakeGit(dirty=True)
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, slug="dirtytest")
            await curator_login(client)
            await _approve(client, sid)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert not (cfg.surveys_live_dir / "surveys" / "dirtytest").exists()
            assert "dirty" in gw.db.transitions_for(sid)[-1]["reason"].lower()
            # No add/commit/push happened.
            assert not any(c[:1] == ["commit"] or "commit" in c for c in git.calls)
    run(_body())


def test_commit_fail_rolls_back_and_fails_closed(tmp_path):
    # review #1: a failure at the COMMIT step (e.g. a commit-hook rejection) — which was OUTSIDE the
    # old try/except — must roll surveys-live back and land PUBLISH_FAILED. Failure criterion: fails
    # if the state is not PUBLISH_FAILED or no rollback reset happened.
    # proven failing 2026-07-06: with checkout/add/commit outside the guard, a commit failure raised
    # straight out of _publish_blocking → the staged tree stayed and no reset was issued.
    async def _body():
        git = FakeGit(fail_on={"commit": (1, "pre-commit hook rejected the change")})
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            await _approve(client, sid)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert git.rolled_back, "commit failure did not roll surveys-live back to the pre-state ref"
    run(_body())


def test_push_fail_rolls_back(tmp_path):
    async def _body():
        git = FakeGit(fail_on={"push": (1, "remote rejected: non-fast-forward")})
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            await _approve(client, sid)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert git.rolled_back
    run(_body())


def test_rollback_restores_original_branch(tmp_path):
    # review #4: rollback must restore the CAPTURED branch/ref, not "whatever is currently checked
    # out". Here the checkout starts on a stale submit branch (a prior failed publish left it there),
    # so a naive rollback that reset the current branch would corrupt it. Pre-flight requires main —
    # so we start on main but assert the rollback checked out the captured branch explicitly.
    # Failure criterion: fails if _rollback did not force-checkout the captured branch.
    # proven failing 2026-07-06: the old _rollback only reset; it never re-checked-out the captured
    # branch, so a mid-publish branch switch (checkout main then a failed push) left HEAD on main
    # rather than the captured pre-branch.
    async def _body():
        git = FakeGit(fail_on={"push": (1, "rejected")}, start_branch="main")
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            await _approve(client, sid)
            await settle_publish(gw, sid)
            # The rollback must have force-checked-out the captured original branch (main) AND reset.
            checkout_f = [c for c in git.calls if c[:2] == ["checkout", "-f"]]
            assert checkout_f and checkout_f[-1][-1] == "main"
            assert git.rolled_back
            assert git.branch == "main"  # ended on the captured branch, not a submit branch
    run(_body())


def test_retry_from_publish_failed(tmp_path):
    # PUBLISH_FAILED -> retry -> PUBLISHING -> PUBLISHED (design §5.4 recoverability), git-only flow.
    async def _body():
        # First attempt fails at push (rolled back); retry with a clean git succeeds.
        git = FakeGit(fail_on={"push": (1, "transient")})
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            await _approve(client, sid)
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            # Swap to a clean git and retry. The rollback removed the staged tree, so the retry stages
            # fresh (no overwrite needed).
            git.fail_on = {}
            r = await client.post(f"/gateway/curator/submission/{sid}/retry",
                                  data={"note": "retrying after the transient push failure",
                                        "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
    run(_body())


def test_confirm_overwrite_exact_token(tmp_path):
    # review #7: confirm_overwrite must be an EXACT affirmative token, default DENY. "0" must NOT
    # enable overwrite. Failure criterion: fails if confirm_overwrite=0 overwrote an existing survey.
    # proven failing 2026-07-06: with bool(confirm_overwrite), the string "0" was truthy → the guard
    # was bypassed and the existing survey was replaced.
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            existing = cfg.surveys_live_dir / "surveys" / "mysurvey"
            existing.mkdir(parents=True, exist_ok=True)
            (existing / "old.txt").write_text("prior", encoding="utf-8")
            sid = seed_validated(gw, cfg, slug="mysurvey")
            await curator_login(client)
            await _approve(client, sid, overwrite="0")  # the falsy-string trap
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED  # refused, not overwritten
            assert (existing / "old.txt").exists()
    run(_body())


def test_overwrite_requires_confirmation(tmp_path):
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            existing = cfg.surveys_live_dir / "surveys" / "mysurvey"
            existing.mkdir(parents=True, exist_ok=True)
            (existing / "old.txt").write_text("prior", encoding="utf-8")
            sid = seed_validated(gw, cfg, slug="mysurvey")
            await curator_login(client)
            await _approve(client, sid, overwrite=None)  # no confirm at all
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert (existing / "old.txt").exists()
    run(_body())


def test_reconciliation_moves_stuck_publishing(tmp_path):
    # proven failing 2026-07-06: without _reconcile_publishing in poll_once, a hand-set PUBLISHING row
    # sat at PUBLISHING across poll passes forever (verified by disabling the reconcile step).
    async def _body():
        async with app_client(tmp_path) as (_client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            gw.db.transition(sid, states.PUBLISHING, actor="curator:curator1", reason="approved")
            assert sid not in gw._publishing
            await gw.poll_once()
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            assert "interrupted" in gw.db.transitions_for(sid)[-1]["reason"].lower()
    run(_body())


def test_slug_charset_validation():
    for bad in ("../evil", "a/b", "with space", "", ".hidden", "a" * 200):
        try:
            publish.validate_slug(bad)
        except publish.PublishError:
            continue
        raise AssertionError(f"validate_slug accepted a bad slug: {bad!r}")
    assert publish.validate_slug("good-slug_1.2") == "good-slug_1.2"


# --------------------------------------------------------------------------------------------------
# C11b — curator-acknowledgeable PII sweep (design maintainer/C11b-PiiAcknowledge.md).
# Every behaviour change below is proven-failing-first against pre-C11b code (evidence in the report).
# --------------------------------------------------------------------------------------------------
def test_generic_email_without_ack_refuses_approve_409(tmp_path):
    # C11b §4.1: a generic (non-submitter) email in the package, NO ack => approve 409 listing the PII
    # reason (the CURRENT hard-block behaviour, now pinned as an explicit regression). Failure
    # criterion: fails if the approve is not 409, or the reason does not mention the PII check, or the
    # submission left VALIDATED, or any git ran.
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="submitter@example.org",
                                 foreign_email_in_preview="someone.else@other.test")
            await curator_login(client)
            r = await _approve(client, sid)  # no ack_pii
            assert r.status_code == 409
            assert any("PII" in reason or "email" in reason.lower()
                       for reason in r.json()["reasons"])
            assert gw.db.get(sid).state == states.VALIDATED
            assert git.calls == []
    run(_body())


def test_generic_email_with_ack_publishes_and_audits(tmp_path):
    # C11b §4.2: generic email + ack_pii=yes + note => publish proceeds; the PUBLISHING audit reason
    # carries the PII-ACK prefix with the file name and the curator note. Failure criterion: fails if
    # the submission does not reach PUBLISHED, or the audit reason lacks PII-ACK / the file name / the
    # note. proven failing against pre-C11b code: there was no ack_pii path, so this approve 409'd and
    # the submission stayed VALIDATED.
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="submitter@example.org",
                                 foreign_email_in_preview="contact.person@records.test")
            await curator_login(client)
            r = await _approve(client, sid, note="INFO line is the original PI contact", ack_pii="yes")
            assert r.status_code == 303
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
            # The acknowledging transition is the VALIDATED->PUBLISHING row; find it in the trail.
            reasons = [t["reason"] for t in gw.db.transitions_for(sid)]
            ack_reason = next(r for r in reasons if "PII-ACK" in r)
            assert "index.html" in ack_reason
            assert "INFO line is the original PI contact" in ack_reason
            # The matched ADDRESS must never appear in the audit reason (file names only).
            assert "contact.person@records.test" not in ack_reason
    run(_body())


def test_submitter_email_with_ack_still_409(tmp_path):
    # C11b §0 / §4.3 — THE CONTRACT TEST. The submitter's OWN email present + ack_pii=yes => 409. No
    # acknowledgement can override a submitter-email hit. Also the MIXED case (submitter + generic) is
    # a 409 with ack, and a CASE-VARIANT of the submitter email is still a submitter hit (review
    # finding 1 — submitter-needle matching is case-insensitive by contract). Failure criterion: fails
    # if ANY acknowledged approve is not 409, or the state left VALIDATED, or any git ran.
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            # Pure submitter-email hit.
            sid = seed_validated(gw, cfg, email="owner@private.test", pii_in_preview=True)
            await curator_login(client)
            r = await _approve(client, sid, note="trying to force it", ack_pii="yes")
            assert r.status_code == 409, "ack overrode a submitter-email hit (§0 violated)"
            assert gw.db.get(sid).state == states.VALIDATED
            assert git.calls == []
            # Mixed: submitter email AND a stranger's email in the same product => still 409 with ack.
            sid2 = seed_validated(gw, cfg, slug="mixedsurvey", email="owner@private.test",
                                  pii_in_preview=True,
                                  foreign_email_in_preview="stranger@other.test")
            r2 = await _approve(client, sid2, note="trying to force the mixed case", ack_pii="yes")
            assert r2.status_code == 409, "ack overrode a mixed submitter+generic hit (§0 violated)"
            assert gw.db.get(sid2).state == states.VALIDATED
            assert git.calls == []
            # Case variant: DB says Owner@Private.Test, the artifact carries owner@private.test. That
            # is STILL the submitter's own address — a case difference must not demote it to generic.
            sid3 = seed_validated(gw, cfg, slug="casesurvey", email="Owner@Private.Test",
                                  foreign_email_in_preview="owner@private.test")
            r3 = await _approve(client, sid3, note="trying the case-variant bypass", ack_pii="yes")
            assert r3.status_code == 409, "ack overrode a case-variant submitter hit (§0 violated)"
            assert gw.db.get(sid3).state == states.VALIDATED
            assert git.calls == []
    run(_body())


def test_submitter_email_case_variants_classified_submitter(tmp_path):
    # Review finding 1 (SHIP-BLOCKER): the submitter needle was byte-exact while the generic regex is
    # case-insensitive, so 'User@Example.com' (DB) with 'user@example.com' in an artifact landed in
    # generic_hits => acknowledgeable => ack_pii published the submitter's own address. Both case
    # orientations must classify as SUBMITTER hits: approve with ack => 409, no ack checkbox rendered,
    # detail says the block is absolute. Failure criterion: fails if either orientation is
    # acknowledgeable (approve+ack != 409) or renders the ack checkbox.
    async def _body():
        cases = [
            ("User@Example.com", "user@example.com"),   # DB mixed-case, artifact lower
            ("user@example.com", "USER@EXAMPLE.COM"),   # DB lower, artifact upper
        ]
        for i, (db_email, artifact_email) in enumerate(cases):
            git = FakeGit()
            async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
                sid = seed_validated(gw, cfg, slug=f"case-{i}", email=db_email,
                                     foreign_email_in_preview=artifact_email)
                await curator_login(client)
                # The detail page must treat it as an ABSOLUTE submitter block: no ack checkbox.
                page = await client.get(f"/gateway/curator/submission/{sid}")
                assert 'name="ack_pii"' not in page.text, (
                    f"case variant {db_email!r}/{artifact_email!r} rendered an ack checkbox")
                assert "absolute" in page.text.lower()
                # And the approve gate must refuse even with ack.
                r = await _approve(client, sid, note="case-variant bypass attempt", ack_pii="yes")
                assert r.status_code == 409, (
                    f"case variant {db_email!r}/{artifact_email!r} was acknowledgeable (§0 bypass)")
                assert gw.db.get(sid).state == states.VALIDATED
                assert git.calls == []
    run(_body())


def test_ack_pii_exact_token_parsing(tmp_path):
    # C11b §4.4: ack_pii is an EXACT affirmative token, default DENY (mirrors confirm_overwrite). The
    # four affirmatives allow; "", "0", "false", "anything" deny. Failure criterion: fails if a
    # non-affirmative value lets the acknowledged approve proceed, or an affirmative is refused.
    # proven failing against pre-C11b code: there was no ack path at all, so every affirmative 409'd.
    async def _body():
        deny_values = ["", "0", "false", "anything", "YESa", " ", "2"]
        allow_values = ["1", "yes", "true", "on", "  YES ", "True", "On"]
        for i, val in enumerate(deny_values):
            git = FakeGit()
            async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
                sid = seed_validated(gw, cfg, slug=f"deny-{i}", email="submitter@example.org",
                                     foreign_email_in_preview="x@y.test")
                await curator_login(client)
                r = await _approve(client, sid, note="deny-token test", ack_pii=val)
                assert r.status_code == 409, f"ack_pii={val!r} wrongly counted as affirmative"
                assert gw.db.get(sid).state == states.VALIDATED
        for i, val in enumerate(allow_values):
            git = FakeGit()
            async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
                sid = seed_validated(gw, cfg, slug=f"allow-{i}", email="submitter@example.org",
                                     foreign_email_in_preview="x@y.test")
                await curator_login(client)
                r = await _approve(client, sid, note="allow-token test", ack_pii=val)
                assert r.status_code == 303, f"ack_pii={val!r} was not accepted as affirmative"
                await settle_publish(gw, sid)
                assert gw.db.get(sid).state == states.PUBLISHED
    run(_body())


def test_ack_address_never_echoed_and_report_capped(tmp_path):
    # C11b §4.5: needle-vs-generic separation; the report caps at 20 names with '+N more'; the matched
    # ADDRESS string appears in NO output (checklist detail, HTML, audit reason). Failure criterion:
    # fails if any matched address leaks, or the cap/+N-more is absent, or a submitter hit is
    # misclassified as generic.
    async def _body():
        # 25 package files each carrying a DIFFERENT generic address -> 25 generic hits => cap fires.
        addrs = [f"person{i:02d}@records.test" for i in range(25)]
        files = {f"mysurvey/extra/contact_{i:02d}.edi":
                 f">INFO\n  EMAIL={addrs[i]}\n>END\n" for i in range(25)}
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="submitter@example.org", package_files=files)
            await curator_login(client)
            page = await client.get(f"/gateway/curator/submission/{sid}")
            assert page.status_code == 200
            # None of the 25 matched addresses may appear in the rendered detail page.
            for a in addrs:
                assert a not in page.text, f"matched address leaked into the detail page: {a}"
            # The cap surfaced a '+N more' (25 hits, cap 20 => '+5 more').
            assert "+5 more" in page.text
            # Now acknowledge and confirm the audit reason also carries no address.
            r = await _approve(client, sid, note="all are >INFO contacts", ack_pii="yes")
            assert r.status_code == 303
            reasons = " ".join(t["reason"] for t in gw.db.transitions_for(sid))
            for a in addrs:
                assert a not in reasons, f"matched address leaked into the audit reason: {a}"
            assert "PII-ACK" in reasons and "+5 more" in reasons
    run(_body())


def test_retry_after_acknowledged_failure_needs_ack_again(tmp_path):
    # C11b §4.6: acknowledgement is PER-ACTION. A retry from PUBLISH_FAILED re-evaluates and needs
    # ack_pii again — a retry WITHOUT ack on a still-acknowledgeable submission is a 409. Failure
    # criterion: fails if the retry proceeds without a fresh ack. proven failing against pre-C11b
    # code: retry did not consider PII acknowledgement at all (the block was absolute), so this path
    # did not exist.
    async def _body():
        # First publish is acknowledged but fails at push (rolled back to PUBLISH_FAILED). The generic
        # email is still in the (rolled-back) quarantine package, so a retry re-sees the ack-able FAIL.
        git = FakeGit(fail_on={"push": (1, "transient")})
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="submitter@example.org",
                                 foreign_email_in_preview="contact@records.test")
            await curator_login(client)
            await _approve(client, sid, note="ack for the first attempt", ack_pii="yes")
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            git.fail_on = {}
            # Retry WITHOUT ack => 409 (per-action ack, nothing persisted on the row).
            r_noack = await client.post(
                f"/gateway/curator/submission/{sid}/retry",
                data={"note": "retry with no ack", "csrf_token": csrf_for_session(client)},
                follow_redirects=False)
            assert r_noack.status_code == 409, "retry proceeded without a fresh ack"
            assert gw.db.get(sid).state == states.PUBLISH_FAILED
            # Retry WITH ack => proceeds.
            r_ack = await client.post(
                f"/gateway/curator/submission/{sid}/retry",
                data={"note": "retry, re-acknowledged", "csrf_token": csrf_for_session(client),
                      "ack_pii": "yes"},
                follow_redirects=False)
            assert r_ack.status_code == 303
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
    run(_body())
