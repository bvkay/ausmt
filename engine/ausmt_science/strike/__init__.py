"""strike: PLANNED science product — NOT yet implemented.

Intended for the MTpy-v2-backed advanced-products layer (see ../decomposition/ for the wiring
pattern). The shipping pipeline (extract/build_portal.py) does not call this module. Marked
explicitly so it is never mistaken for a shipped product; calling write() fails loudly.
"""
from __future__ import annotations


def write(*args, **kwargs):  # noqa: ARG001
    raise NotImplementedError(
        "strike product is planned (MTpy-v2 advanced layer); not implemented yet.")
