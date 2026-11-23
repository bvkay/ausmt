"""The operator network list stays private to the host that folds the statistics.

Its default path must sit outside the gateway state directory (which backup.sh snapshots and the
gateway mounts) and outside every compose volume source, so no route or container can read it, and
deploy/.env.example may name its variable but never carry a value.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_DEPLOY = Path(__file__).resolve().parents[1]
_SCRIPT = _DEPLOY / "scripts" / "aggregate_stats.py"


def _load_agg():
    spec = importlib.util.spec_from_file_location("aggregate_stats", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AGG = _load_agg()
_DATA = Path("/srv/ausmt-example")


def _compose_sources() -> list[str]:
    """Every host-side volume source under $AUSMT_DATA_DIR in compose.yaml, relative to it."""
    text = (_DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    return re.findall(r"\$\{AUSMT_DATA_DIR[^}]*\}/([^:\s]+):", text)


def test_operator_list_default_path_outside_gateway_state_and_compose_mounts():
    """Fails if the default list path moves under the gateway state dir, under any compose volume
    source, or under the published site-data tree."""
    path = AGG._default_operator_list(str(_DATA))
    rel = path.relative_to(_DATA)
    assert rel == Path("stats-private") / "operator-networks.txt"
    backup = (_DEPLOY / "backup.sh").read_text(encoding="utf-8")
    assert 'STATE_DIR="$AUSMT_DATA_DIR/gateway/state"' in backup
    assert not rel.is_relative_to(Path("gateway") / "state")
    sources = _compose_sources()
    assert "gateway/state" in sources and "site-data" in sources, sources
    for src in sources:
        assert not rel.is_relative_to(Path(src)), src
    assert "stats-private" not in (_DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    # The stats state dir, the fold's other default, is not where the list lives either.
    stats_default = _DATA / "gateway" / "state" / "stats.json"
    assert not path.is_relative_to(stats_default.parent)


def test_env_example_names_operator_variable_without_value():
    """deploy/.env.example names the label settings commented out and with no value, so copying the
    example can neither switch labels on nor point the fold at a list."""
    text = (_DEPLOY / ".env.example").read_text(encoding="utf-8")
    for name in ("AUSMT_STATS_OPERATOR_NETWORKS", "AUSMT_STATS_LABELS_FROM"):
        lines = [ln for ln in text.splitlines() if name in ln]
        assert lines, name
        for ln in lines:
            assert ln.lstrip().startswith("#"), ln
            m = re.search(r"%s=(\S*)" % name, ln)
            if m:
                assert m.group(1) == "", ln
