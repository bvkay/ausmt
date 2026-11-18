"""The client name the repository's own jobs send, so the usage fold counts them as the operator.

Each doctor and the Makefile smoke check send a user-agent opening with `ausmt-ops/`. The doctors
build their curl command as `${AUSMT_DOCTOR_CURL:-curl} -A ausmt-ops/1-<job>`, so a set override
keeps the name, and every call site expands $CURL unquoted, which is why the token carries no space.
The stub tests in the three doctor test files prove the override case at run time.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_AGG_SCRIPT = _REPO / "deploy" / "scripts" / "aggregate_stats.py"
_MAKEFILE = _REPO / "deploy" / "Makefile"
_DOCTORS = {
    "deploy/frontdoor/doctor.sh": "ausmt-ops/1-doctor-frontdoor",
    "deploy/nectar/doctor-serve.sh": "ausmt-ops/1-doctor-serve",
    "deploy/scripts/doctor-box.sh": "ausmt-ops/1-doctor-box",
}
_SMOKE = "ausmt-ops/1-smoke"
_NAME_RE = re.compile(r"ausmt-ops/[^\s\"']*")


def _agg():
    spec = importlib.util.spec_from_file_location("aggregate_stats", _AGG_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _code_lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


def _smoke_recipe() -> list[str]:
    lines = _MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = lines.index("smoke:") + 1
    recipe = []
    for ln in lines[start:]:
        if not ln.startswith("\t"):
            break
        recipe.append(ln)
    return recipe


@pytest.mark.parametrize("rel", sorted(_DOCTORS))
def test_repository_jobs_send_ausmt_ops_client_name(rel):
    """Each doctor's curl default appends its client name after the override, and every call site
    expands $CURL unquoted so the name stays its own argument. Fails if the name is dropped, sits
    inside the override's default, or a call site quotes $CURL."""
    lines = _code_lines(_REPO / rel)
    assigns = [ln for ln in lines if re.match(r"^\s*CURL=", ln)]
    assert assigns == [f'CURL="${{AUSMT_DOCTOR_CURL:-curl}} -A {_DOCTORS[rel]}"'], assigns
    uses = [ln for ln in lines if re.search(r"\$\{?CURL\b", ln)]
    assert uses, rel
    for ln in uses:
        assert not re.search(r"\"\$\{?CURL\b", ln), f"quoted $CURL in {rel}: {ln.strip()}"
        assert re.search(r"\$CURL\s", ln), f"$CURL not a bare word in {rel}: {ln.strip()}"


def test_smoke_curls_send_ausmt_ops_client_name():
    """Both smoke curls in the Makefile send the smoke client name."""
    curls = [ln for ln in _smoke_recipe() if "curl" in ln]
    assert len(curls) == 2, curls
    for ln in curls:
        assert re.search(r"\bcurl -fsS -A %s http" % re.escape(_SMOKE), ln), ln


def test_client_name_token_has_no_space_and_no_classifier_token():
    """Every client name the repository sends is one word that opens with the operator prefix, is
    read as the operator from any address, and holds no crawler or scripted token, so the name
    never depends on the classifier order."""
    agg = _agg()
    found = set()
    for rel in _DOCTORS:
        found |= set(_NAME_RE.findall("\n".join(_code_lines(_REPO / rel))))
    found |= set(_NAME_RE.findall("\n".join(_smoke_recipe())))
    assert found == set(_DOCTORS.values()) | {_SMOKE}, found
    for name in found:
        assert not re.search(r"\s", name), name
        assert name.lower().startswith(agg._OPERATOR_UA_PREFIX), name
        for token in agg._CRAWLER_TOKENS + agg._SCRIPTED_TOKENS:
            assert token not in name.lower(), (name, token)
        assert agg._operator_label("frontdoor", "203.0.113.0", name, None) == agg.OPERATOR_YES
