"""Documentation pins for the curator Usage page and the fold settings it depends on.

Each test reads committed text only, so it runs on every checkout without a stack.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCS = _REPO / "docs" / "docs" / "introduction" / "usage-analytics.md"
_README = _REPO / "deploy" / "README.md"
_ENV_EXAMPLE = _REPO / "deploy" / ".env.example"
_C45 = _REPO / "maintainer" / "C45-UsageAnalytics.md"
_FOLD = _REPO / "deploy" / "scripts" / "aggregate_stats.py"

# The superseded daily window, written as a length of days or as one quarter.
_OLD_WINDOW = re.compile(r"\b92[- ]days?\b|\bdefault 92\b|\bKEEP=92\b|roll off after a quarter")


def _read(path: Path) -> str:
    assert path.is_file(), f"this pin runs from a full checkout, never skipped: {path}"
    return path.read_text(encoding="utf-8")


def test_docs_and_settings_state_184_days():
    """The daily window is 184 days by default. No document, setting example, decision record, fold
    comment or gateway source may still state the old 92-day window; the explicit boundary test in
    deploy/tests passes daily_keep=92 on purpose and is not scanned. FAILS IF any scanned file names
    the old window, or if the docs, README or settings example do not state the new one."""
    scanned = [_DOCS, _README, _ENV_EXAMPLE, _C45, _FOLD]
    scanned += [p for p in sorted((_REPO / "gateway").rglob("*.py")) if p != Path(__file__).resolve()]
    offenders = []
    for path in scanned:
        for no, line in enumerate(_read(path).splitlines(), 1):
            if _OLD_WINDOW.search(line):
                offenders.append(f"{path.relative_to(_REPO)}:{no}: {line.strip()}")
    assert offenders == [], "the old daily window is still stated:\n" + "\n".join(offenders)

    assert "| Daily aggregate rows | 184 days |" in _read(_DOCS)
    assert "**184-day**" in _read(_README)
    env = _read(_ENV_EXAMPLE)
    assert "AUSMT_STATS_DAILY_KEEP=184" in env and "default 184" in env
    assert "default 184" in _read(_FOLD)
