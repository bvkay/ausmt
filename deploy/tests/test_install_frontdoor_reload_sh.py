"""install-frontdoor.sh in-place reload logic (ops-hardening O1).

Black-box over `sh`: a copy of the real install script is run in a tmp dir with a fabricated
.env/Caddyfile/compose.yaml and a PATH of stubs (docker, sudo) that record every docker invocation, so
the test drives the actual reload/fallback control flow without a real Docker or VPS. The three cases
the O1 design turns on:
  * already-running + reload OK  -> a `caddy reload` runs, NO restart;
  * already-running + reload FAILS -> a LOUD warning + a `compose restart frontdoor` fallback;
  * fresh (not running)          -> neither reload nor restart (up -d started it clean).

Skips on Windows / a host with no POSIX sh (the same platform reason the reconcile/preflight suites use);
on the gateway-ci ubuntu lane it RUNS with nothing skipped, so the skip tripwire needs no allow entry.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "frontdoor" / "install-frontdoor.sh"
_SH = shutil.which("sh") or shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run install-frontdoor.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh stubs not meaningful on this filesystem"),
]

# A docker stub: records argv to $STUB_LOG and behaves per the invocation. `ps -q frontdoor` prints a
# container id only when $STUB_RUNNING is set (already-running); `exec ... caddy reload` exits
# $STUB_RELOAD_RC; everything else succeeds.
_DOCKER_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_LOG"
case "$*" in
  "compose version") exit 0 ;;
  *"ps -q frontdoor") [ -n "${STUB_RUNNING:-}" ] && printf 'stubcid123\\n'; exit 0 ;;
  *"caddy validate"*) exit 0 ;;
  *"up -d") exit 0 ;;
  *"exec -T frontdoor caddy reload"*) exit "${STUB_RELOAD_RC:-0}" ;;
  *"restart frontdoor") exit 0 ;;
  *) exit 0 ;;
esac
"""

_SUDO_STUB = "#!/bin/sh\nexit 0\n"  # no-op: skip the real `sudo mkdir -p /var/log/caddy`


def _setup(tmp_path: Path) -> tuple[Path, dict]:
    work = tmp_path / "frontdoor"
    work.mkdir()
    shutil.copy(_SCRIPT, work / "install-frontdoor.sh")
    (work / "Caddyfile").write_text("# stub\n", encoding="utf-8")
    (work / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (work / ".env").write_text(
        "AUSMT_PUBLIC_NAME=ausmt.auscope.org.au\n"
        "AUSMT_BOX_READER_UPSTREAM=http://ausmt-box:8445\n"
        "AUSMT_ACME_EMAIL=x@y.org\n", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(_DOCKER_STUB, encoding="utf-8")
    (bindir / "sudo").write_text(_SUDO_STUB, encoding="utf-8")
    for f in ("docker", "sudo"):
        (bindir / f).chmod(0o755)
    log = tmp_path / "docker.log"
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["STUB_LOG"] = str(log)
    return work, env


def _run(work: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(work / "install-frontdoor.sh")],
                          capture_output=True, text=True, env=env, cwd=str(work))


def test_running_edge_reloads_in_place_no_restart(tmp_path):
    """Already-running + reload OK: a `caddy reload` must run and there must be NO restart (the whole
    point of O1 -- a graceful in-place reload, not a bounce). FAILS IF reload is skipped or a restart
    fires anyway."""
    work, env = _setup(tmp_path)
    env["STUB_RUNNING"] = "yes"
    env["STUB_RELOAD_RC"] = "0"
    r = _run(work, env)
    assert r.returncode == 0, f"installer failed: {r.stdout}\n{r.stderr}"
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    assert "caddy reload" in calls, f"a running edge must be reloaded in place; docker calls:\n{calls}"
    assert "restart frontdoor" not in calls, (
        f"a successful reload must NOT also restart; docker calls:\n{calls}")


def test_running_edge_reload_failure_falls_back_to_restart_loudly(tmp_path):
    """Already-running + reload FAILS: the installer must WARN loudly and fall back to a
    `compose restart frontdoor` so the new config still lands. FAILS IF there is no restart fallback or
    no loud warning."""
    work, env = _setup(tmp_path)
    env["STUB_RUNNING"] = "yes"
    env["STUB_RELOAD_RC"] = "1"
    r = _run(work, env)
    assert r.returncode == 0, f"installer should recover via restart: {r.stdout}\n{r.stderr}"
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    assert "caddy reload" in calls, "reload must be attempted first"
    assert "restart frontdoor" in calls, (
        f"a failed reload must fall back to a restart; docker calls:\n{calls}")
    assert "WARNING" in r.stderr, f"the fallback must be LOUD (WARNING on stderr); stderr:\n{r.stderr}"


def test_fresh_install_neither_reloads_nor_restarts(tmp_path):
    """Not running (fresh install): `up -d` starts the container against the current file, so there must
    be NO reload and NO restart. FAILS IF the installer reloads/restarts a container it just started."""
    work, env = _setup(tmp_path)
    env.pop("STUB_RUNNING", None)
    r = _run(work, env)
    assert r.returncode == 0, f"fresh install failed: {r.stdout}\n{r.stderr}"
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    assert "caddy reload" not in calls, f"a fresh install must not reload; docker calls:\n{calls}"
    assert "restart frontdoor" not in calls, f"a fresh install must not restart; docker calls:\n{calls}"
    assert "up -d" in calls, "a fresh install must still bring the stack up"


# --------------------------------------------------------------------------------------------------
# The canonical-name lane: the installer TEMPLATES the legacy redirect block in or out ([A2]).
# These run the REAL script against the REAL repo Caddyfile (not the stub), because the property
# under test is the render of the shipped template: legacy var unset -> Caddyfile.rendered carries
# exactly ONE site block and no legacy reference (an empty `{$VAR}` site address would be a Caddy
# parse error on exactly the deploy with no legacy name); legacy var set -> both blocks survive
# verbatim. The rendered file, not the template, must be what `caddy validate` is pointed at.
# --------------------------------------------------------------------------------------------------
_REAL_CADDYFILE = _REPO / "deploy" / "frontdoor" / "Caddyfile"


def _setup_real_caddyfile(tmp_path: Path, *, legacy: str | None) -> tuple[Path, dict]:
    work, env = _setup(tmp_path)
    shutil.copy(_REAL_CADDYFILE, work / "Caddyfile")
    if legacy is not None:
        with (work / ".env").open("a", encoding="utf-8") as fh:
            fh.write(f"AUSMT_LEGACY_REDIRECT_NAME={legacy}\n")
    return work, env


def _site_addresses(text: str) -> list[str]:
    """Depth-0 site-block addresses (the global options block, a bare '{', excluded)."""
    out, depth = [], 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if depth == 0 and line.endswith("{") and line[:-1].strip():
            out.append(line[:-1].strip())
        depth += line.count("{") - line.count("}")
    return out


def test_render_with_legacy_unset_strips_to_exactly_one_site_block(tmp_path):
    """[A2] Legacy var UNSET: the installer must write Caddyfile.rendered with the marker range
    stripped: exactly the canonical site block, zero legacy references, and the validate call must
    mount the RENDERED file. FAILS IF the legacy block (or any reference to its var) survives, or
    validate still points at the tracked template."""
    work, env = _setup_real_caddyfile(tmp_path, legacy=None)
    r = _run(work, env)
    assert r.returncode == 0, f"installer failed: {r.stdout}\n{r.stderr}"
    rendered = work / "Caddyfile.rendered"
    assert rendered.is_file(), "the installer must write Caddyfile.rendered"
    text = rendered.read_text(encoding="utf-8")
    assert _site_addresses(text) == ["{$AUSMT_PUBLIC_NAME}"], (
        f"the empty-var rendering must carry exactly the canonical site block, got "
        f"{_site_addresses(text)}")
    assert "AUSMT_LEGACY_REDIRECT_NAME" not in text, (
        "no legacy reference may survive the empty-var rendering")
    calls = Path(env["STUB_LOG"]).read_text(encoding="utf-8")
    validate = [c for c in calls.splitlines() if "caddy validate" in c]
    assert validate and "Caddyfile.rendered:/etc/caddy/Caddyfile:ro" in validate[0], (
        f"caddy validate must run over the rendered file; calls:\n{calls}")


def test_render_with_legacy_set_keeps_both_blocks_and_the_permanent_redir(tmp_path):
    """[A2] Legacy var SET: the rendering must keep BOTH site blocks, canonical first, with the
    legacy block still carrying its single permanent {uri}-preserving redir. FAILS IF the strip
    fires anyway, the order flips, or the redir softens."""
    work, env = _setup_real_caddyfile(tmp_path, legacy="ausmt.au")
    r = _run(work, env)
    assert r.returncode == 0, f"installer failed: {r.stdout}\n{r.stderr}"
    text = (work / "Caddyfile.rendered").read_text(encoding="utf-8")
    assert _site_addresses(text) == ["{$AUSMT_PUBLIC_NAME}", "{$AUSMT_LEGACY_REDIRECT_NAME}"], (
        f"the set-var rendering must keep canonical then legacy blocks, got {_site_addresses(text)}")
    assert "redir https://{$AUSMT_PUBLIC_NAME}{uri} permanent" in text, (
        "the legacy block must keep its permanent {uri}-preserving redir")
    assert r.stdout.count("rendering Caddyfile.rendered WITH the legacy redirect block") == 1


def test_closing_log_names_both_names_only_when_legacy_is_set(tmp_path):
    """The closing log line names BOTH hostnames when the legacy var is set (the operator is about
    to watch TWO ACME issuances) and only the canonical one when it is not. FAILS IF either closing
    line loses its name(s). The legacy fixture name is distinct from the fixture public name so each
    is unambiguously attributable in the output."""
    work, env = _setup_real_caddyfile(tmp_path, legacy="old.example.org")
    r = _run(work, env)
    assert r.returncode == 0, r.stderr
    assert "canonical ausmt.auscope.org.au" in r.stdout, (
        f"the closing line must name the canonical hostname; stdout:\n{r.stdout}")
    assert "legacy old.example.org as a permanent 301" in r.stdout, (
        f"the closing line must name the legacy hostname; stdout:\n{r.stdout}")
    solo_root = tmp_path / "solo"
    solo_root.mkdir()
    work2, env2 = _setup_real_caddyfile(solo_root, legacy=None)
    r2 = _run(work2, env2)
    assert r2.returncode == 0, r2.stderr
    assert "no legacy redirect name configured" in r2.stdout, (
        f"the canonical-only closing line must say no legacy name is configured; stdout:\n{r2.stdout}")
