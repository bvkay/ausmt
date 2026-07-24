"""Self-serve submission keys (feat/selfserve-submit-keys, K1-K4). A SECOND key-issuance path
alongside the operator-issued keys: POST /gateway/request-key mints an `email_verified` uploader key,
BOUND to the requesting email, with a 14-day expiry and a 5-submission allowance, and mails it. Both
kinds coexist; operator keys are unchanged.

Every test asserts against an INDEPENDENT observable and RED-proves its enforcement pin (stated in
the docstring). No network: the mail layer is either an injected fake seam (endpoint tests) or a
monkeypatched smtplib (mailer-unit tests). Async bodies run under conftest.run() (no pytest-asyncio),
the established gateway pattern.
"""
from __future__ import annotations

import logging
import smtplib
import time

from gateway import mailer as mailer_mod
from gateway import uploader_keys
from gateway.tests.conftest import (
    SUBMIT_KEY, app_client, good_package_zip, make_config, run, scanner_clean, submit_zip,
)


# --------------------------------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------------------------------
class FakeMailer:
    """A record-and-report mail seam matching the gateway's send callable
    (*, to_email, key, expires_utc, allowance) -> bool. `result` is what a send returns; `raises`
    makes the send raise (the SMTP-down path). Records every call so a test can assert the key was
    passed exactly once and never leaked elsewhere."""

    def __init__(self, *, result: bool = True, raises: bool = False):
        self.calls: list[dict] = []
        self.result = result
        self.raises = raises

    def __call__(self, *, to_email, key, expires_utc, allowance):
        self.calls.append(
            {"to_email": to_email, "key": key, "expires_utc": expires_utc, "allowance": allowance})
        if self.raises:
            raise RuntimeError("fake smtp down")
        return self.result


class _FakeSMTP:
    """A context-manager stand-in for smtplib.SMTP / SMTP_SSL. Records the transport events so a test
    can prove STARTTLS vs implicit-SSL and that auth+send happened. Never opens a socket."""
    instances: list["_FakeSMTP"] = []
    kind = "SMTP"

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.events: list = []
        self.sent: list = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.events.append("ehlo")

    def starttls(self):
        self.events.append("starttls")

    def login(self, user, password):
        self.events.append(("login", user, password))

    def send_message(self, msg):
        self.sent.append(msg)


class _FakeSMTPSSL(_FakeSMTP):
    kind = "SMTP_SSL"


def _mail_cfg(tmp_path, **over):
    """A make_config with SMTP configured so the real mailer path (mail_configured True) is exercised
    in the mailer-unit tests."""
    base = dict(smtp_host="smtp.example.org", smtp_port=587, smtp_user="submissions@ausmt.au",
                smtp_pass="a-secret-pw", mail_from="submissions@ausmt.au",
                submit_page_url="https://ausmt.au/submit")
    base.update(over)
    return make_config(tmp_path, **base)


# --------------------------------------------------------------------------------------------------
# K2: minting + provenance via the endpoint
# --------------------------------------------------------------------------------------------------
def test_request_key_mints_email_verified_key_with_binding_expiry_allowance(tmp_path):
    """An allowed request mints an email_verified key BOUND to the requesting email with a ~14-day
    expiry and a 5-submission allowance, stores only its hash, and hands the plaintext to the mailer
    ONCE. RED-proves: without the v5 provenance/expiry/allowance the minted key would be a plain
    operator key (no binding). Fails if the key is not email_verified, unbound, or has no
    expiry/allowance."""
    async def _body():
        mailer = FakeMailer()
        async with app_client(tmp_path, mailer=mailer) as (client, _app, gw, cfg):
            r = await client.post("/gateway/request-key", data={"email": "contributor@example.org"})
            assert r.status_code == 202
            keys = gw.db.list_uploader_keys()
            assert len(keys) == 1
            k = keys[0]
            assert k.provenance == "email_verified"
            assert k.email == "contributor@example.org"
            assert k.expires_utc is not None and k.expires_utc > time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            assert k.allowance_remaining == cfg.email_verified_key_allowance == 5
            assert k.created_by == "self-serve"
            # The plaintext reached the mailer exactly once and hashes to the stored digest.
            assert len(mailer.calls) == 1
            plaintext = mailer.calls[0]["key"]
            assert plaintext.startswith("ausmt_up_")
            assert uploader_keys.key_hash(plaintext) == k.key_sha256
    run(_body())


# --------------------------------------------------------------------------------------------------
# K1: neutral-202-always + no enumeration
# --------------------------------------------------------------------------------------------------
def test_neutral_202_identical_for_valid_invalid_ratelimited_and_smtp_down(tmp_path):
    """The endpoint ALWAYS returns the byte-identical neutral 202 — valid+issued, invalid email,
    rate-limited, AND mail-failure alike (no account/email enumeration, no rate-limit disclosure).
    RED-proves the anti-enumeration pin: any branch that returned a different status/body would fail
    here."""
    async def _body():
        # valid + issued
        async with app_client(tmp_path, mailer=FakeMailer()) as (client, _a, _g, _c):
            valid = await client.post("/gateway/request-key", data={"email": "a@example.org"})
        # invalid email
        async with app_client(tmp_path, mailer=FakeMailer()) as (client, _a, _g, _c):
            invalid = await client.post("/gateway/request-key", data={"email": "not-an-email"})
        # rate-limited (per-email cap 0 blocks every request)
        async with app_client(tmp_path, mailer=FakeMailer(),
                              key_request_per_email_daily=0) as (client, _a, _g, _c):
            limited = await client.post("/gateway/request-key", data={"email": "b@example.org"})
        # SMTP down (send raises)
        async with app_client(tmp_path, mailer=FakeMailer(raises=True)) as (client, _a, _g, _c):
            smtp_down = await client.post("/gateway/request-key", data={"email": "c@example.org"})
        for r in (valid, invalid, limited, smtp_down):
            assert r.status_code == 202
        bodies = {valid.content, invalid.content, limited.content, smtp_down.content}
        assert len(bodies) == 1, "the 202 body must be byte-identical across every outcome"
    run(_body())


def test_invalid_email_mints_nothing_and_never_mails(tmp_path):
    """A syntactically invalid email mints no key and never calls the mailer (format is not account
    existence). RED-proves: a handler that minted before validating would leave a row here."""
    async def _body():
        mailer = FakeMailer()
        async with app_client(tmp_path, mailer=mailer) as (client, _app, gw, _cfg):
            for junk in ("", "nope", "a@b", "a b@example.org", "two@@example.org"):
                r = await client.post("/gateway/request-key", data={"email": junk})
                assert r.status_code == 202
            assert gw.db.list_uploader_keys() == []
            assert mailer.calls == []
    run(_body())


def test_smtp_unconfigured_disables_issuance(tmp_path):
    """With no mailer seam AND no SMTP config, issuance is DISABLED: the endpoint mints nothing and
    still returns the neutral 202 (K3). RED-proves: a handler that minted regardless of a configured
    mail path would leave an undeliverable key row."""
    async def _body():
        # No mailer injected and make_config sets no SMTP -> cfg.mail_configured is False.
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            assert cfg.mail_configured is False
            r = await client.post("/gateway/request-key", data={"email": "x@example.org"})
            assert r.status_code == 202
            assert gw.db.list_uploader_keys() == []
    run(_body())


# --------------------------------------------------------------------------------------------------
# K2: submit-path enforcement — email binding, expiry, allowance; operator keys unaffected
# --------------------------------------------------------------------------------------------------
def _issue_email_verified(gw, *, email, expires_utc=None, allowance=5):
    """Mint an email_verified key straight through the DB (bypassing the endpoint) so the submit-path
    tests control expiry/allowance precisely. Returns the plaintext key."""
    key = uploader_keys.mint_key()
    exp = expires_utc or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 14 * 86400))
    gw.db.create_email_verified_key(
        email=email, key_sha256=uploader_keys.key_hash(key), expires_utc=exp, allowance=allowance)
    return key


def test_email_verified_key_authorises_matching_submitter_and_decrements(tmp_path):
    """An email_verified key authorises a submit whose submitter_email MATCHES its bound email, and a
    successful submit decrements the allowance by exactly one. RED-proves the allowance pin: without
    the decrement the count would stay 5."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key = _issue_email_verified(gw, email="binder@example.org", allowance=5)
            r = await submit_zip(client, good_package_zip(), key=key, email="binder@example.org")
            assert r.status_code == 201
            row = gw.db.list_uploader_keys()[0]
            assert row.allowance_remaining == 4, "a successful submit must spend one allowance"
            assert row.last_used_utc is not None
    run(_body())


def test_email_binding_mismatch_rejected_same_as_invalid(tmp_path):
    """An email_verified key with a submitter_email that does NOT match its bound email is rejected
    with the SAME 401 body as an outright invalid key (no oracle, no binding leak). RED-proves the
    binding pin: without binding enforcement this submit would be a 201."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key = _issue_email_verified(gw, email="owner@example.org")
            mismatch = await submit_zip(client, good_package_zip(), key=key,
                                        email="someone-else@example.org")
            invalid = await submit_zip(client, good_package_zip(), key="ausmt_up_never-issued-000000")
            assert mismatch.status_code == 401
            assert mismatch.status_code == invalid.status_code
            assert mismatch.content == invalid.content, "binding failure must not be distinguishable"
            # Nothing was accepted, so the allowance is untouched.
            assert gw.db.list_uploader_keys()[0].allowance_remaining == 5
    run(_body())


def test_email_binding_is_case_insensitive(tmp_path):
    """The email binding matches case-insensitively (the same address in different case authorises).
    RED-proves: an exact-case-only compare would 401 this valid submit."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key = _issue_email_verified(gw, email="Mixed.Case@Example.ORG")
            r = await submit_zip(client, good_package_zip(), key=key,
                                 email="mixed.case@example.org")
            assert r.status_code == 201
    run(_body())


def test_expired_key_rejected_same_as_invalid(tmp_path):
    """An email_verified key past its expiry is rejected with the same 401 as an invalid key.
    RED-proves the expiry pin: without the expiry check the expired key would authorise (201)."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
            key = _issue_email_verified(gw, email="expired@example.org", expires_utc=past)
            r = await submit_zip(client, good_package_zip(), key=key, email="expired@example.org")
            assert r.status_code == 401
    run(_body())


def test_allowance_exhausted_rejected(tmp_path):
    """An email_verified key with allowance 1 authorises exactly one submit; the second (allowance now
    0) is rejected 401. RED-proves the exhaustion pin: without the depleted-allowance rejection the
    second submit would be a 201."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            key = _issue_email_verified(gw, email="one-shot@example.org", allowance=1)
            first = await submit_zip(client, good_package_zip(), key=key, email="one-shot@example.org")
            assert first.status_code == 201
            assert gw.db.list_uploader_keys()[0].allowance_remaining == 0
            # A DIFFERENT package (distinct sha) so the second attempt is not a duplicate-409.
            from gateway.tests.conftest import make_zip
            other = make_zip({
                "mysurvey/survey.yaml": b"survey:\n  slug: mysurvey\n",
                "mysurvey/transfer_functions/edi/S02.edi": b">HEAD\n  DATAID=S02\n>END\n"})
            second = await submit_zip(client, other, key=key, email="one-shot@example.org")
            assert second.status_code == 401, "an exhausted allowance must reject further submits"
    run(_body())


def test_operator_keys_unaffected_by_binding_and_expiry(tmp_path):
    """Operator keys behave EXACTLY as before: the env key authorises any submitter_email, and a
    curator-issued DB key (provenance 'operator') is NOT email-bound and has no expiry/allowance even
    when it carries an email. RED-proves: if binding were applied to operator keys, the env submit
    below (submitter_email != any bound value) would 401."""
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, _cfg):
            # env key: any submitter email works.
            r_env = await submit_zip(client, good_package_zip(), key=SUBMIT_KEY,
                                     email="whoever@example.org")
            assert r_env.status_code == 201
            # curator-issued operator key WITH an email set: still not bound, no allowance spent.
            op_key = uploader_keys.mint_key()
            gw.db.create_uploader_key(name="op-team", email="op-owner@example.org",
                                      key_sha256=uploader_keys.key_hash(op_key), created_by="cur")
            from gateway.tests.conftest import make_zip
            pkg = make_zip({
                "mysurvey/survey.yaml": b"survey:\n  slug: mysurvey\n",
                "mysurvey/transfer_functions/edi/S03.edi": b">HEAD\n  DATAID=S03\n>END\n"})
            r_op = await submit_zip(client, pkg, key=op_key, email="a-totally-different@example.org")
            assert r_op.status_code == 201, "an operator key must not be email-bound"
            row = next(k for k in gw.db.list_uploader_keys() if k.name == "op-team")
            assert row.allowance_remaining is None, "operator keys carry no allowance"
    run(_body())


# --------------------------------------------------------------------------------------------------
# K1: rate limits (per-email, per-ip, global) + persistence across restart
# --------------------------------------------------------------------------------------------------
def test_rate_limit_per_email(tmp_path):
    """The per-email daily cap limits issuance to ONE address without blocking OTHER addresses.
    RED-proves the per-email pin: with the cap set to 2, the 3rd request for the same email mints
    nothing while a different email still issues."""
    async def _body():
        async with app_client(tmp_path, mailer=FakeMailer(), key_request_per_email_daily=2,
                              key_request_per_ip_daily=100,
                              key_request_global_daily=100) as (client, _app, gw, _cfg):
            for _ in range(3):
                await client.post("/gateway/request-key", data={"email": "repeat@example.org"})
            same = [k for k in gw.db.list_uploader_keys() if k.email == "repeat@example.org"]
            assert len(same) == 2, "the per-email cap must stop the 3rd key for the same address"
            # A different email is unaffected by another address's cap.
            await client.post("/gateway/request-key", data={"email": "fresh@example.org"})
            assert [k for k in gw.db.list_uploader_keys() if k.email == "fresh@example.org"]
    run(_body())


def test_rate_limit_per_ip(tmp_path):
    """The per-IP daily cap limits issuance from one source across DIFFERENT emails. RED-proves the
    per-ip pin: with per-ip 2 (per-email/global high), the 3rd distinct-email request from the same IP
    mints nothing."""
    async def _body():
        async with app_client(tmp_path, mailer=FakeMailer(), key_request_per_email_daily=100,
                              key_request_per_ip_daily=2,
                              key_request_global_daily=100) as (client, _app, gw, _cfg):
            for i in range(3):
                await client.post("/gateway/request-key", data={"email": f"ip{i}@example.org"})
            assert len(gw.db.list_uploader_keys()) == 2, "the per-IP cap must stop the 3rd source key"
    run(_body())


def test_rate_limit_global_daily(tmp_path):
    """The global daily cap is the absolute backstop across all emails/IPs. RED-proves the global pin:
    with global 2 (per-email/per-ip high), the 3rd request overall mints nothing."""
    async def _body():
        async with app_client(tmp_path, mailer=FakeMailer(), key_request_per_email_daily=100,
                              key_request_per_ip_daily=100,
                              key_request_global_daily=2) as (client, _app, gw, _cfg):
            for i in range(3):
                await client.post("/gateway/request-key", data={"email": f"g{i}@example.org"})
            assert len(gw.db.list_uploader_keys()) == 2, "the global cap must stop the 3rd key overall"
    run(_body())


def test_rate_limit_persists_across_restart(tmp_path):
    """The rate-limit state lives in the DB (the store the submissions table uses), so it SURVIVES a
    gateway restart: an attacker cannot reset a per-email cap by bouncing the process. RED-proves the
    persistence pin: an in-memory limiter would forget the earlier requests and issue again after the
    restart."""
    async def _body():
        # First app instance: exhaust the per-email cap of 2.
        async with app_client(tmp_path, mailer=FakeMailer(), key_request_per_email_daily=2,
                              key_request_per_ip_daily=100,
                              key_request_global_daily=100) as (client, _app, gw, _cfg):
            for _ in range(2):
                await client.post("/gateway/request-key", data={"email": "persist@example.org"})
            assert len(gw.db.list_uploader_keys()) == 2
        # Second app instance over the SAME data dir (same sqlite) — a restart. The cap is already hit.
        async with app_client(tmp_path, mailer=FakeMailer(), key_request_per_email_daily=2,
                              key_request_per_ip_daily=100,
                              key_request_global_daily=100) as (client, _app, gw, _cfg):
            r = await client.post("/gateway/request-key", data={"email": "persist@example.org"})
            assert r.status_code == 202
            assert len(gw.db.list_uploader_keys()) == 2, "the daily cap must persist across a restart"
    run(_body())


def test_rate_limit_store_failure_fails_closed(tmp_path):
    """If the persistent rate-limit store errors, the endpoint fails CLOSED (issues nothing) and still
    returns the neutral 202. RED-proves: a handler that minted on a rate-limit error would open an
    unbounded-issuance hole under DB pressure."""
    async def _body():
        mailer = FakeMailer()
        async with app_client(tmp_path, mailer=mailer) as (client, _app, gw, _cfg):
            def _boom(**_kw):
                raise RuntimeError("rate store down")
            gw.db.try_record_key_request = _boom  # type: ignore[method-assign]
            r = await client.post("/gateway/request-key", data={"email": "y@example.org"})
            assert r.status_code == 202
            assert gw.db.list_uploader_keys() == []
            assert mailer.calls == []
    run(_body())


# --------------------------------------------------------------------------------------------------
# K4: no key material in logs
# --------------------------------------------------------------------------------------------------
def test_no_key_material_in_logs_on_success_or_mail_failure(tmp_path, caplog):
    """Neither a successful issuance nor a mail failure writes the key plaintext to any log line
    (the key is a bearer secret). RED-proves the no-key-in-logs pin: a debug log of the minted key, or
    a mailer that logged the key on failure, would surface the plaintext in caplog here."""
    async def _body():
        with caplog.at_level(logging.DEBUG):
            # Success path.
            ok_mailer = FakeMailer()
            async with app_client(tmp_path, mailer=ok_mailer) as (client, _a, _g, _c):
                await client.post("/gateway/request-key", data={"email": "log-ok@example.org"})
                ok_key = ok_mailer.calls[0]["key"]
            # Mail-failure path (send raises).
            async with app_client(tmp_path, mailer=FakeMailer(raises=True)) as (client, _a, gw, _c):
                await client.post("/gateway/request-key", data={"email": "log-fail@example.org"})
                fail_key = [k for k in gw.db.list_uploader_keys()][0].key_sha256
        assert ok_key not in caplog.text, "the plaintext key must never appear in a log line"
        # The stored HASH is not secret, but the plaintext (which we never have for the fail path) and
        # the ausmt_up_ prefix of a real key must not leak either.
        assert "ausmt_up_" not in caplog.text, "no key material (even prefixed) may reach the logs"
        assert fail_key  # sanity: a key was minted on the fail path (so the log path was exercised)
    run(_body())


# --------------------------------------------------------------------------------------------------
# K3: the stdlib mailer (mock smtplib, never the network)
# --------------------------------------------------------------------------------------------------
def test_is_syntactic_email():
    """The syntactic email gate accepts plausible addresses and rejects obvious junk (a FORMAT check,
    not deliverability). Fails if the gate drifts to accept whitespace/double-@/no-dot forms."""
    for good in ("a@b.co", "first.last@example.org", "x+tag@sub.domain.io"):
        assert mailer_mod.is_syntactic_email(good) is True
    for bad in ("", "nope", "a@b", "a b@example.org", "two@@example.org", "no@domain"):
        assert mailer_mod.is_syntactic_email(bad) is False
    # A trailing space is stripped before the check, so the stripped address is accepted.
    assert mailer_mod.is_syntactic_email("trailing@example.org ") is True


def test_mailer_starttls_on_port_587(tmp_path, monkeypatch):
    """On a non-465 port the mailer connects plaintext then UPGRADES with STARTTLS before auth+send,
    and returns True. Fails if the STARTTLS upgrade is skipped (cleartext auth) or send is not called."""
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    cfg = _mail_cfg(tmp_path, smtp_port=587)
    ok = mailer_mod.send_key_email(cfg, to_email="to@example.org", key="ausmt_up_SECRET_KEY_XYZ",
                                   expires_utc="2026-08-07T00:00:00Z", allowance=5)
    assert ok is True
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.kind == "SMTP"
    assert "starttls" in smtp.events, "non-465 must STARTTLS before auth"
    assert ("login", "submissions@ausmt.au", "a-secret-pw") in smtp.events
    assert len(smtp.sent) == 1
    body = smtp.sent[0].get_content()
    assert "ausmt_up_SECRET_KEY_XYZ" in body, "the key must be in the mailed body"
    assert "2026-08-07T00:00:00Z" in body and "5 submission" in body


def test_mailer_implicit_ssl_on_port_465(tmp_path, monkeypatch):
    """On port 465 the mailer uses implicit TLS (SMTP_SSL), NOT the STARTTLS upgrade path. Fails if the
    port-465 branch runs plaintext SMTP or calls starttls."""
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    cfg = _mail_cfg(tmp_path, smtp_port=465)
    ok = mailer_mod.send_key_email(cfg, to_email="to@example.org", key="ausmt_up_K",
                                   expires_utc="2026-08-07T00:00:00Z", allowance=3)
    assert ok is True
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.kind == "SMTP_SSL"
    assert "starttls" not in smtp.events, "implicit-SSL must not STARTTLS"
    assert len(smtp.sent) == 1


def test_mailer_send_failure_returns_false_without_logging_key(tmp_path, monkeypatch, caplog):
    """A send failure returns False and logs WITHOUT the key. Fails if the failure raises out (would
    break the endpoint 202) or logs the key material."""
    def _raise(*_a, **_k):
        raise smtplib.SMTPException("connect refused")
    monkeypatch.setattr(smtplib, "SMTP", _raise)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _raise)
    cfg = _mail_cfg(tmp_path, smtp_port=587)
    with caplog.at_level(logging.DEBUG):
        ok = mailer_mod.send_key_email(cfg, to_email="to@example.org", key="ausmt_up_TOPSECRET",
                                       expires_utc="2026-08-07T00:00:00Z", allowance=5)
    assert ok is False
    assert "ausmt_up_TOPSECRET" not in caplog.text
    assert "TOPSECRET" not in caplog.text


def test_mailer_unconfigured_returns_false(tmp_path):
    """With SMTP unconfigured the mailer sends nothing and returns False (the endpoint's disabled
    branch). Fails if it tries to connect with an empty host."""
    cfg = make_config(tmp_path)  # no SMTP fields
    assert cfg.mail_configured is False
    assert mailer_mod.send_key_email(cfg, to_email="to@example.org", key="ausmt_up_K",
                                     expires_utc="2026-08-07T00:00:00Z", allowance=5) is False


def test_mailer_body_has_no_em_dash_and_carries_reply_to(tmp_path, monkeypatch):
    """The email body carries no em dash (house rule for user-facing strings) and the message sets
    Reply-To to the From address (K3). Fails if an em dash slips into the body or Reply-To is missing."""
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)
    cfg = _mail_cfg(tmp_path, smtp_port=587)
    mailer_mod.send_key_email(cfg, to_email="to@example.org", key="ausmt_up_K",
                              expires_utc="2026-08-07T00:00:00Z", allowance=5)
    msg = _FakeSMTP.instances[0].sent[0]
    assert msg["Reply-To"] == "submissions@ausmt.au"
    body = msg.get_content()
    assert "—" not in body, "no em dash in a user-facing email body"
    assert "https://ausmt.au/submit" in body, "the submit-page link must appear when configured"
    assert msg["Subject"]


# --------------------------------------------------------------------------------------------------
# Config redaction: the SMTP password never reaches the startup log
# --------------------------------------------------------------------------------------------------
def test_smtp_pass_redacted_from_config_dump(tmp_path):
    """The startup config dump carries the SMTP host/port/user/from (operational) but NEVER the SMTP
    password. Fails if the password value appears in redacted_items()."""
    cfg = _mail_cfg(tmp_path, smtp_pass="a-very-secret-smtp-pw-9999")
    items = dict(cfg.redacted_items())
    assert "a-very-secret-smtp-pw-9999" not in items.values()
    assert items["AUSMT_SMTP_PASS"] == "<redacted>"
    assert items["AUSMT_SMTP_HOST"] == "smtp.example.org"
    assert items["AUSMT_MAIL_FROM"] == "submissions@ausmt.au"
