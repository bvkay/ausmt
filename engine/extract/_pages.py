#!/usr/bin/env python3
"""Tier-3 entity landing pages: one static HTML document per survey, station and collection,
served at the path-URL contract's own shapes (/surveys/<slug>, /stations/<ausmt_id>,
/collections/<id>).

Every page is rendered ONLY from the already-served public documents (survey-metadata.json,
station.json, the collections rollup and the manifest's bundle rows), so a page can never
disclose anything the gated products do not already publish; the C42 posture is inherited, and
the coord-access whole-tree sweep audits pages/ like every other emitter. All free text is
HTML-escaped (curator-authored YAML is still a public serving surface), and the JSON-LD block
escapes "</" so document text can never close the script element.

Stdlib only, deliberately: this is a leaf like _license_text, importable by the spawn workers'
build_portal without extra weight.
"""
from __future__ import annotations

import html
import json

_LICENSE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
}

_BUNDLE_LABELS = {
    "edi-zip": ("EDI archive (zip)", "application/zip"),
    "xml-zip": ("EMTF XML archive (zip)", "application/zip"),
    "survey-mth5": ("Survey MTH5 bundle", "application/x-hdf5"),
}


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _jsonld(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1).replace("</", "<\\/")


def _shell(*, title, description, canonical, body, jsonld=None) -> str:
    ld = f'<script type="application/ld+json">{_jsonld(jsonld)}</script>\n' if jsonld else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{_e(title)}</title>\n"
        f'<meta name="description" content="{_e(description)}">\n'
        f'<link rel="canonical" href="{_e(canonical)}">\n'
        f"{ld}"
        "<style>\n"
        "  body{margin:0;background:#11182D;color:#C9D4E8;font:16px/1.55 -apple-system,'Segoe UI',"
        "Helvetica,Arial,sans-serif}\n"
        "  main{max-width:760px;margin:0 auto;padding:2rem 1.25rem 3rem}\n"
        "  a{color:#EF7256}\n"
        "  h1{color:#fff;font-size:1.7rem;margin:.2rem 0 .3rem}\n"
        "  .crumb{font-size:.85rem;opacity:.8}\n"
        "  dl{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:1.2rem 0}\n"
        "  dt{opacity:.7}\n  dd{margin:0}\n"
        "  .cta{display:inline-block;background:#EF7256;color:#11182D;font-weight:600;"
        "padding:.55rem 1rem;border-radius:6px;text-decoration:none;margin:.8rem 0}\n"
        "  ul{padding-left:1.2rem}\n"
        "  footer{margin-top:2.2rem;font-size:.8rem;opacity:.7}\n"
        "</style>\n</head>\n<body>\n<main>\n"
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
        return f"{y0}" if y0 == y1 else f"{y0}-{y1}"
    return str(y0 or y1 or "")


def survey_page(*, slug, label, sm_doc, smeta, n_stations, bundles, base, extent=None) -> str:
    title = ((sm_doc or {}).get("title")) or label
    blurb = ((smeta or {}).get("blurb")) or ""
    org = (smeta or {}).get("org") or ""
    lic = (smeta or {}).get("lic") or ""
    years = _survey_years(sm_doc, smeta)
    url = f"{base}/surveys/{slug}"
    desc = (blurb or f"Magnetotelluric survey data: {title}.").strip()
    desc_meta = (desc[:157] + "...") if len(desc) > 160 else desc

    dist = []
    dl_items = []
    for fmt, rel in sorted((bundles or {}).items()):
        lbl, mime = _BUNDLE_LABELS.get(fmt, (fmt, "application/octet-stream"))
        dist.append({"@type": "DataDownload", "encodingFormat": mime,
                     "contentUrl": f"{base}/data/{rel}"})
        dl_items.append(f'<li><a href="/data/{_e(rel)}">{_e(lbl)}</a></li>')

    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": f"{title} magnetotelluric survey",
          "description": desc, "url": url,
          "isAccessibleForFree": True,
          "includedInDataCatalog": {"@type": "DataCatalog", "name": "AusMT", "url": base + "/"},
          "keywords": ["magnetotellurics", "MT", "transfer function", "geophysics", "Australia"]}
    if org:
        ld["creator"] = {"@type": "Organization", "name": org}
    if lic:
        ld["license"] = _LICENSE_URLS.get(lic, lic)
    if years:
        ld["temporalCoverage"] = str(years).replace("-", "/") if "-" in str(years) else str(years)
    if extent and all(k in extent for k in ("lat_min", "lat_max", "lon_min", "lon_max")):
        ld["spatialCoverage"] = {"@type": "Place", "geo": {
            "@type": "GeoShape",
            "box": f"{extent['lat_min']} {extent['lon_min']} {extent['lat_max']} {extent['lon_max']}"}}
    if dist:
        ld["distribution"] = dist

    facts = [f"<dt>Stations</dt><dd>{int(n_stations)}</dd>"]
    if org:
        facts.append(f"<dt>Organisation</dt><dd>{_e(org)}</dd>")
    if years:
        facts.append(f"<dt>Acquired</dt><dd>{_e(years)}</dd>")
    if lic:
        facts.append(f"<dt>Licence</dt><dd>{_e(lic)}</dd>")

    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / surveys</p>\n'
        f"<h1>{_e(title)}</h1>\n"
        f'<p class="crumb">Magnetotelluric survey - Australia</p>\n'
        + (f"<p>{_e(blurb)}</p>\n" if blurb else "")
        + "<dl>\n" + "\n".join(facts) + "\n</dl>\n"
        + f'<p><a class="cta" href="/#/survey/{_e(slug)}">Open in the interactive portal</a></p>\n'
        + (("<h2>Data downloads</h2>\n<ul>\n" + "\n".join(dl_items) + "\n</ul>\n") if dl_items else "")
        + f'<p><a href="/data/products/{_e(slug)}/survey-metadata.json">Machine-readable survey record</a></p>\n'
    )
    return _shell(title=f"{title} - magnetotelluric survey data - AusMT",
                  description=desc_meta, canonical=url, body=body, jsonld=ld)


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
        facts.append(f"<dt>Period range</dt><dd>{_e(data['period_min_s'])} - {_e(data['period_max_s'])} s"
                     f" ({int(data.get('n_periods') or 0)} periods)</dd>")
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / <a href="/surveys/{_e(survey_slug)}">{_e(survey)}</a></p>\n'
        f"<h1>Station {_e(st)}</h1>\n"
        f'<p class="crumb">Magnetotelluric transfer function - {_e(survey)}</p>\n'
        "<dl>\n" + "\n".join(facts) + "\n</dl>\n"
        f'<p><a class="cta" href="/#/station/{_e(aid)}">Open in the interactive portal</a></p>\n'
        f'<p><a href="/data/products/{_e(survey_slug)}/{_e(st)}/station.json">Machine-readable station record</a></p>\n'
    )
    return _shell(title=f"{st} - {survey} - AusMT",
                  description=f"Magnetotelluric station {st} from the {survey} survey: "
                              "transfer function data, metadata and downloads on AusMT.",
                  canonical=url, body=body)


def collection_page(*, cid, coll, member_slugs, base) -> str:
    title = (coll or {}).get("title") or cid
    desc = (coll or {}).get("description") or f"{title}: a collection of magnetotelluric surveys on AusMT."
    url = f"{base}/collections/{cid}"
    members = "\n".join(
        f'<li><a href="/surveys/{_e(s)}">{_e(lbl)}</a></li>' for lbl, s in member_slugs)
    ld = {"@context": "https://schema.org", "@type": "Dataset",
          "name": title, "description": desc, "url": url,
          "isAccessibleForFree": True,
          "includedInDataCatalog": {"@type": "DataCatalog", "name": "AusMT", "url": base + "/"},
          "hasPart": [{"@type": "Dataset", "url": f"{base}/surveys/{s}"} for _lbl, s in member_slugs],
          "keywords": ["magnetotellurics", "MT", "AusLAMP", "geophysics", "Australia"]}
    body = (
        f'<p class="crumb"><a href="/">AusMT</a> / collections</p>\n'
        f"<h1>{_e(title)}</h1>\n"
        f"<p>{_e(desc)}</p>\n"
        f"<dl><dt>Surveys</dt><dd>{len(member_slugs)}</dd>"
        f"<dt>Stations</dt><dd>{int((coll or {}).get('n_stations') or 0)}</dd></dl>\n"
        f'<p><a class="cta" href="/#/collection/{_e(cid)}">Open in the interactive portal</a></p>\n'
        "<h2>Member surveys</h2>\n<ul>\n" + members + "\n</ul>\n"
    )
    return _shell(title=f"{title} - magnetotelluric data - AusMT",
                  description=desc if len(desc) <= 160 else desc[:157] + "...",
                  canonical=url, body=body, jsonld=ld)


def emit_pages(out, base, *, surveys_meta, survey_docs, station_docs, collections,
               bundle_formats, survey_extent, survey_coll) -> int:
    """Write every entity page under <out>/pages/. Inputs are the served documents and rollups the
    build already produced; the return value is the page count the caller reconciles against the
    sitemap (the two must always agree, pinned in tests)."""
    base = base.rstrip("/")
    n = 0
    slug_by_label = {}
    counts: dict = {}
    for doc in station_docs.values():
        counts[doc.get("survey_id")] = counts.get(doc.get("survey_id"), 0) + 1

    sdir = out / "pages" / "surveys"
    sdir.mkdir(parents=True, exist_ok=True)
    for label in sorted(surveys_meta):
        smeta = surveys_meta.get(label) or {}
        slug = smeta.get("slug") or label
        slug_by_label[label] = slug
        htmlpage = survey_page(slug=slug, label=label, sm_doc=survey_docs.get(slug),
                               smeta=smeta, n_stations=counts.get(slug, 0),
                               bundles=(bundle_formats or {}).get(slug),
                               base=base, extent=(survey_extent or {}).get(label))
        (sdir / f"{slug}.html").write_text(htmlpage, encoding="utf-8")
        n += 1

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
        (cdir / f"{cid}.html").write_text(
            collection_page(cid=cid, coll=collections[cid], member_slugs=members, base=base),
            encoding="utf-8")
        n += 1
    return n
