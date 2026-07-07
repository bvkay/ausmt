#!/usr/bin/env python3
"""Build plottable TF data per station: app res, phase, tipper, phase tensor.

`tf_from_components` returns one entry per station as a column set (same order):
  [periods, rho_xy, rho_yx, phs_xy, phs_yx_adj, tip_mag, pt_min, pt_max, pt_az, pt_beta]
Arrays are thinned to <=32 periods and rounded; nulls where data absent/invalid.

The component dict comes from mt_metadata (`_mtm.components_from_tf`); this module turns it into
the plottable row. The phase-tensor math and the impedance->rho/phase fallback live in `_ediparse`
(shared with `_edi_science`), so the TF builder and the science layer cannot diverge. Public
surface: `tf_from_components(periods, comp)`.
"""
import math

import _ediparse as ep  # noqa: E402  (shared math: pt_params/drho/dphase/EMPTY_TF)

# Authoritative tf.json column order (each entry is a list of these 10 column-arrays) — SINGLE-SOURCED
# in contract/columns.json, imported here. Consumed BY POSITION by the portal (portal/src/contract.js
# T.* map). Regenerate with `python contract/generate.py`. APPEND, never reorder.
from _contract import TF_COLUMNS  # noqa: E402, F401  (re-exported as tfmod.TF_COLUMNS for compare_mth5)


def pt_params(zxxr, zxxi, zxyr, zxyi, zyxr, zyxi, zyyr, zyyi):
    """Caldwell phase tensor for the plottable TF row — delegates to the single implementation in
    `_ediparse.pt_params` and rounds to 1 dp. (No phase-tensor math lives here anymore.)"""
    r = ep.pt_params(zxxr, zxxi, zxyr, zxyi, zyxr, zyxi, zyyr, zyyi)
    return tuple(round(v, 1) if v is not None else None for v in r)


def sig(x, n=4):
    if x is None:
        return None
    if x == 0:
        return 0
    return round(x, max(0, n - 1 - int(math.floor(math.log10(abs(x))))))


def norm_phase(p, add=0.0):
    if p is None:
        return None
    p = p + add
    p = ((p + 180.0) % 360.0) - 180.0
    return round(p, 1)


def tf_from_components(periods, comp):
    """Compute the plottable tf row from a canonical component dict (built by mt_metadata via
    `_mtm.components_from_tf`). The component dict is the single seam between parsing and the TF
    math, so this computation is independent of how the EDI was read."""
    if not periods:
        return None
    rxy, ryx = comp.get("RHOXY"), comp.get("RHOYX")
    pxy, pyx = comp.get("PHSXY"), comp.get("PHSYX")
    zxxr, zxxi = comp.get("ZXXR"), comp.get("ZXXI")
    zxyr, zxyi = comp.get("ZXYR"), comp.get("ZXYI")
    zyxr, zyxi = comp.get("ZYXR"), comp.get("ZYXI")
    zyyr, zyyi = comp.get("ZYYR"), comp.get("ZYYI")
    txr, txi = comp.get("TXR"), comp.get("TXI")
    tyr, tyi = comp.get("TYR"), comp.get("TYI")

    # Fallback: some EDIs (e.g. impedance-only EDL/BIRRP) carry Z but omit the derived
    # RHOXY/PHSXY blocks. Compute rho = 0.2*T*|Z|^2 and phi = atan2(Im,Re) from impedance so the
    # apparent-resistivity / phase curves still render. EDIs that DO provide the blocks are
    # unchanged (Vulcan golden), since the fallback only fills a missing mode. (`drho`/`dphase`
    # are shared with the science layer via `_ediparse`.)
    if not rxy and zxyr and zxyi:
        rxy = ep.drho(periods, zxyr, zxyi)
    if pxy is None and zxyr and zxyi:
        pxy = ep.dphase(periods, zxyr, zxyi)
    if not ryx and zyxr and zyxi:
        ryx = ep.drho(periods, zyxr, zyxi)
    if pyx is None and zyxr and zyxi:
        pyx = ep.dphase(periods, zyxr, zyxi)

    n = len(periods)

    def at(arr, i):
        return arr[i] if arr and i < len(arr) else None

    rows = []
    for i in range(n):
        per = periods[i]
        if per is None or per <= 0:
            continue
        tip = None
        if txr and at(txr, i) is not None:
            comps = [at(a, i) for a in (txr, txi, tyr, tyi)]
            if all(c is not None for c in comps):
                tip = round(math.sqrt(sum(c * c for c in comps)), 3)
        pt = (None,) * 4
        if zxyr and at(zxyr, i) is not None:
            zv = [at(a, i) for a in (zxxr, zxxi, zxyr, zxyi, zyxr, zyxi, zyyr, zyyi)]
            if all(v is not None for v in zv):
                pt = pt_params(*zv)
        r_xy, r_yx = at(rxy, i), at(ryx, i)
        rows.append([
            sig(per), sig(r_xy if r_xy and r_xy > 0 else None),
            sig(r_yx if r_yx and r_yx > 0 else None),
            norm_phase(at(pxy, i)), norm_phase(at(pyx, i), add=180.0),
            tip, *pt,
        ])

    rows.sort(key=lambda r: r[0])
    if len(rows) > 32:  # thin, keeping endpoints
        step = (len(rows) - 1) / 31.0
        rows = [rows[round(k * step)] for k in range(32)]
    cols = list(map(list, zip(*rows))) if rows else ep.EMPTY_TF
    return cols
