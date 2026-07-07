"""The positional column ORDER is single-sourced in contract/columns.json and generated into
engine/extract/_contract.py + portal/src/contract.js by contract/generate.py. CI runs
`generate.py --check`, but `pytest -q tests` did not cover it — so a developer running the suite
locally got false confidence on the most load-bearing invariant. This promotes that gate into the
unit suite and exercises generate.py's own --check branch.

Fails if: a generated file (_contract.py / contract.js) has drifted from columns.json, OR
generate.py's --check stops returning 0 when they are in sync. (Proven non-vacuous: editing
columns.json without regenerating makes main(["--check"]) return 1, failing this test.)
"""
import sys
from pathlib import Path

# contract/ is a sibling of engine/ in the ausmt monorepo: engine/tests/ -> engine/ -> ausmt/ -> contract/.
CONTRACT = Path(__file__).resolve().parents[2] / "contract"
sys.path.insert(0, str(CONTRACT))
import generate  # noqa: E402  (the contract generator; stdlib-only, resolves its paths from __file__)


def test_generated_constants_in_sync_with_columns_json():
    # 0 when _contract.py AND contract.js match columns.json; 1 if either has drifted.
    assert generate.main(["--check"]) == 0
