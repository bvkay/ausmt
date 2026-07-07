#!/usr/bin/env python3
"""mt_metadata-based EDI extractor — the sole parser since the regex retirement.

Produces a station record dict (`record_from_tf`) and a canonical component dict
(`components_from_tf`) that feed the shared downstream math in `_edi_tf.tf_from_components` and
`_edi_science.science_from_components`. mt_metadata reads each EDI ONCE into a TF object (`read`)
that the record/components/processing helpers all reuse.

mt_metadata is the canonical community model (Kelbert lens) and the basis of the EMTF XML canonical
store (see docs developer/architecture.md).
"""
from __future__ import annotations
import math
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
# mt_metadata logs verbose per-file warnings via loguru; silence them for batch use.
try:
    from loguru import logger as _loguru_logger
    _loguru_logger.disable("mt_metadata")
except Exception:  # noqa: BLE001
    pass

try:
    from mt_metadata.transfer_functions.core import TF
    HAVE_MTM = True
except Exception:  # noqa: BLE001
    HAVE_MTM = False


def available() -> bool:
    return HAVE_MTM


def _read(path: Path):
    tf = TF()
    tf.read(str(path))
    return tf


def read(path: Path):
    """Public single parse of an EDI/MTH5 into a TF object, so callers can parse ONCE and reuse
    it across record_from_tf / components_from_tf / proc_info_from_tf (instead of re-reading the
    file three times)."""
    return _read(path)


def classify(pmin, has_z, has_t):
    """Period-band classifier: AMT (<1e-3 s) / BBMT (<1 s) / LPMT, or GDS for tipper-only."""
    if has_t and not has_z:
        return "GDS"
    if pmin is None:
        return "unknown"
    if pmin < 1e-3:
        return "AMT"
    if pmin < 1.0:
        return "BBMT"
    return "LPMT"


def record_from_tf(tf, file_label: str, *, extractor: str = "mt_metadata") -> dict:
    """Per-station catalogue record (the canonical key set the build pipeline consumes) from a parsed
    TF object — reusable whether the TF came from an EDI or from an MTH5 file."""
    per = tf.period
    has_z = bool(tf.has_impedance())
    has_t = bool(tf.has_tipper())
    pmin = float(per.min()) if per is not None and per.size else None
    pmax = float(per.max()) if per is not None and per.size else None
    comps = []
    if has_z:
        comps.append("Z")
    if has_t:
        comps.append("T")
    lat = tf.latitude
    lon = tf.longitude
    return {
        "id": tf.station or Path(file_label).stem,
        "file": file_label,
        "lat": round(lat, 6) if lat is not None else None,
        "lon": round(lon, 6) if lon is not None else None,
        "elev_m": float(tf.elevation) if getattr(tf, "elevation", None) not in (None, 0) else None,
        "n_periods": int(per.size) if per is not None else 0,
        "period_min_s": round(pmin, 6) if pmin is not None else None,
        "period_max_s": round(pmax, 6) if pmax is not None else None,
        "components": comps,
        "type": classify(pmin, has_z, has_t),
        "coord_flag": None,
        "extractor": extractor,
    }


def parse_edi(path: Path) -> dict:
    """Per-station catalogue record from an EDI, via mt_metadata.

    Coordinates come from the parsed station metadata (mt_metadata reads HEAD LAT/LONG, the
    authoritative field). The DMS sign-bug detection and the processing-note scrape are applied
    separately in build_portal.process_edis (via the kept `_edi_catalog` helpers), not here.
    """
    return record_from_tf(_read(path), path.name)


# mt_metadata / EMTF XML use a large sentinel (~1e32) for MISSING data. Treat any non-physical
# magnitude as missing so a fill never leaks into rho/phase/tipper products — a 1e32 tipper fill
# would otherwise plot as a garbage tip_mag. Real MT impedances/tippers are far below this. (Only
# triggers on EMTF-XML-sourced TFs; an EDI read straight to components carries no values this large.)
_FILL_MAX = 1e8


def _is_missing(zi) -> bool:
    """True if a complex Z/T element is absent, NaN, a non-physical missing-data fill (~1e32), or
    EXACT complex zero. The exact-zero arm is C19b (TAS120 incident, 2026-07-07): mt_metadata
    converts an EDI's 1e32 fills to exact zeros on read, which passed the magnitude threshold and
    plotted as phase=0deg / rho=0 / tipper-dip data points at every source-masked period. A real
    estimated Z/T element is never exactly 0+0j to double precision; a SINGLE zero component
    (e.g. tipper imag crossing 0.0 while real is finite) remains valid data."""
    if zi is None:
        return True
    if isinstance(zi, complex):
        return (math.isnan(zi.real) or math.isnan(zi.imag)
                or abs(zi.real) > _FILL_MAX or abs(zi.imag) > _FILL_MAX
                or (zi.real == 0.0 and zi.imag == 0.0))
    return False


def _z(Z, out, inp):
    """Return the complex array for impedance element (output, input), or None."""
    try:
        return Z.sel(output=out, input=inp).values
    except Exception:  # noqa: BLE001
        return None


def components_from_tf(tf):
    """(periods, canonical component dict) from a parsed TF object — same layout the regex path
    emits, reusable whether the TF came from an EDI or an MTH5 file. ρ/φ from Z, ρ- AND φ-errors
    propagated from impedance_error (linear |dZ| propagation), tipper from Tx/Ty."""
    per = tf.period
    if per is None or not per.size:
        return None, None
    periods = [float(p) for p in per]
    n = len(periods)
    comp = {k: [None] * n for k in (
        "RHOXY", "RHOYX", "PHSXY", "PHSYX", "RHOXY.ERR", "RHOYX.ERR",
        "PHSXY.ERR", "PHSYX.ERR",
        "ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI",
        "TXR", "TXI", "TYR", "TYI")}

    if tf.has_impedance():
        Z = tf.impedance
        Ze = tf.impedance_error if tf.impedance_error is not None else None
        pairs = {"XX": ("ex", "hx"), "XY": ("ex", "hy"), "YX": ("ey", "hx"), "YY": ("ey", "hy")}
        arr = {k: _z(Z, o, i) for k, (o, i) in pairs.items()}
        earr = {k: (_z(Ze, o, i) if Ze is not None else None) for k, (o, i) in pairs.items()}
        for i, T in enumerate(periods):
            for k in ("XX", "XY", "YX", "YY"):
                z = arr[k]
                if z is None:
                    continue
                zi = z[i]
                if _is_missing(zi):
                    continue
                comp["Z" + k + "R"][i] = float(zi.real)
                comp["Z" + k + "I"][i] = float(zi.imag)
            for mode, k in (("XY", "XY"), ("YX", "YX")):
                z = arr[k]
                if z is None or z[i] is None:
                    continue
                zi = z[i]
                if _is_missing(zi):
                    continue
                mag2 = zi.real ** 2 + zi.imag ** 2
                comp["RHO" + mode][i] = 0.2 * T * mag2
                comp["PHS" + mode][i] = math.degrees(math.atan2(zi.imag, zi.real))
                e = earr[k]
                if e is not None and e[i] is not None and not (isinstance(e[i], float) and math.isnan(e[i])):
                    # Standard small-error LINEAR propagation from the impedance error |dZ| (C20):
                    #   rho = 0.2*T*|Z|^2   -> drho  = 0.4*T*|Z|*|dZ|
                    #   phi = atan2(Im,Re)  -> dphi  = degrees(|dZ|/|Z|)
                    # |dZ| is the (real, non-negative) impedance-error magnitude mt_metadata carries
                    # per component. Both errors come from the ONE |dZ| here so rho- and phase-error
                    # cannot diverge; documented in data-files.md.
                    dz = float(abs(e[i]))
                    mag = math.sqrt(mag2)
                    comp["RHO" + mode + ".ERR"][i] = 0.4 * T * mag * dz
                    if mag > 0:
                        comp["PHS" + mode + ".ERR"][i] = math.degrees(dz / mag)

    if tf.has_tipper():
        Tp = tf.tipper
        tpairs = {"TX": ("hz", "hx"), "TY": ("hz", "hy")}
        tarr = {k: _z(Tp, o, i) for k, (o, i) in tpairs.items()}
        for i in range(n):
            for k in ("TX", "TY"):
                z = tarr[k]
                if z is None or z[i] is None:
                    continue
                zi = z[i]
                if _is_missing(zi):
                    continue
                comp[k + "R"][i] = float(zi.real)
                comp[k + "I"][i] = float(zi.imag)

    comp = {k: (v if any(x is not None for x in v) else None) for k, v in comp.items()}
    return periods, comp


def components(path: Path):
    """(periods, canonical component dict) via mt_metadata from an EDI path."""
    return components_from_tf(_read(path))


def proc_info_from_tf(tf):
    """(software, algorithm, remote_reference) from an already-parsed TF object."""
    try:
        tfm = tf.station_metadata.transfer_function
        sw = getattr(getattr(tfm, "software", None), "name", None)
        rr = 1 if (tfm.processing_type and "remote" in str(tfm.processing_type).lower()) else 0
        return (sw or None, str(tfm.processing_type) or None if tfm.processing_type else None, rr)
    except Exception:  # noqa: BLE001
        return (None, None, 0)


def proc_info(path: Path):
    """(software, algorithm, remote_reference) from mt_metadata where present."""
    try:
        return proc_info_from_tf(_read(path))
    except Exception:  # noqa: BLE001
        return (None, None, 0)
