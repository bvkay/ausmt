"""C34/D2 — the stdlib-only _license_text leaf is the SINGLE SOURCE of the licence rights text and
the recognised-id gate, shared by build_portal (bundle LICENSE.txt) and the gw-runner (intake
LICENSE.md). These tests pin that the extraction did not change behaviour and that the new gate is
correct.

NON-VACUOUS failure criteria:
  * _license_text.license_instrument_text is byte-identical to build_portal.license_instrument_text
    for a spread of ids — proves build_portal now delegates to the leaf, not a divergent copy
    (FAILS if build_portal re-grows its own text or the leaf drifts).
  * _license_text imports NOTHING from the heavy scientific stack (numpy/mt_metadata/PyYAML) — that
    is the whole point of the leaf (the runner must import it without the engine build stack). FAILS
    if an import of the leaf drags in a heavy module.
  * recognised() accepts redistributable AND metadata-only ids, rejects typos/placeholders/None —
    the fail-closed D3 gate for LICENSE.md generation (FAILS against a startswith or a too-broad gate).
Stdlib only.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))
import _license_text as lt   # noqa: E402
import build_portal as bp    # noqa: E402


def test_leaf_text_is_byte_identical_to_build_portal():
    # The single-source proof: for every id/licensor/year combination, the leaf and build_portal must
    # produce the SAME bytes. build_portal now imports the leaf, so this is really "the delegation is
    # in place and nothing shadows it". FAILS if build_portal re-defines its own license_instrument_text.
    cases = [
        ("CC-BY-4.0", "Geoscience Australia", "2019"),
        ("CC-BY", "Custodian", ""),                       # bare alias -> canonical + URL
        ("CC0-1.0", "AusMT CI", "2021"),
        ("ODBL", "Data Org", "2010"),                     # alias, deed URL
        ("PUBLIC DOMAIN", "Nobody", ""),                  # recognised, no URL
        ("ALL RIGHTS RESERVED", "Closed Co", "2024"),     # recognised metadata-only, no URL
        ("totally-unknown-licence", "X", "2000"),         # unknown: normalised, no fabricated URL
    ]
    for lic, who, yr in cases:
        assert lt.license_instrument_text(lic, who, yr) == bp.license_instrument_text(lic, who, yr), lic


def test_build_portal_delegates_to_the_same_object():
    # Belt to the byte test: build_portal.license_instrument_text IS the leaf's function object (the
    # import binding), not a copy. FAILS if build_portal ever redefines it locally again.
    assert bp.license_instrument_text is lt.license_instrument_text
    assert bp.redistributable is lt.redistributable


def test_leaf_is_stdlib_only_no_heavy_stack():
    # The leaf's whole purpose (D2) is that the runner can import it WITHOUT the engine build stack.
    # Import it in a fresh subprocess with only extract/ on the path and assert none of numpy /
    # mt_metadata / mth5 / yaml were pulled in as a side effect. FAILS if the leaf grows a heavy import.
    import subprocess
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import _license_text;"
        "bad=[m for m in ('numpy','mt_metadata','mth5','yaml','ruamel') if m in sys.modules];"
        "print('LOADED_HEAVY:'+','.join(bad) if bad else 'CLEAN')"
    ) % str(ROOT / "extract")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "CLEAN" in r.stdout, r.stdout


def test_recognised_gate_accepts_recognised_rejects_unknown():
    # D3 fail-closed gate for LICENSE.md generation.
    assert lt.recognised("CC-BY-4.0")                      # redistributable
    assert lt.recognised("cc-by-4.0")                      # case-insensitive
    assert lt.recognised("CC-BY")                          # bare alias -> canonical
    assert lt.recognised("ALL RIGHTS RESERVED")            # recognised metadata-only (still gets a rights file)
    assert lt.recognised("CC-BY-NC-3.0")                   # recognised metadata-only
    assert not lt.recognised("CC-BY-4.O")                  # typo (letter O) -> NOT recognised
    assert not lt.recognised("TBD by uploader")            # placeholder -> NOT recognised
    assert not lt.recognised("")                           # empty
    assert not lt.recognised(None)                         # None
    assert not lt.recognised("CC-nonsense")                # free text


def test_recognised_is_broader_than_redistributable():
    # A recognised metadata-only id is recognised (gets a LICENSE.md rights statement) but NOT
    # redistributable (its bytes are not served). The two gates are distinct on purpose.
    assert lt.recognised("ALL RIGHTS RESERVED") and not lt.redistributable("ALL RIGHTS RESERVED")
    assert lt.recognised("CC-BY-NC-3.0") and not lt.redistributable("CC-BY-NC-3.0")
