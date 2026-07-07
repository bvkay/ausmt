"""decomposition (Tier 3): OPTIONAL. Imports the MTpy-v2 fork lazily so the core
pipeline runs without it. See README.md for the refactor-vs-depend decision.
STATUS: not yet implemented — this is a guarded stub, not working code.
"""
from __future__ import annotations


def available() -> bool:
    try:
        import mtpy  # noqa: F401  (the fork)
        return True
    except Exception:  # noqa: BLE001  (availability probe — any import failure means "not installed")
        return False


def write(tf, out_dir):
    """Write decomposition.json if the engine is installed; otherwise no-op.

    NOT YET IMPLEMENTED: when wired, this calls the fork's Groom-Bailey /
    McNeice-Jones routines and emits the schema in docs developer/product-schema.md.
    """
    if not available():
        return None  # core build proceeds; Tier-3 product simply absent
    raise NotImplementedError("decomposition wiring is planned; see README.md")
