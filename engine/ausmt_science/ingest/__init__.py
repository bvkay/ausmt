"""ingest: standardise any input (EDI / EMTFXML / Z / J / MTH5) to one TF object.

STATUS: the portal PRODUCTS (catalogue/tf/sci) are built by extract/build_portal.py via the
mt_metadata extractor (`extract/_mtm.py`). This package backs the CANONICAL EMTF XML store (D6):
`normalize` is called by build_portal.emit_canonical_store under `--canonical-dir`. It is the
intended single-choke-point ingest abstraction (numpy/mt_metadata-based) for the canonical/advanced
layers; if you route the portal products through it too, add golden parity tests against the current
extractor outputs first.

Single choke point so every downstream module sees the same interface, regardless of source
format. Prefer mt_metadata (USGS) — it round-trips EDI <-> EMTFXML <-> Z/J and shares the MTH5
schema, so the TF catalogue and the time-series holdings speak the same language.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class TransferFunction:
    """Minimal, library-agnostic TF the rest of the pipeline depends on."""
    ausmt_id: str
    station: str
    survey: str
    lat: float
    lon: float
    elev_m: Optional[float]
    periods: np.ndarray            # (n,)
    z: np.ndarray                  # (n, 2, 2) complex impedance, ohm
    z_err: Optional[np.ndarray]    # (n, 2, 2) real, std errors
    t: Optional[np.ndarray]        # (n, 1, 2) complex tipper, or None
    t_err: Optional[np.ndarray]
    source_path: str
    source_sha256: str
    meta: dict = field(default_factory=dict)

    @property
    def has_tipper(self) -> bool:
        return self.t is not None and np.isfinite(self.t).any()


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(path: str | Path, *, ausmt_id: str, survey: str) -> TransferFunction:
    """Load via mt_metadata; raises on unparseable input (a hard QC gate)."""
    path = Path(path)
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415

    tf = TF(fn=str(path))
    tf.read()
    z = tf.impedance.to_numpy() if hasattr(tf, "impedance") else tf.z
    z_err = getattr(getattr(tf, "impedance_error", None), "to_numpy", lambda: None)()
    has_t = tf.has_tipper()
    return TransferFunction(
        ausmt_id=ausmt_id,
        station=tf.station,
        survey=survey,
        lat=float(tf.latitude),
        lon=float(tf.longitude),
        elev_m=float(tf.elevation) if tf.elevation is not None else None,
        periods=np.asarray(tf.period, dtype=float),
        z=np.asarray(z, dtype=complex),
        z_err=np.asarray(z_err, dtype=float) if z_err is not None else None,
        t=np.asarray(tf.tipper.to_numpy(), dtype=complex) if has_t else None,
        t_err=None,
        source_path=str(path),
        source_sha256=_sha256(path),
        meta={"software": tf.station_metadata.transfer_function.processing_type or None},
    )
