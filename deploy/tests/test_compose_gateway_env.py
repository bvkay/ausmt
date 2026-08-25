"""The compose gateway environment list is the ONLY bridge from deploy/.env to the app: a
variable gateway/config.py reads but compose does not forward is silently invisible to the
container, however carefully the operator sets it. Real incident (2026-07-24): the self-serve
key mail settings (AUSMT_SMTP_* / AUSMT_MAIL_FROM) shipped in .env.example and config.py but
were missing from compose.yaml's gateway environment block, so the operator configured mail,
the container saw nothing, and request-key silently issued no keys.

This pin fails when ANY operator-facing variable config reads is dropped from the gateway
service's environment block. It reads the YAML textually (no yaml dependency in this suite) but
anchors on the gateway service's environment mapping keys, so a rename or removal trips it.

DERIVATION BOUNDARY (H1, deploy review section 5). REQUIRED_FORWARDED is DERIVED from
gateway.config.operator_env_vars(), NOT hand-listed - that is the whole point of this revision.
The old pin restated a copy of config's env surface (only the six mail vars), so it stayed green
while five self-serve abuse-control knobs (AUSMT_KEYREQ_* / AUSMT_SELFSERVE_KEY_*) that config
reads went unforwarded - the same class of drift the 2026-07-24 incident is. operator_env_vars()
records every AUSMT_* key load_config() actually reads and drops the two container-fixed paths
(AUSMT_GW_DATA, AUSMT_SURVEYS_LIVE - compose sets those to /gw and /srv/surveys-live itself, they
are not .env knobs). So the required set = every AUSMT_* operator knob config consumes, and a knob
newly added to load_config is required here automatically. Secrets that ARE forwarded
(AUSMT_SUBMIT_KEY, AUSMT_CURATOR_KEYS, AUSMT_SMTP_PASS) are in the set and must stay forwarded.
"""
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from gateway.config import operator_env_vars  # noqa: E402 - path insert above must precede this

COMPOSE = _REPO / "deploy" / "compose.yaml"

# Derived, never hand-maintained (see the module docstring's DERIVATION BOUNDARY).
REQUIRED_FORWARDED = operator_env_vars()


def _gateway_environment_keys() -> set[str]:
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"^  gateway:\n(.*?)(?=^  \S)", text, re.M | re.S)
    assert m, "gateway service not found in deploy/compose.yaml"
    block = m.group(1)
    env = re.search(r"^    environment:\n(.*?)(?=^    \S)", block, re.M | re.S)
    assert env, "gateway service has no environment block"
    return set(re.findall(r"^      (AUSMT_[A-Z_]+|HOME|GIT_[A-Z_]+|TMPDIR):", env.group(1), re.M))


def test_required_forward_set_is_nonempty_and_derived():
    """Guards the derivation itself: operator_env_vars() must return a real set (not an empty tuple a
    silent import/refactor slip could produce), and must EXCLUDE the container-fixed paths so this pin
    never demands compose forward a var it fixes inline. FAILS IF the derived surface collapses."""
    assert len(REQUIRED_FORWARDED) >= 6, "the derived operator env surface is implausibly small"
    assert "AUSMT_SMTP_HOST" in REQUIRED_FORWARDED, "the mail vars must be in the derived set"
    assert "AUSMT_GW_DATA" not in REQUIRED_FORWARDED, "AUSMT_GW_DATA is container-fixed, not an .env knob"
    assert "AUSMT_SURVEYS_LIVE" not in REQUIRED_FORWARDED, \
        "AUSMT_SURVEYS_LIVE is container-fixed, not an .env knob"


def test_gateway_forwards_every_operator_env_var():
    keys = _gateway_environment_keys()
    missing = [name for name in REQUIRED_FORWARDED if name not in keys]
    assert not missing, (
        f"compose.yaml gateway environment is missing {missing}; a value set in deploy/.env "
        "never reaches the container unless it is forwarded here. This set is DERIVED from "
        "gateway.config.operator_env_vars(), so add the passthrough(s) to the gateway service."
    )
