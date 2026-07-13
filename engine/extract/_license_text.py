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
    from _contract import LICENSES, PROFILES
except ImportError:  # pragma: no cover - exercised only in the installed-package (runner) context
    from extract._contract import LICENSES, PROFILES

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


# C46 (CC-BY 4.0 §3(a) discharge): the default human summary rendered in the changes clause when a
# survey declares no explicit attribution.changes_summary. Factual — it describes what the engine does
# to every deposited transfer function it serves (EMTF-XML regeneration, MTH5, coordinate/identifier
# conditioning). Owner-review wording (flagged in the C46-W2 report); to change it, edit here AND
# regenerate engine/tests/fixtures/license_instrument_vectors.json (both mirrors read the vectors).
DEFAULT_CHANGES_SUMMARY = (
    "the deposited transfer functions were regenerated into AusMT's canonical distribution formats, "
    "and station coordinates, identifiers and metadata were conditioned for release")


def _year4(s) -> str:
    """First run of 4 consecutive digits in a string (a source's `retrieved` date -> its year), else ''."""
    import re  # stdlib, lazy so the leaf's import stays trivially light (D2)
    m = re.search(r"\d{4}", str(s or ""))
    return m.group(0) if m else ""


def _render_profile(profile_key, licensor, year, source_title, derivative) -> str:
    """Render a custodian's required attribution from the generated PROFILES table (C46). Falls back to
    the `generic` profile for an unknown key. The `derivative` form (GA: 'Based on … by GA …') renders
    only when the caller asks for it AND the profile defines one (today only `ga`); otherwise the plain
    `attribution` template renders. Source values are passed as .format ARGUMENTS (never re-parsed), so a
    custodian/title carrying a literal brace cannot break the template or inject a field."""
    prof = PROFILES.get(profile_key) or PROFILES.get("generic") or {}
    tmpl = (prof.get("derivative") if (derivative and prof.get("derivative"))
            else prof.get("attribution")) or "{licensor} ({year})"
    return tmpl.format(licensor=licensor, year=year, source_title=source_title)


def resolve_changes(attribution_block, derived_products):
    """The {made, summary} changes descriptor for license_instrument_text, resolved from a survey's
    attribution block + whether AusMT serves derived renditions of it. `made` = the survey's explicit
    attribution.changes_made when set, else True whenever derived renditions are served (the design's
    'always, once XML/MTH5 serve' rule). Returns None (no clause) when not made. `summary` defaults to
    DEFAULT_CHANGES_SUMMARY when the survey states no attribution.changes_summary."""
    ab = attribution_block or {}
    made = ab.get("changes_made")
    if made is None:
        made = bool(derived_products)
    if not made:
        return None
    summary = str(ab.get("changes_summary") or "").strip() or DEFAULT_CHANGES_SUMMARY
    return {"made": True, "summary": summary}


def instrument_params_from_survey(*, attribution_block, sources_block, derived_products,
                                  synthesized_attribution=None):
    """The (attribution, sources, changes) kwargs for license_instrument_text, derived ONCE from a
    survey's attribution/sources blocks so build_portal (the bundle LICENSE.txt) and the gw-runner (the
    intake LICENSE.md) state IDENTICAL rights for the same survey — the single-source parity the C46 map
    found the two call sites lacked. `attribution` = the custodian's verbatim attribution.statement when
    present, else `synthesized_attribution` (None -> license_instrument_text synthesises who(year))."""
    ab = attribution_block or {}
    statement = str(ab.get("statement") or "").strip()
    return {
        "attribution": statement or synthesized_attribution,
        "sources": list(sources_block) if sources_block else None,
        "changes": resolve_changes(ab, derived_products),
    }


def license_instrument_text(lic, licensor, year, attribution=None, sources=None, changes=None,
                            filename="LICENSE.txt") -> str:
    """C6/C46: the LICENSE.txt that travels INSIDE every distributed survey zip so the rights don't get
    stripped from the bytes. Records the canonical licence id, the licensor (survey custodian org), the
    year (from the survey's date range), an attribution line, and the licence deed URL for CC/ODC ids.
    Deterministic pure text (no timestamps) so the caller can keep the zip byte-reproducible.
    `lic` is passed through canon_license so a bare alias/typo prints its canonical id (or the raw
    normalised value if unrecognised — this file ships only for redistributable surveys, so in practice
    it is always a known id, but it never fabricates a URL for an unknown one).

    C46 additions, appended AFTER the existing attribution block and BYTE-INERT when both are absent:
      * `sources` (list of dicts: title/custodian/identifier/licence/retrieved/statement/profile) — one
        attribution paragraph per upstream dataset, using the source's verbatim `statement` when present
        else the custodian profile's rendered attribution (the GA derivative form when the release makes
        changes), a supersession line for any source whose licence differs from the release licence, and
        (C46-W3a) the custodian profile's s.5 disclaimer paragraph once per distinct disclaimer when a
        source's profile carries one (today only `ga`).
      * `changes` ({made, summary}) — the CC-BY 4.0 §3(a) 'indicate if changes were made' clause.
    When `sources` is falsy and `changes` is falsy/`made` False, the output is byte-identical to the
    pre-C46 instrument (the frozen LICENSE.txt pins)."""
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
    # --- C46 additions (byte-inert when sources + changes are both absent): per-source attribution
    # paragraphs, licence-supersession line(s), then the CC-BY §3(a) changes clause. Order per the
    # C46-W2 contract. The existing None-path `lines` above is untouched, so the frozen pins hold.
    srcs = list(sources or [])
    if srcs:
        made = bool(changes and changes.get("made"))
        lines += ["Source datasets", "-" * len("Source datasets"), ""]
        for s in srcs:
            title = str(s.get("title") or "").strip() or "untitled source dataset"
            cust = str(s.get("custodian") or "").strip() or "unknown custodian"
            ident = str(s.get("identifier") or "").strip()
            slic = canon_license(s.get("licence"))
            head = f"{title} — {cust}" + (f" ({ident})" if ident else "") + f", licensed {slic}."
            statement = str(s.get("statement") or "").strip()
            if statement:
                attr = statement
            else:
                profile_key = str(s.get("profile") or "generic").strip() or "generic"
                syr = _year4(s.get("retrieved")) or yr
                attr = _render_profile(profile_key, cust, syr, title,
                                       derivative=(made and profile_key == "ga"))
            lines += [head, f"  {attr}", ""]
        for s in srcs:
            slic = canon_license(s.get("licence"))
            if slic and slic != cid:
                lines += [f"The upstream dataset was obtained under {slic}; this AusMT release is "
                          f"published by the custodian under {cid}.", ""]
        # C46-W3a: render each custodian profile's s.5-style DISCLAIMER once (dedup, first-seen order) as
        # the final paragraph(s) of the Source-datasets block, when a source's profile carries one (today
        # only `ga`). The disclaimer is a profile-level legal notice distinct from the attribution LINE,
        # so it renders even when a source supplies a verbatim `statement` (which supplants only the line).
        # Byte-inert when no source's profile defines a disclaimer (the generic-only vectors are unchanged).
        _seen_disc: list[str] = []
        for s in srcs:
            profile_key = str(s.get("profile") or "generic").strip() or "generic"
            disc = str((PROFILES.get(profile_key) or {}).get("disclaimer") or "").strip()
            if disc and disc not in _seen_disc:
                _seen_disc.append(disc)
                lines += [disc, ""]
    if changes and changes.get("made"):
        summary = str(changes.get("summary") or "").strip() or DEFAULT_CHANGES_SUMMARY
        lines += [f"Changes were made: {summary}. AusMT serves derived renditions (canonical EMTF XML; "
                  "MTH5 where available) generated from the deposited files; per-station conditioning "
                  "notes are recorded in the machine-readable products.", ""]
    return "\n".join(lines)
