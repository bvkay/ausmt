#!/usr/bin/env python3
"""Tier-3 entity landing pages: one static HTML document per survey, station and collection,
served at the path-URL contract's own shapes (/surveys/<slug>, /stations/<ausmt_id>,
/collections/<id>).

Every page is rendered ONLY from the already-served public documents (surveys.json entries,
survey-metadata.json, station.json, the collections rollup, the manifest's bundle rows and the
time-series register), so a page can never disclose anything the gated products do not already
publish; the C42 posture is inherited, and the coord-access whole-tree sweep audits pages/ like
every other emitter. All free text is HTML-escaped (curator-authored YAML is still a public
serving surface), and the JSON-LD block escapes "</" so document text can never close the
script element.

Survey pages carry the full design of record: citation box (surname-plus-initial authors),
location minimap on the shared schematic outline (_au_outline, the same geometry the portal's
collections view draws), footprint zoom for compact surveys, stat tiles, per-level download
panels with manifest sizes and checksums, grouped contributors, publications, and the wide
station table (horizontal scroll, sticky station column) whose run columns render from the
station documents' own runs[]. Time-series panels and cells render ONLY the levels the served
register carries. NO em/en dashes and NO tick glyphs anywhere: ranges say "to", absent cells
are plain hyphens, availability is stated as data (sizes), per the owner's rulings.

Per-survey link-preview cards (og:image) are rendered when Pillow is importable; without it
every entity page falls back to the portal's root card. Both paths emit the og/twitter tags.

Stdlib only (Pillow soft-gated), deliberately: this is a leaf like _license_text, importable by
the spawn workers' build_portal without extra weight.
"""
from __future__ import annotations

import html
import json
import re

import _au_outline as au

_LICENSE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
}

# Keys as the MANIFEST bundle rows spell them ("mth5", not the station-resource id
# "survey-mth5"; the two vocabularies differ and the manifest is what this emitter reads).
_BUNDLE_LABELS = {
    "edi-zip": ("EDI archive (zip)", "application/zip"),
    "xml-zip": ("EMTF XML archive (zip)", "application/zip"),
    "mth5": ("Survey MTH5 bundle", "application/x-hdf5"),
    "survey-mth5": ("Survey MTH5 bundle", "application/x-hdf5"),
}

# The register's level keys, in publication level order, with their page names.
_TS_LEVELS = (("level0", "L0", "Raw time series"),
              ("raw_packed", "L0", "Raw time series (packed archives)"),
              ("level1_mth5", "L1", "MTH5 time series"))

_ROLE_LABELS = {"ProjectLeader": "Project Leader", "ProjectMember": "Project Member",
                "DataCollector": "Data Collector", "DataCurator": "Data Curator",
                "ContactPerson": "Contact", "RightsHolder": "Rights Holder",
                "Distributor": "Distributor"}


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _jsonld(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1).replace("</", "<\\/")


def _initials(authors) -> str:
    """"Kay, Ben; Heinson, Graham" -> "Kay, B.; Heinson, G." An entry without a comma (an
    organisation) passes through verbatim."""
    out = []
    for raw_entry in str(authors or "").split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "," in entry:
            last, _, given = entry.partition(",")
            initials = " ".join(f"{g[0]}." for g in given.split() if g)
            out.append(f"{last.strip()}, {initials}" if initials else last.strip())
        else:
            out.append(entry)
    return "; ".join(out)


def _fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.1f} MB"
    return f"{n / 1e3:.0f} KB"


def _fmt_period(v) -> str:
    """A period in seconds, printed the way the portal writes them (no dash glyphs anywhere)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v >= 1000:
        return f"{v:,.0f}"
    if v >= 1:
        return f"{v:g}"
    return f"{v:g}"


def _doi_url(identifier) -> str | None:
    """A related identifier as a resolvable URL. Bare DOIs resolve via doi.org; a value already
    carrying a scheme is used as-is (one corpus row is a full dx.doi.org URL)."""
    v = str(identifier or "").strip()
    if not v:
        return None
    if v.startswith(("http://", "https://")):
        return v
    return f"https://doi.org/{v}"


def _bare_doi(identifier) -> str | None:
    v = str(identifier or "").strip()
    v = re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", v, flags=re.IGNORECASE)
    return v or None


# --------------------------------------------------------------------------- SVG map panels

def _proj(extent):
    w, e, s, n = extent["w"], extent["e"], extent["s"], extent["n"]

    def to(width, height, pad):
        def p(lon, lat):
            x = pad + (lon - w) / (e - w) * (width - 2 * pad)
            y = pad + (n - lat) / (n - s) * (height - 2 * pad)
            return round(x, 1), round(y, 1)
        return p
    return to


def _minimap_svg(points, *, width=230) -> str:
    """The location minimap: the shared schematic outline with this survey's stations. The
    projection is the portal collections view's own fixed-extent equirectangular fit, so the two
    surfaces draw one map."""
    ext = au.EXTENT
    height = round(width * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))
    p = _proj(ext)(width, height, 8)

    def path(ring, close=True):
        d = "M" + "L".join(f"{x},{y}" for x, y in (p(lo, la) for lo, la in ring))
        return d + ("Z" if close else "")
    coast = "".join(f'<path d="{path(r)}" fill="#1d3140" stroke="#3a5266" stroke-width="1"/>'
                    for r in au.COAST)
    borders = "".join(f'<path d="{path(r, False)}" fill="none" stroke="#3a5266" '
                      f'stroke-width=".8" stroke-dasharray="3 3"/>' for r in au.BORDERS)
    dots = "".join(f'<circle cx="{p(lo, la)[0]}" cy="{p(lo, la)[1]}" r="2" fill="#4FC3D9" '
                   f'fill-opacity=".9"/>' for lo, la in points)
    marker = ""
    if points and len(points) < 400:
        clon = sum(lo for lo, _la in points) / len(points)
        clat = sum(la for _lo, la in points) / len(points)
        mx, my = p(clon, clat)
        marker = (f'<circle cx="{mx}" cy="{my}" r="9" fill="none" stroke="#EF7256" '
                  f'stroke-width="1.4" opacity=".65"/>')
    return (f'<svg viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="Survey location in Australia" '
            f'style="background:#16242f;border:1px solid #2B3557;border-radius:8px">'
            f'{coast}{borders}{dots}{marker}</svg>')


def _footprint_svg(points, *, width=230) -> str:
    """The station-grid zoom for a compact survey, aspect-fit to the survey's own bbox."""
    lons = [lo for lo, _la in points]
    lats = [la for _lo, la in points]
    lo0, lo1, la0, la1 = min(lons), max(lons), min(lats), max(lats)
    dlo, dla = max(lo1 - lo0, 1e-6), max(la1 - la0, 1e-6)
    height = max(70, min(320, int(width * dla / dlo)))
    pad = 0.12

    def p(lon, lat):
        x = (lon - lo0) / dlo * (1 - 2 * pad) * width + pad * width
        y = (la1 - lat) / dla * (1 - 2 * pad) * height + pad * height
        return round(x, 1), round(y, 1)
    dots = "".join(f'<circle cx="{p(lo, la)[0]}" cy="{p(lo, la)[1]}" r="2.1"/>'
                   for lo, la in points)
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Station grid detail" '
            f'style="background:#16242f;border:1px solid #2B3557;border-radius:8px">'
            f'<g fill="#4FC3D9">{dots}</g></svg>')


# --------------------------------------------------------------------------- page shell

_CSS = """
  body{margin:0;background:#11182D;color:#C9D4E8;font:16px/1.55 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
  main{max-width:840px;margin:0 auto;padding:1.6rem 1.25rem 3rem}
  a{color:#EF7256}
  h1{color:#fff;font-size:1.7rem;margin:.5rem 0 .3rem}
  h2{color:#fff;font-size:1.12rem;margin:1.7rem 0 .5rem}
  .crumb{font-size:.85rem;opacity:.8}
  .crumb a{opacity:1}
  .pagenav{display:flex;gap:.6rem;margin:.2rem 0 .6rem}
  .navbtn{background:#18213D;border:1px solid #2B3557;border-radius:999px;color:#C9D4E8;font-size:.85rem;padding:.35rem .9rem;text-decoration:none}
  .navbtn.map{color:#EF7256}
  .cite{background:#18213D;border:1px solid #2B3557;border-radius:6px;padding:.7rem .9rem;font-size:.88rem;margin:1rem 0}
  .cite code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem;color:#C9D4E8}
  .embargo{background:#3a2a1a;border:1px solid #7a5a2a;border-radius:6px;padding:.6rem .9rem;margin:.8rem 0;color:#e8d5b5;font-size:.9rem}
  .hero{display:grid;grid-template-columns:1fr 240px;gap:1.2rem;align-items:start;margin:.8rem 0}
  .hero-maps{display:flex;flex-direction:column;gap:.5rem}
  .hero-maps svg{width:100%;height:auto;display:block}
  .mapcap{font-size:.72rem;color:#8FA3B0;font-family:ui-monospace,Menlo,monospace}
  @media(max-width:640px){.hero{grid-template-columns:1fr}}
  .cstats{display:flex;flex-wrap:wrap;gap:.6rem;margin:1rem 0}
  .cstat{background:#18213D;border:1px solid #2B3557;border-radius:8px;padding:.55rem .9rem;min-width:96px}
  .cnum{color:#fff;font-size:1.15rem;font-weight:650;font-variant-numeric:tabular-nums}
  .clab{color:#8FA3B0;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em}
  dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:1rem 0}
  dt{color:#8FA3B0}
  dd{margin:0}
  .lvl{border:1px solid #2B3557;border-radius:8px;padding:.7rem .9rem;margin:.6rem 0}
  .lvlhead{display:flex;align-items:center;gap:.6rem;margin-bottom:.35rem}
  .lvlbadge{font-family:ui-monospace,Menlo,monospace;font-size:.72rem;font-weight:600;background:#1E2B4F;border:1px solid #2B3557;border-radius:4px;padding:.1rem .45rem;color:#4FC3D9}
  .lvlname{color:#fff;font-weight:600;font-size:.95rem}
  .dtbl{border-collapse:collapse;font-size:.88rem;font-variant-numeric:tabular-nums;width:100%}
  .dtbl td{padding:.24rem .8rem .24rem 0;border-bottom:1px solid #1E2B4F}
  .dtbl tr:last-child td{border-bottom:none}
  .dtbl td:nth-child(2),.dtbl td:nth-child(3){font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.78rem;color:#8FA3B0}
  .doi{font-size:.8rem;color:#8FA3B0;margin-top:.35rem}
  .doi a{color:#4FC3D9}
  .people{display:flex;flex-direction:column;gap:.35rem;margin:.6rem 0;font-size:.88rem}
  .person{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem}
  .orcid{font-family:ui-monospace,Menlo,monospace;font-size:.7rem;color:#4FC3D9}
  .rolechip{font-size:.68rem;background:#1E2B4F;border:1px solid #2B3557;border-radius:3px;padding:.05rem .4rem;color:#8FA3B0}
  .pub{font-size:.88rem;margin:.4rem 0}
  .pub i{color:#8FA3B0}
  .stbl{border-collapse:collapse;width:100%;font-size:.82rem;font-variant-numeric:tabular-nums;min-width:1180px}
  .stbl th{text-align:left;color:#8FA3B0;font-weight:600;padding:.3rem .5rem .3rem 0;border-bottom:1px solid #2B3557;position:sticky;top:0;background:#11182D}
  .stbl td{padding:.2rem .5rem .2rem 0;border-bottom:1px solid #1E2B4F}
  .stbl th:first-child,.stbl td:first-child{position:sticky;left:0;background:#11182D;z-index:2;padding-left:.2rem}
  .stbl th:first-child{z-index:3}
  .stbl td:nth-child(2),.stbl td:nth-child(3),.stbl td:nth-child(4),.stbl td:nth-child(5){font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.76rem}
  .pidcell,.pidcell a{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.74rem;color:#4FC3D9}
  .ts-y{color:#5BAE6A;font-family:ui-monospace,Menlo,monospace;font-size:.76rem}
  .ts-n{color:#8FA3B0}
  .scroll{max-height:360px;overflow:auto;border:1px solid #2B3557;border-radius:6px;padding:0 .8rem}
  ul{padding-left:1.2rem}
  footer{margin-top:2.2rem;font-size:.8rem;opacity:.7}
"""


def _shell(*, title, description, canonical, body, jsonld=None, noindex=False,
           og_image=None, base="") -> str:
    ld = f'<script type="application/ld+json">{_jsonld(jsonld)}</script>\n' if jsonld else ""
    # noindex: the page exists for the URL contract and for humans following published links, but
    # is deliberately kept out of the search index (station pages: thousands of templated
    # documents would read as thin content at scale and dilute the survey/collection pages that
    # carry the ranking).
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    # Link previews: crawlers resolve nothing relative, so og:url/og:image are absolute.
    image = og_image or (f"{base}/vendor/social-card.png" if base else None)
    og = ""
    if image:
        og = (f'<meta property="og:type" content="website">\n'
              f'<meta property="og:title" content="{_e(title)}">\n'
              f'<meta property="og:description" content="{_e(description)}">\n'
              f'<meta property="og:url" content="{_e(canonical)}">\n'
              f'<meta property="og:image" content="{_e(image)}">\n'
              f'<meta name="twitter:card" content="summary_large_image">\n')
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"{robots}"
        f"<title>{_e(title)}</title>\n"
        f'<meta name="description" content="{_e(description)}">\n'
        f'<link rel="canonical" href="{_e(canonical)}">\n'
        f"{og}"
        f"{ld}"
        f"<style>{_CSS}</style>\n</head>\n<body>\n<main>\n"
        f"{body}"
        "\n<footer>AusMT - Australia's Magnetotelluric Data Portal - an AuScope service. "
        "Data licences vary by survey; each download carries its licence.</footer>\n"
        "</main>\n</body>\n</html>\n"
    )


def _survey_years(sm_doc, smeta):
    cov = ((sm_doc or {}).get("dates") or {}).get("coverage") or {}
    y0 = cov.get("year_start") or (smeta or {}).get("year_start")
    y1 = cov.get("year_end") or (smeta or {}).get("year_end")
    if y0 and y1:
        return f"{y0}" if y0 == y1 else f"{y0} to {y1}"
    return str(y0 or y1 or "")


def _station_points(docs):
    pts = []
    for doc in docs:
        loc = doc.get("location") or {}
        if loc.get("lat") is not None and loc.get("lon") is not None:
            pts.append((float(loc["lon"]), float(loc["lat"])))
    return pts


def _run_summary(docs):
    """(sample rates set, dipole lengths list) across the survey's published runs."""
    rates, dipoles = set(), []
    for doc in docs:
        for run in doc.get("runs") or []:
            if run.get("sample_rate_hz"):
                rates.add(run["sample_rate_hz"])
            for ch in run.get("channels") or []:
                if ch.get("component", "").startswith("e") and ch.get("dipole_length_m"):
                    dipoles.append(float(ch["dipole_length_m"]))
    return rates, dipoles


def _person_rows(contributors):
    """Contributors grouped by (name, orcid), roles in first-seen order, names as initials."""
    order, roles, orcids = [], {}, {}
    for c in contributors or []:
        name = (c or {}).get("name") or ""
        if not name:
            continue
        key = name
        if key not in roles:
            order.append(key)
            roles[key] = []
            orcids[key] = (c or {}).get("orcid")
        role = _ROLE_LABELS.get((c or {}).get("role") or "", (c or {}).get("role"))
        if role and role not in roles[key]:
            roles[key].append(role)
    rows = []
    for name in order:
        chips = "".join(f'<span class="rolechip">{_e(r)}</span>' for r in roles[name])
        orcid = (f'<a class="orcid" href="https://orcid.org/{_e(orcids[name])}">{_e(orcids[name])}</a>'
                 if orcids[name] else "")
        rows.append(f'<div class="person"><span>{_e(_initials(name))}</span>{orcid}{chips}</div>')
    return rows


def _ts_survey_rows(slug, ts_access):
    """{level key: {aid: row}} for one survey, from the served register."""
    out: dict = {}
    prefix = None
    for aid, levels in (ts_access or {}).items():
        parts = aid.split(".")
        if len(parts) == 3 and parts[1] == slug:
            prefix = True
            for level, row in (levels or {}).items():
                out.setdefault(level, {})[aid] = row
    return out if prefix else out


def _related_by_identifies(smeta):
    out = {}
    for row in (smeta or {}).get("related_identifiers") or []:
        key = (row or {}).get("identifies")
        if key and key not in out:
            out[key] = row
    return out


def survey_page(*, slug, label, sm_doc, smeta, station_docs, bundle_rows, ts_access,
                base, extent=None) -> str:
    smeta = smeta or {}
    title = ((sm_doc or {}).get("title")) or label
    blurb = smeta.get("blurb") or ""
    org = smeta.get("org") or ""
    lic = smeta.get("lic") or ""
    region = smeta.get("region") or "Australia"
    version = smeta.get("version") or ""
    years = _survey_years(sm_doc, smeta)
    url = f"{base}/surveys/{slug}"
    desc = (blurb or f"Magnetotelluric survey data: {title}.").strip()
    desc_meta = (desc[:157] + "...") if len(desc) > 160 else desc
    docs = sorted(station_docs, key=lambda d: str(d.get("station") or d.get("ausmt_id")))
    n_stations = len(docs)

    # ---- aggregates from the served station documents ----
    type_counts: dict = {}
    pmin = pmax = None
    tipper = 0
    for doc in docs:
        data = doc.get("data") or {}
        t = data.get("type")
        if t:
            type_counts[t] = type_counts.get(t, 0) + 1
        for key, cmp_ in (("period_min_s", min), ("period_max_s", max)):
            v = data.get(key)
            if v is not None:
                if key == "period_min_s":
                    pmin = v if pmin is None else min(pmin, v)
                else:
                    pmax = v if pmax is None else max(pmax, v)
        if ((doc.get("diagnostics") or {}).get("tipper_available")):
            tipper += 1
    rates, dipoles = _run_summary(docs)
    points = _station_points(docs)

    # ---- JSON-LD ----
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": f"{title} magnetotelluric survey",
          "description": desc, "url": url,
          "identifier": url,
          "isAccessibleForFree": True,
          "includedInDataCatalog": {"@type": "DataCatalog", "name": "AusMT", "url": base + "/"},
          "measurementTechnique": "magnetotellurics",
          "variableMeasured": "magnetotelluric transfer function",
          "keywords": ["magnetotellurics", "MT", "transfer function", "geophysics", "Australia"]}
    if org:
        creator = {"@type": "Organization", "name": org}
        if smeta.get("org_ror"):
            creator["sameAs"] = smeta["org_ror"]
        ld["creator"] = creator
    if lic:
        ld["license"] = _LICENSE_URLS.get(lic, lic)
    if version:
        ld["version"] = str(version)
    if years:
        ld["temporalCoverage"] = years.replace(" to ", "/")
    same_as = [u for u in (_doi_url((row or {}).get("identifier"))
                           for row in (smeta.get("related_identifiers") or [])) if u]
    if same_as:
        ld["sameAs"] = same_as
    pubs = smeta.get("pubs") or []
    if pubs:
        ld["citation"] = [{"@type": "ScholarlyArticle", "name": p.get("t"),
                           **({"sameAs": _doi_url(p["doi"])} if p.get("doi") else {})}
                          for p in pubs if p.get("t")]
    funders = smeta.get("funders") or []
    if funders:
        ld["funder"] = [{"@type": "Organization", "name": f.get("name"),
                         **({"sameAs": f["pid"]} if f.get("pid") else {})}
                        for f in funders if f.get("name")]
    # spatialCoverage: the DECLARED extent tuple (west, east, south, north) from _extent_of when
    # the survey declares one, else the bbox of the served (posture-filtered) station positions.
    box = None
    if extent and len(extent) == 4:
        w, e_, s, n = extent
        box = (s, w, n, e_)
    elif points:
        lons = [lo for lo, _la in points]
        lats = [la for _lo, la in points]
        box = (min(lats), min(lons), max(lats), max(lons))
    if box:
        ld["spatialCoverage"] = {"@type": "Place", "geo": {
            "@type": "GeoShape", "box": f"{box[0]} {box[1]} {box[2]} {box[3]}"}}

    # ---- downloads: level panels ----
    dist = []
    ts_rows = _ts_survey_rows(slug, ts_access)
    panels = []
    for level_key, badge, name in _TS_LEVELS:
        rows = ts_rows.get(level_key)
        if not rows:
            continue
        total = sum((r or {}).get("bytes") or 0 for r in rows.values())
        per = (f", about {_fmt_bytes(total / len(rows))} per station" if total else "")
        related = _related_by_identifies(smeta)
        doi_bits = []
        if related.get("raw_packed") and badge == "L0":
            u = _doi_url(related["raw_packed"].get("identifier"))
            if u:
                doi_bits.append(f'Archive release: <a href="{_e(u)}">{_e(_bare_doi(related["raw_packed"].get("identifier")) or u)}</a>')
        if related.get("collection"):
            u = _doi_url(related["collection"].get("identifier"))
            if u:
                doi_bits.append(f'part of <a href="{_e(u)}">{_e(_bare_doi(related["collection"].get("identifier")) or u)}</a>')
        doi_line = f'<div class="doi">{" &#183; ".join(doi_bits)}</div>' if doi_bits else ""
        panels.append(
            f'<div class="lvl"><div class="lvlhead"><span class="lvlbadge">{badge}</span>'
            f'<span class="lvlname">{_e(name)}</span></div>'
            f'<p style="margin:.2rem 0;font-size:.9rem">Hosted at NCI for '
            f'<b style="color:#fff">{len(rows)} of {n_stations} stations</b>{per}. '
            f'Build a download script from the <a href="/">interactive portal</a>.</p>'
            f"{doi_line}</div>")
    bundle_items = []
    for row in sorted(bundle_rows or [], key=lambda r: (r or {}).get("format") or ""):
        fmt = (row or {}).get("format")
        lbl, mime = _BUNDLE_LABELS.get(fmt, (fmt, "application/octet-stream"))
        rel = (row or {}).get("url") or ""
        size = _fmt_bytes(row.get("size"))
        sha = str(row.get("sha256") or "")[:8]
        nst = row.get("n_stations")
        meta_bits = " &#183; ".join(b for b in
                                    ([f"{int(nst)} stations"] if nst else [])
                                    + ([size] if size else []))
        sha_cell = f"sha256 {sha}&#8230;" if sha else ""
        bundle_items.append(f'<tr><td><a href="/data/{_e(rel)}">{_e(lbl)}</a></td>'
                            f"<td>{meta_bits}</td><td>{sha_cell}</td></tr>")
        dist.append({"@type": "DataDownload", "encodingFormat": mime,
                     "contentUrl": f"{base}/data/{rel}"})
    if bundle_items:
        related = _related_by_identifies(smeta)
        doi_line = ""
        if related.get("level2"):
            u = _doi_url(related["level2"].get("identifier"))
            if u:
                doi_line = (f'<div class="doi">Published release: <a href="{_e(u)}">'
                            f'{_e(_bare_doi(related["level2"].get("identifier")) or u)}</a></div>')
        panels.append(
            '<div class="lvl"><div class="lvlhead"><span class="lvlbadge">L2</span>'
            '<span class="lvlname">Transfer functions</span></div>'
            '<table class="dtbl">' + "".join(bundle_items) + f"</table>{doi_line}</div>")
    if dist:
        ld["distribution"] = dist

    # ---- head-of-page blocks ----
    nav = ('<div class="pagenav"><a class="navbtn" href="/#/surveys">&#8592; All surveys</a>'
           f'<a class="navbtn map" href="/#/survey/{_e(slug)}">View all stations on the main map</a></div>')
    cite = ""
    c = smeta.get("cite") or {}
    if c.get("au") or c.get("ti"):
        parts = [f"{_e(_initials(c.get('au')))}" if c.get("au") else _e(org)]
        if c.get("yr"):
            parts.append(f"({_e(c['yr'])}):")
        parts.append(f"<i>{_e(c.get('ti') or title)}.</i>")
        if c.get("ve"):
            parts.append(f"Version {_e(c['ve'])}.")
        if c.get("pb"):
            parts.append(f"{_e(c['pb'])}.")
        cite = ('<div class="cite"><span style="color:#8FA3B0">Cite as:</span> '
                + " ".join(parts) + f" <code>{_e(url)}</code></div>")
    embargo = ""
    if (smeta.get("access") or "").lower() == "embargoed":
        until = smeta.get("embargo_until")
        embargo = (f'<div class="embargo">This survey is under embargo'
                   f'{f" until {_e(until)}" if until else ""}: its transfer functions are not '
                   f"yet distributed. Discovery metadata is published now; the data follows when "
                   f"the embargo lifts.</div>")

    # ---- hero: abstract + maps ----
    compact = False
    if points:
        lons = [lo for lo, _la in points]
        lats = [la for _lo, la in points]
        compact = max(max(lons) - min(lons), max(lats) - min(lats)) < 8 and len(points) > 1
    maps = [_minimap_svg(points)]
    cap = ""
    if compact:
        maps.append(_footprint_svg(points))
        cap = (f'<div class="mapcap">{min(lats):.2f}&#176; to {max(lats):.2f}&#176;S &#183; '
               f'{min(lons):.2f}&#176; to {max(lons):.2f}&#176;E</div>')
    hero = (f'<div class="hero"><div><p style="margin-top:.2rem">{_e(blurb)}</p></div>'
            f'<div class="hero-maps">{"".join(maps)}{cap}</div></div>'
            if blurb else
            f'<div class="hero"><div></div><div class="hero-maps">{"".join(maps)}{cap}</div></div>')

    # ---- stat tiles ----
    def tile(num, lab):
        return f'<div class="cstat"><div class="cnum">{num}</div><div class="clab">{lab}</div></div>'
    tiles = [tile(n_stations, "stations")]
    if type_counts:
        tstr = " / ".join(f"{t}" if len(type_counts) == 1 else f"{t} {n}"
                          for t, n in sorted(type_counts.items()))
        tiles.append(tile(_e(tstr), "data type"))
    if pmin is not None and pmax is not None:
        tiles.append(tile(f"{_fmt_period(pmin)} to {_fmt_period(pmax)} s", "period coverage"))
    tiles.append(tile(f"{tipper} / {n_stations}", "tipper stations"))
    if years:
        tiles.append(tile(_e(years), "acquired"))
    if version:
        tiles.append(tile(_e(version), "version"))
    stats = f'<div class="cstats">{"".join(tiles)}</div>'

    # ---- facts ----
    facts = []
    if org:
        facts.append(f"<dt>Organisation</dt><dd>{_e(org)}</dd>")
    if lic:
        facts.append(f"<dt>Licence</dt><dd>{_e(lic)}</dd>")
    if len(rates) == 1:
        facts.append(f"<dt>Sample rate</dt><dd>{next(iter(rates)):,.0f} Hz</dd>")
    elif rates:
        facts.append(f"<dt>Sample rates</dt><dd>{', '.join(f'{r:,.0f}' for r in sorted(rates))} Hz</dd>")
    if dipoles:
        lo, hi = min(dipoles), max(dipoles)
        mid = sorted(dipoles)[len(dipoles) // 2]
        facts.append(f"<dt>Dipoles</dt><dd>about {mid:g} m Ex and Ey, measured per station "
                     f"({lo:g} to {hi:g} m)</dd>")
    if smeta.get("instrument_model"):
        pid = smeta.get("instrument_pid")
        pid_bit = (f' &#183; <a href="{_e(_doi_url(pid))}">instrument PID {_e(pid)}</a>'
                   if pid else "")
        facts.append(f"<dt>Instruments</dt><dd>{_e(smeta['instrument_model'])}{pid_bit}</dd>")
    if smeta.get("software"):
        facts.append(f"<dt>Processing</dt><dd>{_e(smeta['software'])}</dd>")
    if funders:
        bits = []
        for f in funders:
            grant = f.get("grant_id")
            bits.append(_e(f.get("name") or "") + (f" (grant {_e(grant)})" if grant else ""))
        facts.append(f"<dt>Funding</dt><dd>{' &#183; '.join(b for b in bits if b)}</dd>")
    facts_html = f"<dl>{''.join(facts)}</dl>" if facts else ""

    # ---- contributors / publications ----
    people = _person_rows(smeta.get("contributors"))
    people_html = (f"<h2>Contributors</h2><div class=\"people\">{''.join(people)}</div>"
                   if people else "")
    pub_rows = []
    for p in pubs:
        doi = _doi_url(p.get("doi"))
        link = f' <a href="{_e(doi)}">{_e(_bare_doi(p.get("doi")) or "")}</a>' if doi else ""
        pub_rows.append(f'<p class="pub">{_e(p.get("a") or "")} ({_e(p.get("y") or "")}). '
                        f'{_e(p.get("t") or "")}. <i>{_e(p.get("j") or "")}.</i>{link}</p>')
    pubs_html = f"<h2>Publications</h2>{''.join(pub_rows)}" if pub_rows else ""

    # ---- the station table ----
    any_runs = any(doc.get("runs") for doc in docs)
    header = ["Station", "Lat", "Lon", "T max (s)"]
    if any_runs:
        header += ["Deployed", "Recovered", "Rate (Hz)", "Ex", "Ey",
                   "Logger", "Bx coil", "By coil"]
    header.append("Time series")
    rows_html = []
    for doc in docs:
        aid = doc["ausmt_id"]
        st = doc.get("station") or aid
        loc = doc.get("location") or {}
        data = doc.get("data") or {}
        cells = [f'<td><a href="/stations/{_e(aid)}">{_e(st)}</a></td>']
        for v in (loc.get("lat"), loc.get("lon")):
            cells.append(f"<td>{v if v is not None else '-'}</td>")
        pm = data.get("period_max_s")
        cells.append(f"<td>{_fmt_period(pm) if pm is not None else '-'}</td>")
        if any_runs:
            run = (doc.get("runs") or [{}])[0]
            period = run.get("time_period") or {}
            for key in ("start", "end"):
                v = str(period.get(key) or "")[:16].replace("T", " ")
                cells.append(f"<td>{_e(v) if v else '-'}</td>")
            rate = run.get("sample_rate_hz")
            cells.append(f"<td>{rate:g}</td>" if rate else "<td>-</td>")
            channels = {ch.get("component"): ch for ch in run.get("channels") or []}
            for comp in ("ex", "ey"):
                ch = channels.get(comp) or {}
                length = ch.get("dipole_length_m")
                az = ch.get("measurement_azimuth_deg")
                if length is not None:
                    az_bit = f" @ {az:g}&#176;" if az is not None else ""
                    cells.append(f"<td>{length:g} m{az_bit}</td>")
                else:
                    cells.append("<td>-</td>")

            def _inst_cell(inst):
                if not inst:
                    return "<td>-</td>"
                rows = (inst or {}).get("identifiers") or []
                doi = rows[0].get("identifier") if rows else None
                if doi:
                    tail = doi.rsplit("/", 1)[-1]
                    return (f'<td class="pidcell"><a href="{_e(_doi_url(doi))}">{_e(tail)}</a></td>')
                serial = inst.get("serial_number")
                return f"<td>{_e(serial)}</td>" if serial else "<td>-</td>"
            cells.append(_inst_cell(run.get("data_logger")))
            for comp in ("hx", "hy"):
                cells.append(_inst_cell((channels.get(comp) or {}).get("sensor")))
        level_bits = []
        for level_key, badge, _name in _TS_LEVELS:
            row = (ts_rows.get(level_key) or {}).get(aid)
            if row:
                size = _fmt_bytes((row or {}).get("bytes"))
                level_bits.append(f"{badge} {size}" if size else badge)
        cells.append(f'<td class="ts-y">{" &#183; ".join(level_bits)}</td>'
                     if level_bits else '<td class="ts-n">-</td>')
        rows_html.append("<tr>" + "".join(cells) + "</tr>")
    table = ""
    if rows_html:
        table = (f"<h2>Stations ({n_stations})</h2>"
                 '<div class="scroll"><table class="stbl"><thead><tr>'
                 + "".join(f"<th>{h}</th>" for h in header)
                 + "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table></div>")

    body = (
        f"{nav}\n"
        f"<h1>{_e(title)}</h1>\n"
        f'<p class="crumb">Magnetotelluric survey &#183; {_e(region)}</p>\n'
        f"{cite}\n{embargo}\n{hero}\n{stats}\n{facts_html}\n"
        + (f"<h2>Data &amp; downloads</h2>\n{''.join(panels)}\n" if panels else "")
        + f"{people_html}\n{pubs_html}\n{table}\n"
        + f'<p><a href="/data/products/{_e(slug)}/survey-metadata.json">Machine-readable survey record</a>'
        + ' &#183; catalogue schema <a href="/data/mtcat.schema.json">mtcat 2.0</a></p>\n'
    )
    og_image = f"{base}/pages/og/{slug}.png" if _og_available() else None
    return _shell(title=f"{title} - magnetotelluric survey data - AusMT",
                  description=desc_meta, canonical=url, body=body, jsonld=ld,
                  og_image=og_image, base=base)


def station_page(*, doc, survey_slug, base) -> str:
    aid = doc["ausmt_id"]
    st = doc.get("station") or aid
    survey = doc.get("survey") or survey_slug
    url = f"{base}/stations/{aid}"
    loc = doc.get("location") or {}
    data = doc.get("data") or {}
    facts = [f"<dt>AusMT id</dt><dd>{_e(aid)}</dd>",
             f"<dt>Survey</dt><dd><a href=\"/surveys/{_e(survey_slug)}\">{_e(survey)}</a></dd>"]
    # The served document's OWN presentation, verbatim: a generalised or withheld station's
    # document already carries the disclosed (or absent) position, so echoing it adds nothing.
    if loc.get("lat") is not None and loc.get("lon") is not None:
        facts.append(f"<dt>Location</dt><dd>{_e(loc['lat'])}, {_e(loc['lon'])}</dd>")
    else:
        facts.append("<dt>Location</dt><dd>withheld or generalised by the data custodian</dd>")
    if data.get("type"):
        facts.append(f"<dt>Data type</dt><dd>{_e(data['type'])}</dd>")
    if data.get("period_min_s") is not None and data.get("period_max_s") is not None:
        facts.append(f"<dt>Period range</dt><dd>{_e(data['period_min_s'])} to {_e(data['period_max_s'])} s"
                     f" ({int(data.get('n_periods') or 0)} periods)</dd>")
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / <a href="/surveys/{_e(survey_slug)}">{_e(survey)}</a></p>\n'
        f"<h1>Station {_e(st)}</h1>\n"
        f'<p class="crumb">Magnetotelluric transfer function &#183; {_e(survey)}</p>\n'
        "<dl>\n" + "\n".join(facts) + "\n</dl>\n"
        f'<p><a class="navbtn" href="/#/station/{_e(aid)}">Open in the interactive portal</a></p>\n'
        f'<p><a href="/data/products/{_e(survey_slug)}/{_e(st)}/station.json">Machine-readable station record</a></p>\n'
    )
    return _shell(title=f"{st} - {survey} - AusMT",
                  description=f"Magnetotelluric station {st} from the {survey} survey: "
                              "transfer function data, metadata and downloads on AusMT.",
                  canonical=url, body=body, noindex=True, base=base)


def collection_page(*, cid, coll, member_slugs, member_smeta, base) -> str:
    title = (coll or {}).get("title") or cid
    desc = (coll or {}).get("description") or f"{title}: a collection of magnetotelluric surveys on AusMT."
    url = f"{base}/collections/{cid}"
    members = "\n".join(
        f'<li><a href="/surveys/{_e(s)}">{_e(lbl)}</a></li>' for lbl, s in member_slugs)
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": title, "description": desc, "url": url,
          "identifier": url,
          "isAccessibleForFree": True,
          "includedInDataCatalog": {"@type": "DataCatalog", "name": "AusMT", "url": base + "/"},
          "measurementTechnique": "magnetotellurics",
          "variableMeasured": "magnetotelluric transfer function",
          "hasPart": [{"@type": "Dataset", "url": f"{base}/surveys/{s}"} for _lbl, s in member_slugs],
          "keywords": ["magnetotellurics", "MT", "AusLAMP", "geophysics", "Australia"]}
    # licence / creators / temporal coverage roll up from the member surveys' own served records:
    # a single shared licence is stated; mixed licences state nothing (never overclaim).
    lics = {(_LICENSE_URLS.get((m or {}).get("lic"), (m or {}).get("lic")))
            for m in member_smeta if (m or {}).get("lic")}
    if len(lics) == 1:
        ld["license"] = next(iter(lics))
    orgs = []
    for m in member_smeta:
        name = (m or {}).get("org")
        if name and name not in [o["name"] for o in orgs]:
            orgs.append({"@type": "Organization", "name": name})
    if orgs:
        ld["creator"] = orgs
    y0 = [m.get("year_start") for m in member_smeta if (m or {}).get("year_start")]
    y1 = [m.get("year_end") for m in member_smeta if (m or {}).get("year_end")]
    if y0:
        ld["temporalCoverage"] = f"{min(y0)}/{max(y1)}" if y1 else f"{min(y0)}/.."
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / collections</p>\n'
        f"<h1>{_e(title)}</h1>\n"
        f"<p>{_e(desc)}</p>\n"
        f"<dl><dt>Surveys</dt><dd>{len(member_slugs)}</dd>"
        f"<dt>Stations</dt><dd>{int((coll or {}).get('n_stations') or 0)}</dd></dl>\n"
        f'<p><a class="navbtn" href="/#/collection/{_e(cid)}">Open in the interactive portal</a></p>\n'
        "<h2>Member surveys</h2>\n<ul>\n" + members + "\n</ul>\n"
    )
    return _shell(title=f"{title} - magnetotelluric data - AusMT",
                  description=desc if len(desc) <= 160 else desc[:157] + "...",
                  canonical=url, body=body, jsonld=ld, base=base)


# --------------------------------------------------------------------------- og cards (Pillow)

def _og_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def _og_card(path, *, title, subtitle, region_year, period_line, dims_line, points):
    """One 1200x630 link-preview card in the portal card's design language: footprint dots,
    Australia locator inset, the survey's key numbers. Pillow's bundled scalable default face
    (no font files shipped or fetched)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1200, 630
    ink, panel, line = (13, 20, 40), (17, 26, 51), (43, 53, 87)
    text, muted, copper, cyan = (255, 255, 255), (143, 163, 176), (239, 114, 86), (79, 195, 217)
    img = Image.new("RGB", (W, H), ink)
    d = ImageDraw.Draw(img)

    def font(size, bold=False):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:                     # Pillow < 10.1: tiny bitmap face, still legible
            return ImageFont.load_default()

    # footprint panel, right side
    if points:
        lons = [lo for lo, _la in points]
        lats = [la for _lo, la in points]
        lo0, lo1 = min(lons), max(lons)
        la0, la1 = min(lats), max(lats)
        dlo, dla = max(lo1 - lo0, 1e-6), max(la1 - la0, 1e-6)
        px0, py0, px1, py1 = 640, 70, 1150, 560
        pw, ph = px1 - px0, py1 - py0
        if pw * (dla / dlo) > ph:
            pw = ph / (dla / dlo)
        else:
            ph = pw * (dla / dlo)
        px1, py1 = px0 + pw, py0 + ph
        d.rounded_rectangle([px0 - 16, py0 - 16, px1 + 16, py1 + 16], radius=12,
                            fill=panel, outline=line, width=2)
        for lo, la in points:
            x = px0 + (lo - lo0) / dlo * pw
            y = py0 + (la1 - la) / dla * ph
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=cyan)
        # Australia locator inset, bottom-right over the panel
        ext = au.EXTENT
        iw = 190
        ih = round(iw * (ext["n"] - ext["s"]) / (ext["e"] - ext["w"]))
        ix, iy = W - iw - 36, H - ih - 36
        d.rounded_rectangle([ix - 10, iy - 10, ix + iw + 10, iy + ih + 10], radius=10,
                            fill=ink, outline=line, width=2)

        def ip(lon, lat):
            return (ix + (lon - ext["w"]) / (ext["e"] - ext["w"]) * iw,
                    iy + (ext["n"] - lat) / (ext["n"] - ext["s"]) * ih)
        for ring in au.COAST:
            d.polygon([ip(lo, la) for lo, la in ring], fill=(20, 29, 54), outline=(49, 64, 107))
        cx, cy = ip((lo0 + lo1) / 2, (la0 + la1) / 2)
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=copper)
        d.ellipse([cx - 14, cy - 14, cx + 14, cy + 14], outline=copper, width=2)
    d.text((60, 130), title, font=font(64), fill=text)
    d.text((60, 220), subtitle, font=font(29), fill=muted)
    d.text((60, 262), region_year, font=font(29), fill=muted)
    if period_line:
        d.text((60, 330), period_line, font=font(26), fill=(201, 212, 232))
    if dims_line:
        d.text((60, 370), dims_line, font=font(26), fill=(201, 212, 232))
    d.text((60, 540), "ausmt.auscope.org.au", font=font(28), fill=copper)
    img.save(path, "PNG", optimize=True)


# --------------------------------------------------------------------------- the emitter

def emit_pages(out, base, *, surveys_meta, survey_docs, station_docs, collections,
               bundle_formats, survey_extent, survey_coll,
               bundle_rows=None, ts_access=None) -> int:
    """Write every entity page under <out>/pages/ (and, when Pillow is importable, the
    per-survey link-preview cards under <out>/pages/og/). Inputs are the served documents and
    rollups the build already produced; the return value is the page count the caller reconciles
    against the sitemap (the two must always agree, pinned in tests)."""
    base = base.rstrip("/")
    n = 0
    slug_by_label = {}
    docs_by_survey: dict = {}
    for doc in station_docs.values():
        docs_by_survey.setdefault(doc.get("survey_id"), []).append(doc)
    bundles_by_slug: dict = {}
    for row in bundle_rows or []:
        bundles_by_slug.setdefault((row or {}).get("slug"), []).append(row)

    sdir = out / "pages" / "surveys"
    sdir.mkdir(parents=True, exist_ok=True)
    ogdir = out / "pages" / "og"
    draw_cards = _og_available()
    if draw_cards:
        ogdir.mkdir(parents=True, exist_ok=True)
    for label in sorted(surveys_meta):
        smeta = surveys_meta.get(label) or {}
        slug = smeta.get("slug") or label
        slug_by_label[label] = slug
        docs = docs_by_survey.get(slug, [])
        rows = bundles_by_slug.get(slug)
        if rows is None and (bundle_formats or {}).get(slug):
            # Compatibility path for callers that pass only the format->path map: rows carry the
            # url alone and the size/sha cells stay absent.
            rows = [{"slug": slug, "format": f, "url": rel}
                    for f, rel in sorted(bundle_formats[slug].items())]
        htmlpage = survey_page(slug=slug, label=label, sm_doc=survey_docs.get(slug),
                               smeta=smeta, station_docs=docs,
                               bundle_rows=rows or [], ts_access=ts_access,
                               base=base, extent=(survey_extent or {}).get(label))
        (sdir / f"{slug}.html").write_text(htmlpage, encoding="utf-8")
        n += 1
        if draw_cards:
            points = _station_points(docs)
            pmin = pmax = None
            types: dict = {}
            for doc in docs:
                data = doc.get("data") or {}
                if data.get("period_min_s") is not None:
                    pmin = data["period_min_s"] if pmin is None else min(pmin, data["period_min_s"])
                if data.get("period_max_s") is not None:
                    pmax = data["period_max_s"] if pmax is None else max(pmax, data["period_max_s"])
                if data.get("type"):
                    types[data["type"]] = types.get(data["type"], 0) + 1
            title = ((survey_docs.get(slug) or {}).get("title")) or label
            tdesc = " + ".join(sorted(types)) if types else "magnetotelluric"
            years = _survey_years(survey_docs.get(slug), smeta)
            period_line = (f"{_fmt_period(pmin)} to {_fmt_period(pmax)} s"
                           if pmin is not None and pmax is not None else "")
            dims = ""
            if points and len(points) > 1:
                lons = [lo for lo, _la in points]
                lats = [la for _lo, la in points]
                dkm_x = (max(lons) - min(lons)) * 111 * 0.83
                dkm_y = (max(lats) - min(lats)) * 111
                dims = f"about {dkm_x:.0f} x {dkm_y:.0f} km"
            _og_card(ogdir / f"{slug}.png",
                     title=title,
                     subtitle=f"{len(docs)}-station {tdesc} survey",
                     region_year=" · ".join(x for x in (smeta.get("region"), years) if x),
                     period_line=period_line, dims_line=dims, points=points)

    stdir = out / "pages" / "stations"
    stdir.mkdir(parents=True, exist_ok=True)
    for doc in station_docs.values():
        (stdir / f"{doc['ausmt_id']}.html").write_text(
            station_page(doc=doc, survey_slug=doc.get("survey_id"), base=base), encoding="utf-8")
        n += 1

    cdir = out / "pages" / "collections"
    cdir.mkdir(parents=True, exist_ok=True)
    for cid in sorted(collections or {}):
        members = [(lbl, slug_by_label.get(lbl, lbl))
                   for lbl in sorted(surveys_meta) if (survey_coll or {}).get(lbl) == cid]
        member_smeta = [surveys_meta.get(lbl) or {} for lbl, _s in members]
        (cdir / f"{cid}.html").write_text(
            collection_page(cid=cid, coll=collections[cid], member_slugs=members,
                            member_smeta=member_smeta, base=base),
            encoding="utf-8")
        n += 1
    return n
