"""VPS front-door doctor (deploy/frontdoor/doctor.sh, ops-hardening O4 + O3 zombie kit).

Black-box over `sh`. Every external command the doctor uses is overridable by an AUSMT_DOCTOR_* env var,
so the test points each at a tiny stub and drives the real report/exit/hash-compare/zombie-grouping logic
with no docker/tailscale/VPS. The load-bearing pins: the report is one labelled line per check, the exit
is non-zero iff any check FAILs, the config check PASSES on a hash match and FAILS on a mismatch (the O1
stale-config trap), and the zombie kit NAMES the top leaker by parent PID.

Skips on Windows / no POSIX sh (platform reason, same as the reconcile/preflight suites); RUNS with
nothing skipped on the gateway-ci ubuntu lane, so the skip tripwire needs no allow entry.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DOCTOR = _REPO / "deploy" / "frontdoor" / "doctor.sh"
_SH = shutil.which("sh") or shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run doctor.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh stubs not meaningful on this filesystem"),
]

_DOCKER_STUB = """#!/bin/sh
case "$*" in
  *"ps -q frontdoor") echo cid ;;
  *"inspect -f"*) echo running ;;
  *"exec -T frontdoor sha256sum"*) echo "$FAKE_HASH  /etc/caddy/Caddyfile" ;;
  *) exit 0 ;;
esac
"""
# The curl stub answers per-invocation: the path-URL contract leg (recognisable by its pinned
# /surveys/vulcan-2022 probe path) gets "${PATHURL_OUT}" header text (default: the correct 301 with
# the fragment-route Location; `-` not `:-` so an EMPTY value models the unreachable edge); the
# redirect leg (recognisable by its `%{redirect_url}` format string) gets "${REDIR_OUT}" (default:
# the correct 301 to the canonical schema URL); every other probe gets the plain "${CURL_CODE}"
# body. Argv is recorded so a test can pin WHAT was probed (the https:// scheme of the redirect and
# pathurl legs is itself a load-bearing property).
_CURL_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "${CURL_ARGV_LOG:-/dev/null}"
case "$*" in
  *"/surveys/vulcan-2022"*) printf '%b' "${PATHURL_OUT-HTTP/1.1 301 Moved Permanently\\nlocation: https://ausmt.auscope.org.au/#/survey/vulcan-2022\\n}" ;;
  *redirect_url*) printf '%s' "${REDIR_OUT:-301 https://ausmt.auscope.org.au/data/mtcat.schema.json}" ;;
  *) echo "${CURL_CODE:-200}" ;;
esac
"""
_TAILSCALE_STUB = '#!/bin/sh\ncase "$1" in status) echo "100.1.2.3 ausmt-box linux -"; exit 0;; esac\n'
# With NO_LEGACY_CERT set, the s_client leg for the LEGACY name returns nothing (no cert served).
# The match is END-ANCHORED (`*"-servername ausmt.au"`, no trailing *): ausmt.au is a PREFIX of
# ausmt.auscope.org.au, so a substring match would knock out the canonical name's cert too.
_OPENSSL_STUB = """#!/bin/sh
case "$*" in
  *s_client*)
    case "$*" in
      *"-servername ausmt.au") [ -n "${NO_LEGACY_CERT:-}" ] && exit 0 ;;
    esac
    echo CERT ;;
  *x509*enddate*) read -r line || true; [ -n "$line" ] && echo "notAfter=${CERT_ENDDATE:-Jul 25 12:00:00 2027 GMT}" ;;
esac
"""
_DIG_STUB = '#!/bin/sh\necho "${DIG_IP:-203.0.113.9}"\n'
# ps stub: emits fixture zombie rows for `-eo stat=,ppid=,comm=` and a parent name for `-o args= -p PID`.
_PS_STUB = """#!/bin/sh
case "$*" in
  *"-eo stat"*) printf '%b' "${PS_ROWS:-S 1 init\\n}" ;;
  *"-o args= -p 4242") echo "/usr/bin/leaky-parent --serve" ;;
  *"-o args= -p 9001") echo "ssh caddylog@ausmt-vps" ;;
  *) echo "" ;;
esac
"""


def _bindir(tmp_path: Path) -> Path:
    b = tmp_path / "bin"
    b.mkdir()
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB), ("tailscale", _TAILSCALE_STUB),
                       ("openssl", _OPENSSL_STUB), ("dig", _DIG_STUB), ("ps", _PS_STUB)):
        p = b / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    return b


def _env(tmp_path: Path, caddyfile: Path, *, legacy: str | None = "ausmt.au", **extra) -> dict:
    """The doctor's .env fixture mirrors the canonical-name deploy: the AuScope name is canonical
    and (by default) ausmt.au is the legacy redirect name, so the legacy legs RUN in the default
    fixtures. Pass legacy=None for the canonical-only deploy (the legs must then SKIP)."""
    b = _bindir(tmp_path)
    envf = tmp_path / ".env"
    lines = ["AUSMT_PUBLIC_NAME=ausmt.auscope.org.au",
             "AUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445"]
    if legacy is not None:
        lines.append(f"AUSMT_LEGACY_REDIRECT_NAME={legacy}")
    envf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "AUSMT_DOCTOR_DOCKER": str(b / "docker"),
        "AUSMT_DOCTOR_CURL": str(b / "curl"),
        "AUSMT_DOCTOR_TAILSCALE": str(b / "tailscale"),
        "AUSMT_DOCTOR_OPENSSL": str(b / "openssl"),
        "AUSMT_DOCTOR_DIG": str(b / "dig"),
        "AUSMT_DOCTOR_PS": str(b / "ps"),
        "AUSMT_DOCTOR_ENV": str(envf),
        "AUSMT_DOCTOR_CADDYFILE": str(caddyfile),
        "AUSMT_DOCTOR_COMPOSE": str(tmp_path / "compose.yaml"),
        "AUSMT_DOCTOR_DISK_PATH": "/",
        "AUSMT_DOCTOR_EXPECT_IP": "203.0.113.9",
    })
    env.update(extra)
    return env


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_DOCTOR), *args], capture_output=True, text=True, env=env)


def _caddyfile(tmp_path: Path, text: str = "# doctor test caddyfile\n") -> Path:
    p = tmp_path / "Caddyfile"
    p.write_text(text, encoding="utf-8")
    return p


def test_report_all_pass_is_labelled_and_exits_zero(tmp_path):
    """With every probe green the report must be one labelled PASS/WARN/FAIL line per check, end in a
    PASS RESULT, and exit 0. FAILS IF a check line is unlabelled or the exit is non-zero on an all-green
    run."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest())
    r = _run(env, "report")
    assert r.returncode == 0, f"all-green report should exit 0:\n{r.stdout}\n{r.stderr}"
    body = [ln for ln in r.stdout.splitlines()
            if ln and not ln.startswith("=") and not ln.startswith("AusMT front-door doctor")
            and not ln.startswith("RESULT")]
    assert body, "expected check lines"
    for ln in body:
        assert ln.split(" ", 1)[0] in ("PASS", "WARN", "FAIL"), f"unlabelled check line: {ln!r}"
    assert "FAIL" not in r.stdout, f"no check should FAIL on an all-green run:\n{r.stdout}"
    assert r.stdout.rstrip().splitlines()[-1].startswith("RESULT: PASS")


def test_config_hash_match_passes(tmp_path):
    """O1 trap, green side: when the container's mounted Caddyfile hashes EQUAL to the repo file, the
    config check PASSES. Proves the FAIL pin below is non-vacuous."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest())
    r = _run(env, "report")
    assert any(ln.startswith("PASS config:") for ln in r.stdout.splitlines()), (
        f"a matching config hash must PASS:\n{r.stdout}")


def test_config_hash_mismatch_fails_and_exits_nonzero(tmp_path):
    """O1 trap, red side: when the RUNNING container's Caddyfile hash DIFFERS from the repo file, the
    config check must FAIL and the whole run must exit non-zero (so it can gate an alert). FAILS IF a
    drifted running config is reported green."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH="deadbeef" * 8)
    r = _run(env, "report")
    assert any(ln.startswith("FAIL config:") for ln in r.stdout.splitlines()), (
        f"a mismatched config hash must FAIL:\n{r.stdout}")
    assert r.returncode != 0, "any FAIL must make the doctor exit non-zero"
    assert r.stdout.rstrip().splitlines()[-1].startswith("RESULT: FAIL")


def test_zombie_kit_names_top_leaker_by_parent(tmp_path):
    """O3: the zombie kit must count Z-state procs and group them by PARENT PID with the heaviest parent
    at the top (the named leaker). Fixture: ppid 4242 has two zombies, ppid 9001 has one, so 4242 must
    lead. FAILS IF the kit does not aggregate by parent or does not surface the top parent first."""
    cf = _caddyfile(tmp_path)
    rows = "Z 4242 defunct-a\\nZ 4242 defunct-b\\nZ 9001 defunct-c\\nS 1 init\\n"
    env = _env(tmp_path, cf, PS_ROWS=rows)
    r = _run(env, "zombies")
    assert r.returncode == 0, f"the kit is read-only and should exit 0:\n{r.stdout}"
    assert "3" in r.stdout.splitlines()[2], f"expected a total count of 3 zombies:\n{r.stdout}"
    grouped = [ln for ln in r.stdout.splitlines() if "ppid=" in ln]
    assert grouped, f"expected grouped-by-parent lines:\n{r.stdout}"
    assert "4242" in grouped[0], f"the heaviest parent (4242, 2 zombies) must lead:\n{r.stdout}"
    assert "leaky-parent" in grouped[0], "the leaker's command line should be named"
    assert "init: true" in r.stdout, "the kit must list the container-PID-1 reaping fix"


def test_unknown_subcommand_exits_2(tmp_path):
    """Arg parsing: an unknown subcommand must exit 2 with a usage hint, not silently run the report."""
    cf = _caddyfile(tmp_path)
    r = _run(_env(tmp_path, cf), "wibble")
    assert r.returncode == 2, f"unknown subcommand must exit 2, got {r.returncode}"
    assert "unknown subcommand" in r.stderr


def test_upstream_down_fails(tmp_path):
    """A non-200 from the box reader must FAIL the upstream check and the run."""
    cf = _caddyfile(tmp_path)
    env = _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest(), CURL_CODE="502")
    r = _run(env, "report")
    assert any(ln.startswith("FAIL upstream:") for ln in r.stdout.splitlines()), (
        f"a 502 upstream must FAIL:\n{r.stdout}")
    assert r.returncode != 0


# --------------------------------------------------------------------------------------------------
# Canonical-name lane: the legacy-name legs (certificate for BOTH names; the legacy 301; skip-clean).
# --------------------------------------------------------------------------------------------------
def _hash_env(tmp_path, cf, **extra):
    return _env(tmp_path, cf, FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest(), **extra)


def test_legacy_legs_pass_when_cert_and_301_are_right(tmp_path):
    """GREEN side of the legacy legs (proves the FAIL pins below are non-vacuous): with a legacy
    cert served and the redirect answering 301 to the canonical schema URL, tls-legacy and redirect
    both PASS and the run exits 0."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf), "report")
    assert r.returncode == 0, f"all-green with legacy set should exit 0:\n{r.stdout}\n{r.stderr}"
    assert any(ln.startswith("PASS tls-legacy: certificate for ausmt.au") for ln in r.stdout.splitlines()), (
        f"the legacy certificate leg must PASS and name the legacy host:\n{r.stdout}")
    assert any(ln.startswith("PASS redirect:") and "301s to" in ln for ln in r.stdout.splitlines()), (
        f"the redirect leg must PASS on a correct 301:\n{r.stdout}")


def test_missing_legacy_certificate_is_a_fail_not_a_warn(tmp_path):
    """A legacy name with NO served certificate means the https:// leg of every old link is dead:
    the check must FAIL (never WARN) and the run must exit non-zero, while the canonical cert
    (whose name the legacy one prefixes) stays PASS. FAILS IF the missing cert is soft-pedalled."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf, NO_LEGACY_CERT="1"), "report")
    lines = r.stdout.splitlines()
    assert any(ln.startswith("FAIL tls-legacy: no certificate served for ausmt.au") for ln in lines), (
        f"a missing legacy certificate must FAIL:\n{r.stdout}")
    assert not any(ln.startswith("WARN tls-legacy:") for ln in lines), "FAIL, not WARN"
    assert any(ln.startswith("PASS tls: certificate for ausmt.auscope.org.au") for ln in lines), (
        f"the canonical certificate must still PASS (prefix names must not cross-trip):\n{r.stdout}")
    assert r.returncode != 0


def test_redirect_leg_requires_301_exactly(tmp_path):
    """A 302 (or any non-301) from the legacy name must FAIL the redirect leg: a temporary status
    would tell crawlers the move is temporary, which breaks the permanent contract."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf,
                       REDIR_OUT="302 https://ausmt.auscope.org.au/data/mtcat.schema.json"), "report")
    assert any(ln.startswith("FAIL redirect:") for ln in r.stdout.splitlines()), (
        f"a 302 must FAIL the redirect leg:\n{r.stdout}")
    assert r.returncode != 0


def test_redirect_leg_requires_the_canonical_target_with_path_preserved(tmp_path):
    """A 301 to the WRONG place (host or path) must FAIL: the leg pins the Location, not just the
    status, so a redirect that drops the path or points off the canonical name cannot pass."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf, REDIR_OUT="301 https://ausmt.auscope.org.au/"), "report")
    assert any(ln.startswith("FAIL redirect:") for ln in r.stdout.splitlines()), (
        f"a 301 that drops the path must FAIL:\n{r.stdout}")
    assert r.returncode != 0


def test_redirect_leg_probes_the_https_url_of_the_schema_id(tmp_path):
    """The redirect probe must be the EXPLICIT https:// leg on the old schema $id path: Caddy's
    automatic HTTP->HTTPS hop answers any http:// probe with a redirect, so only an https:// probe
    proves the legacy SITE BLOCK is doing the redirecting. FAILS IF the probe scheme or path drifts."""
    cf = _caddyfile(tmp_path)
    argv_log = tmp_path / "curl.argv"
    r = _run(_hash_env(tmp_path, cf, CURL_ARGV_LOG=str(argv_log)), "report")
    assert r.returncode == 0, r.stdout
    redirect_calls = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines()
                      if "redirect_url" in ln]
    assert len(redirect_calls) == 1, f"exactly one redirect probe expected: {redirect_calls}"
    assert "https://ausmt.au/data/mtcat.schema.json" in redirect_calls[0], (
        f"the probe must be the https:// URL of the old schema $id; argv: {redirect_calls[0]}")
    assert "--resolve ausmt.au:443:127.0.0.1" in redirect_calls[0], (
        f"the probe must pin the legacy name to this host; argv: {redirect_calls[0]}")


def test_unset_legacy_var_skips_both_legs_cleanly(tmp_path):
    """Canonical-only deploy (no legacy var): both legacy legs must be SKIPPED, not failed, the skip
    must be visible (an explicit labelled line each), and the run must exit 0."""
    cf = _caddyfile(tmp_path)
    r = _run(_env(tmp_path, cf, legacy=None,
                  FAKE_HASH=hashlib.sha256(cf.read_bytes()).hexdigest()), "report")
    assert r.returncode == 0, f"the canonical-only deploy must stay green:\n{r.stdout}\n{r.stderr}"
    lines = r.stdout.splitlines()
    assert any(ln.startswith("PASS tls-legacy: skipped") for ln in lines), (
        f"the legacy cert leg must visibly skip:\n{r.stdout}")
    assert any(ln.startswith("PASS redirect: skipped") for ln in lines), (
        f"the redirect leg must visibly skip:\n{r.stdout}")
    assert not any(ln.startswith(("FAIL tls-legacy", "FAIL redirect")) for ln in lines)


def test_config_check_agrees_with_the_installers_rendering(tmp_path):
    """CROSS-IMPLEMENTATION DRIFT GUARD. install-frontdoor.sh renders Caddyfile.rendered; doctor.sh
    independently re-renders the repo template for its hash compare. Run the REAL installer (docker
    stubbed) over the REAL repo Caddyfile in both var states, then feed each rendering's hash to the
    doctor as the container-mounted file: the config leg must PASS both ways. FAILS IF the two
    renderers ever diverge (the sed ranges are meant to be identical)."""
    real_cf = _REPO / "deploy" / "frontdoor" / "Caddyfile"
    install = _REPO / "deploy" / "frontdoor" / "install-frontdoor.sh"
    for label, legacy in (("unset", None), ("set", "ausmt.au")):
        work = tmp_path / f"install-{label}"
        work.mkdir(parents=True)
        shutil.copy(install, work / "install-frontdoor.sh")
        shutil.copy(real_cf, work / "Caddyfile")
        (work / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        envtext = ("AUSMT_PUBLIC_NAME=ausmt.auscope.org.au\n"
                   "AUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445\n"
                   "AUSMT_ACME_EMAIL=x@y.org\n")
        if legacy:
            envtext += f"AUSMT_LEGACY_REDIRECT_NAME={legacy}\n"
        (work / ".env").write_text(envtext, encoding="utf-8")
        bindir = work / "bin"
        bindir.mkdir()
        (bindir / "docker").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (bindir / "sudo").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        for f in ("docker", "sudo"):
            (bindir / f).chmod(0o755)
        ienv = dict(os.environ)
        ienv["PATH"] = f"{bindir}:{ienv['PATH']}"
        ri = subprocess.run([_SH, str(work / "install-frontdoor.sh")], capture_output=True,
                            text=True, env=ienv, cwd=str(work))
        assert ri.returncode == 0, f"installer ({label}) failed: {ri.stdout}\n{ri.stderr}"
        rendered_hash = hashlib.sha256((work / "Caddyfile.rendered").read_bytes()).hexdigest()
        doctor_root = tmp_path / f"doctor-{label}"
        doctor_root.mkdir()
        denv = _env(doctor_root, real_cf, legacy=legacy, FAKE_HASH=rendered_hash)
        rd = _run(denv, "report")
        assert any(ln.startswith("PASS config:") for ln in rd.stdout.splitlines()), (
            f"doctor's fresh render ({label}) must hash-match the installer's rendering:\n{rd.stdout}")


# --------------------------------------------------------------------------------------------------
# Path-URL contract lane (2026-08-18): the /surveys/<slug> 301 leg.
# --------------------------------------------------------------------------------------------------
def test_pathurl_leg_passes_on_the_contract_301(tmp_path):
    """GREEN side (proves the FAIL pins below are non-vacuous): with the edge answering the pinned
    /surveys/vulcan-2022 probe with a 301 whose Location is the exact fragment route, the pathurl
    leg PASSES and the run exits 0."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf), "report")
    assert r.returncode == 0, f"all-green should exit 0:\n{r.stdout}\n{r.stderr}"
    assert any(ln.startswith("PASS pathurl:") and "301s to" in ln
               for ln in r.stdout.splitlines()), (
        f"the pathurl leg must PASS on the contract 301:\n{r.stdout}")


def test_pathurl_leg_fails_on_a_non_301(tmp_path):
    """An edge that answers the path shape with anything but a 301 (here a 200, i.e. the redirect
    section is missing and the reader swallowed the path) must FAIL the leg and the run."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf, PATHURL_OUT="HTTP/1.1 200 OK\\n"), "report")
    assert any(ln.startswith("FAIL pathurl:") for ln in r.stdout.splitlines()), (
        f"a non-301 must FAIL the pathurl leg:\n{r.stdout}")
    assert r.returncode != 0


def test_pathurl_leg_fails_on_a_wrong_location(tmp_path):
    """A 301 to the WRONG place (a Location that is not the fragment route for the probed slug)
    must FAIL: the leg pins the Location, not just the status."""
    cf = _caddyfile(tmp_path)
    wrong = "HTTP/1.1 301 Moved Permanently\\nlocation: https://ausmt.auscope.org.au/\\n"
    r = _run(_hash_env(tmp_path, cf, PATHURL_OUT=wrong), "report")
    assert any(ln.startswith("FAIL pathurl:") for ln in r.stdout.splitlines()), (
        f"a 301 to the wrong Location must FAIL the pathurl leg:\n{r.stdout}")
    assert r.returncode != 0


def test_pathurl_leg_skips_cleanly_when_unreachable(tmp_path):
    """No response at all from the probe (edge down or unreachable): the leg SKIPS cleanly with a
    visible PASS-labelled line (the container check is the authority on a down edge) and the run
    stays green. FAILS IF an unreachable edge turns the leg into a FAIL."""
    cf = _caddyfile(tmp_path)
    r = _run(_hash_env(tmp_path, cf, PATHURL_OUT=""), "report")
    assert r.returncode == 0, f"an unreachable probe must not fail the run:\n{r.stdout}\n{r.stderr}"
    assert any(ln.startswith("PASS pathurl: skipped") for ln in r.stdout.splitlines()), (
        f"the pathurl leg must visibly skip when unreachable:\n{r.stdout}")


def test_pathurl_leg_probes_the_pinned_slug_over_https(tmp_path):
    """The probe must be the EXPLICIT https:// path-shape URL for the pinned vulcan-2022 slug on
    the canonical name, resolved to this host (--resolve), so the leg exercises the canonical
    block's own mapping and never a DNS detour. FAILS IF the scheme, slug, or resolve pin drifts."""
    cf = _caddyfile(tmp_path)
    argv_log = tmp_path / "curl.argv"
    r = _run(_hash_env(tmp_path, cf, CURL_ARGV_LOG=str(argv_log)), "report")
    assert r.returncode == 0, r.stdout
    calls = [ln for ln in argv_log.read_text(encoding="utf-8").splitlines()
             if "/surveys/vulcan-2022" in ln]
    assert len(calls) == 1, f"exactly one pathurl probe expected: {calls}"
    assert "https://ausmt.auscope.org.au/surveys/vulcan-2022" in calls[0], (
        f"the probe must be the https:// path-shape URL on the canonical name; argv: {calls[0]}")
    assert "--resolve ausmt.auscope.org.au:443:127.0.0.1" in calls[0], (
        f"the probe must pin the canonical name to this host; argv: {calls[0]}")
