"""The compose gateway environment list is the ONLY bridge from deploy/.env to the app: a
variable gateway/config.py reads but compose does not forward is silently invisible to the
container, however carefully the operator sets it. Real incident (2026-07-24): the self-serve
key mail settings (AUSMT_SMTP_* / AUSMT_MAIL_FROM) shipped in .env.example and config.py but
were missing from compose.yaml's gateway environment block, so the operator configured mail,
the container saw nothing, and request-key silently issued no keys.

This pin fails when a mail-flow variable is dropped from the gateway service's environment
block. It reads the YAML textually (no yaml dependency in this suite) but anchors on the
gateway service's environment mapping keys, so a rename or removal trips it.
"""
import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "compose.yaml"

# The operator-facing mail/key-issuance variables gateway/config.py reads. Extend when the
# config grows a new operator-set env var that the compose gateway service must forward.
REQUIRED_FORWARDED = [
    "AUSMT_SMTP_HOST",
    "AUSMT_SMTP_PORT",
    "AUSMT_SMTP_USER",
    "AUSMT_SMTP_PASS",
    "AUSMT_MAIL_FROM",
    "AUSMT_SUBMIT_PAGE_URL",
]


def _gateway_environment_keys() -> set[str]:
    text = COMPOSE.read_text(encoding="utf-8")
    m = re.search(r"^  gateway:\n(.*?)(?=^  \S)", text, re.M | re.S)
    assert m, "gateway service not found in deploy/compose.yaml"
    block = m.group(1)
    env = re.search(r"^    environment:\n(.*?)(?=^    \S)", block, re.M | re.S)
    assert env, "gateway service has no environment block"
    return set(re.findall(r"^      (AUSMT_[A-Z_]+|HOME|GIT_[A-Z_]+|TMPDIR):", env.group(1), re.M))


def test_gateway_forwards_the_mail_flow_variables():
    keys = _gateway_environment_keys()
    missing = [name for name in REQUIRED_FORWARDED if name not in keys]
    assert not missing, (
        f"compose.yaml gateway environment is missing {missing}; a value set in deploy/.env "
        "never reaches the container unless it is forwarded here"
    )
