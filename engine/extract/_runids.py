#!/usr/bin/env python3
"""The persistent run-id store a survey package carries beside survey.yaml.

Station-metadata scope section 9: a run id is the SOURCE run id where the instrument metadata
declares one, and otherwise a PERSISTENT CURATED LOCAL id, assigned once and stored, because an id
regenerated from mutable metadata (a timestamp, a rate, a serial, a channel set) silently renames a
run as soon as curation corrects that value. The store is therefore the ONLY id authority the build
has: where it holds no row for a station, that station publishes no runs at all. The engine never
mints one, not even for a station whose source clearly describes an acquisition.

    surveys/<slug>/run-ids.yaml
        run_ids:
          A1:  [A1_001]         # the source's own run id, copied verbatim by the curation tool
          A23: [A23-r01]        # a curated local id, minted from the published station id alone

Shape failures are refused rather than half-applied: a store the build cannot read whole would give
some stations their assigned ids and silently renumber none of the others, which is the one outcome
the assigned-once guarantee exists to prevent.
"""
from __future__ import annotations

from pathlib import Path

STORE_NAME = "run-ids.yaml"


class RunIdError(Exception):
    """The store exists but cannot be read as an id authority."""


def load(pkg_dir) -> dict:
    """{published station id: [ordered run ids]} for one survey package, {} where it carries no
    store. Raises RunIdError on a store that exists and is not readable as one whole mapping."""
    path = Path(pkg_dir) / STORE_NAME
    if not path.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415
    except ModuleNotFoundError:
        raise RunIdError(
            f"{STORE_NAME} needs PyYAML to be read (pip install PyYAML). The stdlib fallback parser "
            f"returns a PARTIAL map, which would publish some stations under their assigned run ids "
            f"and silently drop the rest") from None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise RunIdError(f"{STORE_NAME} is not valid YAML ({e})") from None
    rows = doc.get("run_ids") if isinstance(doc, dict) else None
    if not isinstance(rows, dict):
        raise RunIdError(f"{STORE_NAME} carries no `run_ids` mapping")
    out, seen = {}, {}
    for station, row in rows.items():
        ids = row if isinstance(row, (list, tuple)) else [row]
        clean = [str(i).strip() for i in ids if str(i).strip()]
        if not clean:
            raise RunIdError(f"{STORE_NAME}: station {station!r} has no run id")
        for rid in clean:
            if rid in seen:
                raise RunIdError(f"{STORE_NAME}: run id {rid!r} is assigned to both {seen[rid]!r} "
                                 f"and {station!r}; run ids are unique within the store")
            seen[rid] = str(station)
        out[str(station)] = clean
    return out
