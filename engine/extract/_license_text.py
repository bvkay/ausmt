"""C34/D2 — the single source for AusMT licence primitives + deterministic rights text.

STDLIB-ONLY leaf module (no numpy / mt_metadata / PyYAML): it imports only `_contract`, itself a
stdlib-generated table. This is what lets BOTH sides share one implementation of the rights text:

  * build_portal — the bundle LICENSE.txt that travels inside every distributed survey zip
    (`license_instrument_text`), plus the redistribution allow-list gate (`redistributable`); its
    output stays byte-identical to the pre-C34 in-module version (pinned by
    tests/test_license_gate.py + tests/test_manifest.py).
  * the gw-runner — the LICENSE.md it writes into a submitted package at intake (C34/D1). The runner
    executes on the ENGINE image, where `extract` is an installed package (C37), so
    `from extract._license_text import license_instrument_text` resolves without pulling the heavy
    scientific stack that a `build_portal` import would.

The gateway APP process never imports this module (C10/C31 house rule: the app is content-blind).

The canonical id / alias / URL / allow-list tables all derive from contract/licenses.json via
`_contract.LICENSES` — the ONE place a licence string is canonicalised. Edit contract/licenses.json,
then `python contract/generate.py`; never hand-edit the derived sets here.
"""
from __future__ import annotations

# `_contract` is a SIBLING module (engine/extract/_contract.py). This module is imported in two
# contexts and must resolve `_contract` in BOTH:
#   * as a bare sibling — build_portal runs `sys.path.insert(0, HERE)` before importing us, and the
#     engine test lane puts extract/ on sys.path; then `import _contract` works directly.
#   * as an installed package — the gw-runner does `from extract._license_text import ...` on the
#     engine image (C37). There sys.path holds the package ROOT (engine/), not engine/extract/, so a
#     bare `import _contract` would miss; `from extract._contract` is the resolvable path.
# Try the sibling form first (the pre-existing engine convention), fall back to the package-qualified
# form for the installed-package/runner context. Either way it is stdlib-only content (no heavy deps).
try:
    from _contract import LICENSES
except ImportError:  # pragma: no cover - exercised only in the installed-package (runner) context
    from extract._contract import LICENSES

# C6: normalise a raw survey.yaml licence string to a canonical id for allow-list matching. trim ->
# collapse internal whitespace -> upper, then resolve a legacy bare alias (CC0, CC-BY, ODBL, ...) to
# its canonical id. Allow-list keys and aliases are compared in this same UPPER space, so the match is
# case-insensitive by construction. This is the ONLY place a licence string is canonicalised — the old
# `startswith("CC")` prefix test (which redistributed a typo'd 'CC-BY-4.O' or any 'CC-nonsense') is gone.
_LIC_REDIST = {s.upper() for s in LICENSES["redistributable"]}          # canonical ids, upper
_LIC_RECOGNISED = {s.upper() for s in LICENSES["recognised_only"]} | _LIC_REDIST
_LIC_ALIASES = {k.upper(): v.upper() for k, v in LICENSES["aliases"].items()}  # legacy bare -> canonical, upper
_LIC_URLS = {k.upper(): v for k, v in LICENSES["urls"].items()}         # canonical id (upper) -> deed URL


def canon_license(license_str) -> str:
    """Canonical UPPER id for a raw licence string (trim, collapse internal whitespace, upper, de-alias)."""
    s = " ".join((license_str or "").strip().split()).upper()
    return _LIC_ALIASES.get(s, s)


def redistributable(license_str) -> bool:
    """Only serve TF files whose licence EXACTLY (case-insensitive after trim/whitespace-collapse/de-alias)
    matches the contract/licenses.json redistributable allow-list. Ties the distribution model to licensing
    (the honest gate). 'TBD'/None/unknown/metadata-only -> NOT served (catalogue still lists the station;
    download -> archive). See the DECISION note in contract/licenses.json (NC/ND stay redistributable-verbatim,
    but ONLY via exact ids — killing the pre-C6 typo hole)."""
    return canon_license(license_str) in _LIC_REDIST


def recognised(license_str) -> bool:
    """C34/D3 fail-closed gate for LICENSE.md generation: the id must be a RECOGNISED canonical id
    (redistributable ∪ recognised_only, matched case-insensitively after de-alias). An unrecognised id
    (typo, placeholder 'TBD', free text, None) is NOT recognised, so no LICENSE.md is generated and the
    validator's 'LICENSE.md missing' WARNING correctly stands. Broader than `redistributable`: a
    recognised-but-metadata-only licence (e.g. 'ALL RIGHTS RESERVED', 'CC-BY-NC-3.0') still gets a
    correct rights statement written even though its bytes are not served."""
    return canon_license(license_str) in _LIC_RECOGNISED


def license_instrument_text(lic, licensor, year, attribution=None, filename="LICENSE.txt") -> str:
    """C6: the LICENSE.txt that travels INSIDE every distributed survey zip so the rights don't get
    stripped from the bytes. Records the canonical licence id, the licensor (survey custodian org), the
    year (from the survey's date range), an attribution line, and the licence deed URL for CC/ODC ids.
    Deterministic pure text (no timestamps) so the caller can keep the zip byte-reproducible.
    `lic` is passed through canon_license so a bare alias/typo prints its canonical id (or the raw
    normalised value if unrecognised — this file ships only for redistributable surveys, so in practice
    it is always a known id, but it never fabricates a URL for an unknown one)."""
    cid = canon_license(lic)
    url = _LIC_URLS.get(cid, "")
    who = (licensor or "the survey custodian").strip()
    yr = str(year or "").strip()
    attn = (attribution or f"{who}{(' (' + yr + ')') if yr else ''}").strip()
    lines = [
        "AusMT survey data — licence and attribution",
        "=" * 44,
        "",
        f"Licence:     {cid}",
    ]
    if url:
        lines.append(f"Licence URL: {url}")
    lines += [
        f"Licensor:    {who}",
        f"Year:        {yr or 'not stated'}",
        "",
        "Attribution (cite as):",
        f"  {attn}",
        "",
        f"This {filename} travels with the data files in this archive. The transfer functions were",
        "distributed via the AusMT portal, which serves only openly licensed Australian magnetotelluric",
        "releases; the licence above is the custodian's, set in the survey's survey.yaml. Reuse under the",
        "terms of that licence" + (f" ({url})." if url else "."),
        "",
    ]
    return "\n".join(lines)
