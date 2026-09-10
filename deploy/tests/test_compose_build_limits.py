"""The build container's resource ceiling.

`build-runner` is the only service on the box that can grow without bound: the engine fans MTH5
writes out to N worker processes, each of which holds a station-sized unit of h5/pydantic state, so
the container's footprint is roughly N times what any single process reports. The box has 15 GB and
must keep the portal, the gateway, clamd and the OS alive while a build runs. Without a cgroup
ceiling a runaway build is the kernel's problem, and the kernel's OOM killer does not know that the
portal matters more than the build; with one, the build dies inside its own cgroup and everything
else keeps serving.

`pids_limit` is the same ceiling in the other unit: the parent, its MTH5 workers and their library
threads are a bounded set, so a fork storm has a floor to hit that is not the host's pid space.

Pinned here rather than reviewed, because the failure is invisible until the night it is not: a
compose file with no `mem_limit` runs exactly like one with a generous cap right up to the build
that exceeds it.

Textual YAML parsing, matching this suite's convention (no yaml dependency): services are level-1
keys (two spaces), their option keys level-2 (four spaces).
"""
import re
import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
COMPOSE = DEPLOY / "compose.yaml"
ENV_EXAMPLE = DEPLOY / ".env.example"

sys.path.insert(0, str(DEPLOY / "scripts"))
from check_compose_guards import find_guard_trips  # noqa: E402 - path insert above must precede this

MEM_KNOB = "AUSMT_BUILD_MEM_LIMIT"


def _service_block(name: str) -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert m, f"{name} service not found in deploy/compose.yaml"
    return m.group(1)


def test_build_runner_declares_a_memory_ceiling():
    """FAILS IF build-runner has no mem_limit: an unbounded build competes with the portal, the
    gateway and clamd for the box's 15 GB, and the kernel resolves that competition."""
    block = _service_block("build-runner")
    assert re.search(r"^    mem_limit:", block, re.M), (
        "deploy/compose.yaml's build-runner declares no mem_limit; a build that runs away takes the "
        "box down instead of dying inside its own cgroup")


def test_build_runner_declares_a_process_ceiling():
    """FAILS IF build-runner has no pids_limit. The worker pool plus library threads is a bounded
    set; without the cap a fork storm has no floor short of the host's pid space."""
    block = _service_block("build-runner")
    assert re.search(r"^    pids_limit:", block, re.M), (
        "deploy/compose.yaml's build-runner declares no pids_limit")


def test_the_memory_ceiling_is_an_operator_knob_that_never_aborts_config():
    """The knob follows the AUSMT_CACHE_MAX_MB pattern exactly: ${VAR:-DEFAULT}, so an operator can
    lower it on a smaller box and an unset variable resolves to the shipped default. FAILS IF it is
    hard-coded (no knob) or written as a ${VAR:?} guard, which would abort every compose command,
    including a portal-only one, until the variable was set."""
    block = _service_block("build-runner")
    m = re.search(r"^    mem_limit:\s*(\S+)", block, re.M)
    assert m, "build-runner declares no mem_limit"
    value = m.group(1)
    assert re.fullmatch(rf"\$\{{{MEM_KNOB}:-[0-9]+[kmg]?\}}", value), (
        f"build-runner's mem_limit must be ${{{MEM_KNOB}:-DEFAULT}} (the AUSMT_CACHE_MAX_MB "
        f"pattern), got {value!r}")
    minimal = {"AUSMT_DATA_DIR": "/srv/ausmt", "OWNER": "someowner"}
    trips = find_guard_trips(COMPOSE.read_text(encoding="utf-8"), minimal)
    assert not any(t.var == MEM_KNOB for t in trips), (
        f"{MEM_KNOB} must never be a hard :? guard")


def test_the_memory_knob_is_documented_for_the_operator():
    """FAILS IF the knob exists in compose but not in .env.example. An undocumented cap is a cap the
    operator discovers by having a build killed."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert MEM_KNOB in text, (
        f"deploy/.env.example does not document {MEM_KNOB}; an operator cannot tune a knob that is "
        "not written down")
