"""Every compose service that runs a healthcheck must set `init: true`.

Real incident: the frontdoor container's 30-second BusyBox-wget
healthcheck left exactly one Z-state process per interval, because Caddy runs as PID 1 and
never waits for orphaned children. Measured live: container up 48 minutes = 96 intervals =
97 zombies, tripping doctor.sh's zombie threshold (warn at 50). `init: true` puts Docker's
tini in front as PID 1, which reaps; nothing else about the service changes.

This pin fails when a healthchecked service in either compose file lacks `init: true` - so
a future service (or a revert) cannot quietly reintroduce the leak. Services WITHOUT a
healthcheck are exempt: gw-runner has none deliberately (see its comment in compose.yaml)
and its loop reaps its own job children.

Textual YAML parsing, matching this suite's convention (no yaml dependency): services are
level-1 keys (two spaces), their option keys level-2 (four spaces).
"""
import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]
COMPOSE_FILES = [DEPLOY / "compose.yaml", DEPLOY / "frontdoor" / "compose.yaml"]


def _services(text: str) -> dict[str, str]:
    m = re.search(r"^services:\n(.*?)(?=^\S|\Z)", text, re.M | re.S)
    assert m, "no services: mapping found"
    body = m.group(1)
    names = re.findall(r"^  (\w[\w-]*):\n", body, re.M)
    blocks = re.split(r"^  \w[\w-]*:\n", body, flags=re.M)[1:]
    return dict(zip(names, blocks))


def test_every_healthchecked_service_sets_init_true():
    missing = []
    for path in COMPOSE_FILES:
        for name, block in _services(path.read_text(encoding="utf-8")).items():
            has_healthcheck = re.search(r"^    healthcheck:", block, re.M)
            has_init = re.search(r"^    init: true\b", block, re.M)
            if has_healthcheck and not has_init:
                missing.append(f"{path.relative_to(DEPLOY)}::{name}")
    assert not missing, (
        "healthchecked service(s) without init: true (each 30s probe will leak one zombie "
        "under a non-reaping PID 1): " + ", ".join(missing)
    )
