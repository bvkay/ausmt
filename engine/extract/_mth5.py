#!/usr/bin/env python3
"""MTH5 ingestion (Prototype 14, Priority 2 — comparison, not replacement).

MTH5 (the community HDF5 container for MT data) is the standards endpoint Anna Kelbert's lens
points at. Following the strategy that worked for mt_metadata — *add a path, then compare it to
the existing one and gather evidence* — this module:

  * builds an MTH5 file from a set of EDIs (EDI -> mt_metadata TF -> MTH5), and
  * reads transfer functions back out of an MTH5 file into the SAME record + canonical component
    structures the EDI extractors produce (via `_mtm.record_from_tf` / `_mtm.components_from_tf`),
    so MTH5-sourced products run through the identical downstream science.

Because ingestion reuses the shared TF logic, an EDI->MTH5->products result can be compared
directly against EDI->products; any difference is a *storage round-trip* difference — isolated to
how MTH5 stores the TF, since both paths share the one mt_metadata parser and the same downstream
science.

Uses the core `mth5` / `mt_metadata` stack (see the pinned lock in environments/).
"""
from __future__ import annotations
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
try:
    from loguru import logger as _loguru_logger
    _loguru_logger.disable("mth5")
    _loguru_logger.disable("mt_metadata")
except Exception:  # noqa: BLE001
    pass

try:
    from mth5.mth5 import MTH5
    from mt_metadata.transfer_functions.core import TF
    HAVE_MTH5 = True
except Exception:  # noqa: BLE001
    HAVE_MTH5 = False

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mtm  # noqa: E402  (shared TF -> record/components logic)


def available() -> bool:
    return HAVE_MTH5


def build_mth5_from_edis(edi_paths, out_h5: Path, survey_id: str = "ausmt_preview") -> int:
    """EDI -> TF -> MTH5. Returns the number of transfer functions written."""
    out_h5 = Path(out_h5)
    if out_h5.exists():
        out_h5.unlink()
    m = MTH5()
    m.open_mth5(str(out_h5), mode="w")
    n = 0
    try:
        for p in sorted(edi_paths):
            tf = TF()
            tf.read(str(p))
            if not tf.survey_metadata.id or tf.survey_metadata.id == "0":
                tf.survey_metadata.id = survey_id
            m.add_transfer_function(tf)
            n += 1
    finally:
        m.close_mth5()
    return n


def _iter_tf_keys(m):
    """Yield (station_id, tf_id, survey) for every TF in an open MTH5 file."""
    df = m.tf_summary.to_dataframe()
    for _, row in df.iterrows():
        yield row["station"], row.get("tf_id", row["station"]), row.get("survey")


def records_and_components(h5_path: Path):
    """Read every TF from an MTH5 file and yield (record, periods, components), using the SAME
    TF->record/components logic as the EDI path so products are directly comparable."""
    m = MTH5()
    m.open_mth5(str(h5_path), mode="r")
    try:
        for station_id, tf_id, survey in _iter_tf_keys(m):
            tf = m.get_transfer_function(station_id, tf_id, survey=survey)
            label = f"{h5_path.name}::{survey}/{station_id}"
            rec = _mtm.record_from_tf(tf, label, extractor="mth5")
            per, comp = _mtm.components_from_tf(tf)
            yield rec, per, comp
    finally:
        m.close_mth5()
