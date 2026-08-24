"""A3 (LANE-CONTRACT-FORM-CREDIT): the survey.yaml the public Add Survey page PACKAGES is validated by
the REAL surveys validator, not by a same-author expectation of what it should look like.

The lane rewrites the form's credit and citation questions onto the ratified MTCAT 2.0 homes
(citation{}, organisations[], acknowledgements[], dates.issued, the ProjectLeader contributors row and
the typed related_identifiers row a pasted identifier becomes). Every one of those blocks is checked
surveys-side by rules the portal cannot see, and a form that writes a shape the validator refuses would
quarantine a real contributor's submission. So the driver (tools/packaged_yaml_dump.js) drives the LIVE
page through jsdom for a set of scenarios, unpacks each packaged zip into a validator-shaped package,
and this wrapper runs the validator over every one of them and asserts ZERO FAILs.

Validator resolution mirrors gateway/tests/conftest.py::resolve_validator_dir EXACTLY: the sibling
ausmt-surveys checkout when present (a dev box tests the LIVE cross-repo pair), else the committed
vendored copy (CI and fresh clones test the PINNED contract). "Neither present" is a BROKEN CHECKOUT,
because the vendored copy is committed - so it FAILS rather than skips. The one legitimate skip is the
driver reporting exit 2 (jsdom absent), matching test_add_survey_submit.py.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PORTAL = Path(__file__).resolve().parent.parent                     # portal/
REPO = PORTAL.parent                                                 # the monorepo root
DRIVER = PORTAL / "tools" / "packaged_yaml_dump.js"
# the sibling checkout sits beside the monorepo, not inside it
SIBLING_VALIDATOR_DIR = REPO.parent / "ausmt-surveys" / "_validation"
VENDORED_VALIDATOR_DIR = REPO / "gateway" / "tests" / "fixtures" / "vendored_validation"


def _validator_py() -> Path:
    """The validate_survey.py the oracles run: sibling checkout, else the committed vendored copy.
    Asserts (never skips) when neither is present - the vendored copy is committed, so its absence is
    a broken checkout, not a legitimate environment gap."""
    for candidate in (SIBLING_VALIDATOR_DIR, VENDORED_VALIDATOR_DIR):
        script = candidate / "validate_survey.py"
        if script.is_file():
            return script
    raise AssertionError(
        "no validator available: neither the sibling ausmt-surveys/_validation checkout nor the "
        f"committed vendored copy at {VENDORED_VALIDATOR_DIR} was found. The vendored copy is "
        "committed, so this is a BROKEN CHECKOUT, not a legitimate skip.")


def test_every_packaged_survey_yaml_validates_with_zero_fails(tmp_path):
    assert DRIVER.exists(), "packaged_yaml_dump.js missing"
    out_dir = tmp_path / "packaged"
    r = subprocess.run(["node", str(DRIVER)], capture_output=True, text=True, encoding="utf-8",
                       cwd=str(PORTAL), env={**_env(), "AUSMT_PACKAGED_YAML_DIR": str(out_dir)})
    driver_out = r.stdout + r.stderr
    if r.returncode == 2:
        pytest.skip("jsdom dev-dependency not installed (run `npm ci` in portal/)")
    assert r.returncode == 0, driver_out
    assert "PACKAGED-YAML DUMP OK" in driver_out, driver_out

    validator = _validator_py()
    packages = sorted(p for p in out_dir.iterdir() if p.is_dir())
    assert packages, f"the driver wrote no packages: {driver_out}"
    for pkg in packages:
        assert (pkg / "survey.yaml").is_file(), pkg
        report = tmp_path / f"{pkg.name}.json"
        subprocess.run([sys.executable, str(validator), str(pkg), "--json", str(report)],
                       capture_output=True, text=True, encoding="utf-8")
        assert report.is_file(), f"{pkg.name}: the validator wrote no JSON report"
        data = json.loads(report.read_text(encoding="utf-8"))
        items = data["items"] if isinstance(data, dict) else data
        fails = [i for i in items if i.get("level") in ("FAIL", "ERROR")]
        assert not fails, (
            f"{pkg.name}: the packaged survey.yaml the form produces is REFUSED by the real "
            f"validator: {fails}\n\n{(pkg / 'survey.yaml').read_text(encoding='utf-8')}")


def _env() -> dict:
    import os
    return dict(os.environ)
