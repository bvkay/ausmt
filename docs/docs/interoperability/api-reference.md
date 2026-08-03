# AusMT data reference

This page lists every document AusMT serves, says how to key into it, and shows worked patterns for
getting bytes out. [How AusMT serves data](api-overview.md) covers the architecture behind it,
[Tool integration](tool-integration.md) covers reading the artifacts from MT software, and the
[Reference section](../reference/index.md) documents every document field by field.

Counts and sizes quoted here describe a corpus of 21 surveys and 1,418 stations and move with the
corpus. The shapes and the rules do not.

---

## Base URL and conventions

All data lives under one prefix:

```text
/data/
```

Paths on this page are relative to the portal root, so `/data/mtcat.json` means
`<portal root>/data/mtcat.json`. The examples take that root from a `BASE` variable; set it to the
deployment you are reading from.

Paths inside the documents are relative to the data prefix, not to the document that carries them. A
manifest row whose `url` is `edi/vulcan-2022/Vulcan_A1.edi` resolves to
`/data/edi/vulcan-2022/Vulcan_A1.edi`. Join, do not template.

The manifest's `base_url` field is the escape hatch for a deployment that publishes artifacts
somewhere else. It is `""` on the live site, which means portal-relative. If it is set, join `url`
onto it instead. Rows also carry a `tier`, which is `repo` for every row in the live corpus; a `nci`
row would carry an absolute URL to a THREDDS file server and needs no joining at all. Handle both by
checking whether the `url` already starts with a scheme.

Two identifiers key almost everything:

| Identifier | Form | Example | Where it appears |
|---|---|---|---|
| survey slug | lowercase, hyphenated | `vulcan-2022` | `mtcat.json` as `survey_id`, `surveys.json` as `slug`, bundle filenames, product paths |
| `ausmt_id` | `au.<slug>.<station>[.<variant>]` | `au.vulcan-2022.A1` | `catalogue.json` column 12, every manifest row, `mtcat.json` as `station_id` |

---

## Discovery documents

Sizes are rounded, and are there to tell you what is cheap to fetch and what is not.

| URL | Bytes | What it is |
|---|---|---|
| `/data/mtcat.json` | 276 kB | The discovery document. Portal identity, surveys, stations, collections. Start here. |
| `/data/mtcat.schema.json` | 7.8 kB | The JSON Schema the document above validates against. |
| `/data/surveys.json` | 54 kB | Full per-survey metadata, including credit and citation. |
| `/data/catalogue.json` | 320 kB | One positional row per station. |
| `/data/stations.geojson` | 390 kB | Every station that has a position, as a GeoJSON point layer. Open it in a GIS. |
| `/data/sci.json` | 93 kB | Per-station derived diagnostics, aligned to the catalogue by index. |
| `/data/tf.json` | 3.2 MB | Per-station transfer-function curves, thinned, aligned by index. |
| `/data/collections.json` | 1.8 kB | Programme groupings. |
| `/data/manifest.json` | 828 kB | The download manifest: every fetchable artifact with size and SHA-256. |
| `/data/products/manifest.json` | 975 kB | The same document, indented. |
| `/data/build.json` | 300 B | Build identity and library versions. |
| `/data/build_provenance.json` | 1.3 kB | How this build was produced and with what parameters. |
| `/data/feed.xml` | 3.3 kB | Atom feed of surveys, newest first. |

`/data/manifest.json` and `/data/products/manifest.json` parse to identical content. The build writes
one compact and one indented, so the compact form is 147 kB smaller as raw bytes and the indented one
is readable in a browser. Don't pick on size. Gzipped they are 126 kB and 127 kB, under 1 kB apart, so
the choice costs nothing either way. The portal's own resolver reads `/data/manifest.json`.

### `mtcat.json`

MTCAT is the document to harvest. It is small, schema-versioned and designed to be read by a catalogue
that is not AusMT. Four top-level keys carry the payload, plus two that record the library versions the
build ran against:

```json
{
  "portal": { "portal_id": "ausmt", "portal_name": "...", "schema": "mtcat",
              "version": "1.2", "schema_url": "mtcat.schema.json",
              "metadata_license": "CC0-1.0", "generated_at": "2026-07-27T08:29:39Z" },
  "surveys":     [ ... ],
  "stations":    [ ... ],
  "collections": [ ... ],
  "mt_metadata_version": "1.0.9",
  "mth5_version": "0.6.8"
}
```

Read the schema version off `portal.version` rather than assuming one, and mean it. This page describes
**1.2**, which is what the current engine writes; a deployment serving an older build serves fewer keys.
`additionalProperties` stays true on every record object, so a consumer written against one minor
version reads another without changes as long as it treats an absent key as absent rather than as empty.

`portal.schema_url` is served next to the document, so a harvester can validate without resolving
anything off-site. `portal.metadata_license` is `CC0-1.0` and covers the catalogue metadata only; a
survey's data licence is the separate `license` field on its own record and varies by survey.

Survey records are identified by `survey_id` (the survey's slug). Required on every record are `survey_id`,
`title`, `organisation` and `country`. Six more facets are derived from the document's own `stations[]`
and from the build's download manifest, so a harvester can size and band-filter a survey without walking
the station list:

| Field | Derived from | Note |
|---|---|---|
| `n_stations` | `stations[]` | `stations[]` stays authoritative if the two ever disagree. |
| `data_types` | `stations[].data_type` | A map of band to station count, in the order BBMT, LPMT, AMT, GDS. |
| `period_min_s`, `period_max_s` | per-station period ranges | `null` when no station reports a range. |
| `n_stations_tipper` | per-station component lists | Compare against `n_stations` to read tipper coverage. |
| `formats` | the download manifest | The formats actually served. Empty for a survey whose bytes are withheld. |
| `year_start`, `year_end` | the survey's declared dates | Passed through, never inferred from file timestamps. |

`formats` is not curated. It is read off the manifest the same build has just written, so an embargoed
survey serves `[]`. Empty means "this build distributes nothing for this survey"; it never means
"unknown".

Station records are flat and small: `station_id` (the `ausmt_id`), `survey_id`, `latitude`, `longitude`
and `data_type`. `data_type` is one of `AMT`, `BBMT`, `LPMT`, `GDS` or `unknown`, derived from the
station's shortest period and which transfer functions are present. The survey does not declare it.
Latitude and longitude are nullable, because a custodian can withhold a position.

Every field, including the credit and provenance blocks and the access fields, is documented field by
field in the [MTCAT schema reference](../reference/mtcat-schema.md), which also explains how to read a
served record. The normative artifact is the schema itself.

### `surveys.json`

The full survey metadata the portal renders, and the place to go for citation and credit.

It is an object, and **the keys are survey display names**. The key for the Vulcan 2022 survey is
`"Vulcan 2022"`, not `"vulcan-2022"`. The slug lives in a `slug` field inside each record. That trips
people up, so build your own index by iterating values:

```python
import json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]                 # the portal root you are reading from
surveys = json.load(urllib.request.urlopen(f"{BASE}/data/surveys.json"))
by_slug = {v["slug"]: v for v in surveys.values()}
print(by_slug["vulcan-2022"]["cite"])
```

Credit fields on each record:

| Field | Shape | Meaning |
|---|---|---|
| `creators` | list of `{name, name_type, orcid?, ror?}` | Citation authors, in citation order. Order is load-bearing. |
| `contributors` | list of `{name, name_type, role, orcid?, ror?}` | Who did what, as DataCite contributor types. Order carries no meaning. |
| `cite` | `{au, yr, ti, ve, pb}` | The pre-rendered citation parts the portal's Cite tab assembles. |
| `related_identifiers` | list of typed links | What the survey points at, with an NCI data level and a resolution state. |
| `attribution`, `sources`, `changes` | objects, present only when declared | Rights of record, upstream sources, and the CC-BY changes declaration. |

`contributors` in the exported form always ends with the hosting portal appended as
`{"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"}`. A survey never declares
that role for itself.

The full field set is in [Served documents](../reference/portal-documents.md#surveysjson), and the
`survey.yaml` these records are generated from is specified in the
[survey.yaml reference](../reference/survey-yaml.md).

### `catalogue.json`

One row per station, 1,418 rows in the live corpus. **The rows are positional arrays, not objects.**
There are no field names in the file. You read by index.

The authoritative column map is `/src/contract.js`, generated from `contract/columns.json`, which is
the single file that defines the order. Take indices from there instead of counting them by hand.
Columns are only ever appended, never reordered.

| Index | Name | Type | Meaning |
|---|---|---|---|
| 0 | `id` | string | Station id (`<station>.<variant>` when one site has several processings) |
| 1 | `survey` | string | Survey display name, the key into `surveys.json` |
| 2 | `lat` | number or null | Latitude, decimal degrees, WGS84 |
| 3 | `lon` | number or null | Longitude, decimal degrees, WGS84 |
| 4 | `period_min_s` | number or null | Shortest period, seconds |
| 5 | `period_max_s` | number or null | Longest period, seconds |
| 6 | `n_periods` | integer | Number of periods |
| 7 | `comps` | string | Components present, e.g. `"ZT"` for impedance and tipper |
| 8 | `type` | string | Band: `AMT`, `BBMT`, `LPMT`, `GDS` or `unknown` |
| 9 | `region` | string | Region facet from the survey |
| 10 | `file` | string | Source transfer-function filename |
| 11 | `coord_flag` | bool | True if the coordinate was flagged and resolved at intake |
| 12 | `ausmt_id` | string | `au.<slug>.<station>[.<variant>]`, the join key for the manifest |
| 13 | `edi_available` | 0 or 1 | 1 if the EDI is redistributably licensed and bundled |
| 14 | `sha256` | string | SHA-256 of the source transfer-function file |
| 15 | `site_name` | string or null | Original pre-sanitisation site name, when it differs from index 0 |

`sci.json` and `tf.json` are aligned to this file **by array index only**, with no key on the wire.
`catalogue[i]`, `sci[i]` and `tf[i]` describe the same station. All three have 1,418 entries in the
live corpus. Their columns are enumerated in
[Portal Data Files](../developer/data-files.md), which is the authoritative definition.

Two facts about withheld surveys, both verifiable on `au.kalkaroo-2022.KD-C3`:

- its `tf.json` entry is 18 empty arrays, one per column, so the width and the index alignment hold;
- its `sci.json` entry has the science-derived fields nulled but keeps the processing metadata that
  exists at source, because that describes how the data were processed rather than what the data
  say. For this station that means `rr` is 0 and `sw` is `"Geotools 4.0.5.12583"`, both public;
  `alg` is null here because no Kalkaroo station declares one, withheld or not.

The catalogue row itself stays complete apart from `edi_available`, which is 0. The band, the period
range and the component list of an embargoed station are public; the curves are not.

### `stations.geojson`

An RFC 7946 `FeatureCollection` of `Point` features, one per station that has a position, in WGS84
(GeoJSON's only coordinate reference system, so there is nothing to set). It exists so you can put the
corpus on a map without first writing a script against the positional catalogue.

In QGIS: **Layer > Add Layer > Add Vector Layer**, set Source Type to **Protocol: HTTP(S)**, and paste
the URL:

```text
<portal root>/data/stations.geojson
```

The same URL works anywhere that reads GeoJSON over HTTP, and with `ogr2ogr` for a local conversion:

```bash
BASE=${AUSMT_BASE:?the portal root you are reading from}
ogr2ogr -f GPKG stations.gpkg "/vsicurl/$BASE/data/stations.geojson"
```

Each feature carries seven flat properties, chosen to be joinable and to keep the file small:
`ausmt_id`, `station`, `survey` (the display name), `survey_id` (the slug), `data_type`,
`period_min_s` and `period_max_s`. Join on `ausmt_id` to the download manifest, or on `survey_id` to
`mtcat.json`, for anything else. Licence and credit are deliberately not repeated per feature: they
are survey-level facts and live in `surveys.json` and `mtcat.json`.

Two membership rules, and they are the same rules the catalogue follows:

- a station whose position the custodian **withholds** is **absent**, rather than present with a null
  geometry. A null-geometry feature parses but nothing draws it, so it would be an invisible row. The
  station itself is not hidden: it keeps its catalogue row, its `mtcat.json` entry and its
  `station.json`, and `/data/coord_policy.json` records that its position is withheld;
- a station whose position is **generalised** is here, at the same 0.1° cell the catalogue serves, so a
  point can sit up to about 5 km from the true site. Nothing is rounded twice.

An embargoed survey's stations **are** on this layer. An embargo withholds bytes, never discovery, and
this document carries no bytes.

### `collections.json`

Programme groupings, keyed by collection id. One entry in the current corpus, `auslamp`, holding nine
surveys and 459 stations.

`mtcat.json` carries the same groupings under `collections[]`, keyed the same way, with member surveys
pointing back through `surveys[].collection_id`. One difference will catch you out. A collection's
`centroid` is the mean of its member station positions, while a survey's `centroid` is the centre of
its own bbox.

The field reference is in
[Served documents](../reference/portal-documents.md#collectionsjson).

### `build.json` and `build_provenance.json`

`build.json` is small and is what you poll. Its `build_id` concatenates the engine commit, the
survey-data commit and the build timestamp, so it changes whenever anything that could change the
output changed.

`build_provenance.json` is the longer record: the pipeline name and version, the extractor, the Python
version, the git commit, the dimensionality parameters the screening ran with, corpus counts, the
distribution flags in force and the build cache statistics. Use it when you need to say in a paper
exactly what produced the numbers you used.

Both are documented field by field in
[Served documents](../reference/portal-documents.md#buildjson).

### `feed.xml`

A minimal Atom 1.0 feed at `/data/feed.xml`, not at the site root. One entry per dated survey, newest
first, 21 entries in the current corpus. The entry id carries the slug, so resolve the survey from
there; entries carry no `<link>` element, because the build emits one only when it is given a site base
URL and the production invocation is not.

The element reference and the date rule are in
[Served documents](../reference/portal-documents.md#feedxml).

---

## Fetching data today

These are the patterns for the current build, as opposed to the frozen snapshots described under
[the releases tier](#the-releases-tier). There is no key to obtain and no quota to stay under, and every
response carries `Access-Control-Allow-Origin: *`, so a browser application can fetch it cross-origin.

Every example sets `BASE` to the portal root it reads from, and joins the site-relative paths onto it.

The portal's own About page carries a short quickstart. This is the long version.

### Whole-survey bundles

One request per survey, keyed by the survey slug (`vulcan-2022` and the like). Each published survey is
packaged three ways:

```text
/data/bundles/<slug>-edi.zip     every served station of that survey as EDI
/data/bundles/<slug>-xml.zip     the same stations as EMTF XML
/data/bundles/<slug>-tf.h5       the survey's transfer functions as MTH5
```

```bash
BASE=${AUSMT_BASE:?the portal root you are reading from}
curl -O "$BASE/data/bundles/vulcan-2022-edi.zip"
```

A `LICENSE.txt` rides inside each zip, carrying that survey's licence and its required attribution.
The MTH5 bundle is a single HDF5 file, so its licence is an attribute instead:
`Experiment/Surveys/<slug>` carries `release_license`, alongside `project_lead.author`, the ORCID and
the funding source.

To find a slug, read `/data/mtcat.json`. Its survey records carry the slug under `survey_id`, and
`/data/surveys.json` carries the same value under `slug`.

Nineteen of the 21 live surveys have bundles, three each, which is the 57 rows in the manifest's
`bundles` list. The two that don't are the embargoed ones.

### Per-station fetch through the manifest

Fetch `/data/products/manifest.json` once, filter its `files` rows by `format` (`edi` or `emtfxml`) and
by `survey`, then fetch `/data/` joined to each row's `url` and check the bytes against that row's
`sha256`.

Go through the manifest rather than building paths yourself. A served filename is not derivable from the
station id, so the manifest is the only correct way to locate one station's file. In the current corpus,
station A1 of `vulcan-2022` is served as `edi/vulcan-2022/Vulcan_A1.edi`.

The manifest's other list, `bundles`, holds the whole-survey artifacts above and the third format,
`mth5`, which exists per survey rather than per station. Don't filter station rows by `mth5`; there are
none.

```bash
BASE=${AUSMT_BASE:?the portal root you are reading from}
curl -s "$BASE/data/products/manifest.json" \
  | jq -r '.files[] | select(.survey=="Vulcan 2022" and .format=="edi") | "\(.url) \(.sha256)"' \
  | while read -r url sha; do
      curl -s -O "$BASE/data/$url"
      echo "$sha  $(basename "$url")" | shasum -a 256 -c -
    done
```

The same loop in Python, standard library only:

```python
import hashlib, json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
man = json.load(urllib.request.urlopen(f"{BASE}/data/products/manifest.json"))
for r in man["files"]:
    if r["survey"] != "Vulcan 2022" or r["format"] != "edi": continue
    body = urllib.request.urlopen(f"{BASE}/data/{r['url']}").read()
    assert hashlib.sha256(body).hexdigest() == r["sha256"], r["url"]
    open(r["url"].split("/")[-1], "wb").write(body)
```

Note that the `files` filter above matches on the survey DISPLAY name, which is what a manifest row
carries, not the slug. `au.<slug>.` as a prefix test on `ausmt_id` works too and is less fragile.

An embargoed survey has no rows in the manifest at all. Its bytes are withheld by construction, so
there's nothing to request and no access error to handle, while its catalogue record stays public.

### Bounding-box fetch

`/data/catalogue.json` is one row per station, and the rows are POSITIONAL arrays rather than objects.
Every column is read by index, with no field names in the file. The authoritative column map is
`/src/contract.js`, generated from the one file that defines the column order, so take indices from
there rather than counting them. A bounding-box fetch needs three:
`lat` at index **2**, `lon` at index **3**, and `ausmt_id` at index **12**. Columns are only ever
appended, never reordered.

Filter the catalogue to the box, join to the products manifest on `ausmt_id` (the one identifier both a
catalogue row and a manifest row carry), then fetch each matched row's `url` under `/data/` and check its
`sha256`.

```python
import hashlib, json, os, pathlib, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
LAT, LON, AUSMT_ID = 2, 3, 12               # column indices; /src/contract.js is the map
W, S, E, N = 133.0, -30.0, 135.0, -28.0     # west, south, east, north
cat = json.load(urllib.request.urlopen(f"{BASE}/data/catalogue.json"))
ids = {r[AUSMT_ID] for r in cat
       if r[LAT] is not None and r[LON] is not None
       and S <= r[LAT] <= N and W <= r[LON] <= E}
man = json.load(urllib.request.urlopen(f"{BASE}/data/products/manifest.json"))
for row in man["files"]:
    if row["ausmt_id"] not in ids or row["format"] != "edi": continue
    body = urllib.request.urlopen(f"{BASE}/data/{row['url']}").read()
    assert hashlib.sha256(body).hexdigest() == row["sha256"], row["url"]
    out = pathlib.Path(row["url"])          # mirror the manifest path, do not flatten it
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
```

Two coordinate caveats apply to any box filter.

A station whose position its custodian **withholds** carries `null` in the lat and lon columns, so the
example tests for null before comparing and those stations are excluded rather than compared. A null is
not a position, and no box contains one. Do not leave that to the language. JavaScript reads `null` as
`0` in a numeric comparison, which silently treats a withheld station as if it sat at 0°, 0° instead of
dropping it.

A station whose position is **generalised** at the custodian's request is served rounded to a 0.1° cell,
roughly 11 km, so a box edge is approximate. A generalised station can land on the wrong side of it by up
to 0.05°. The build emits `/data/coord_policy.json`, a map of `ausmt_id` to `generalised` or `withheld`,
whenever any station is non-exact. The file is absent when every served position is exact, so a `404`
there means every position is as surveyed.

One practical note. A box crosses surveys, and two surveys can hold a station with the same filename, so
write files out under the manifest's `url` path rather than flattening them to a basename or you will
lose one of the pair.

---

## Per-station products

Each station has a small product directory:

```text
/data/products/<slug>/<station>/station.json
/data/products/<slug>/<station>/dimensionality.json
```

`station.json` is the per-station record. It carries identity, location, band and period range, the
derived diagnostics, the processing strings read from the source file, the distribution state, the
coordinate QC verdict, any canonical conditioning notes, and a `provenance` block naming the input file
and its SHA-256. `dimensionality.json` is the phase-tensor screening result:

```console
$ curl -s "$BASE/data/products/vulcan-2022/A1/dimensionality.json"
{
 "classification": "2-D",
 "skew_beta_median_deg": 0.7,
 "pct_periods_3d": 0,
 "method": "phase-tensor (Caldwell 2004)",
 "screening_diagnostic": true,
 "note": "screening diagnostic, not an interpretation product"
}
```

The `note` travels with the payload. This is a screening diagnostic and not an interpretation, so treat
it as a filter and not as a finding.

The two files are gated differently, and the difference matters if you loop over stations:

| | Open survey | Withheld survey |
|---|---|---|
| `station.json` | Full record | `200`, with `"withheld": true`, an `access` block, and no derived science |
| `dimensionality.json` | Full record | `404`, never written |

So `station.json` always resolves and is worth requesting for any station; `dimensionality.json` should
only be requested when the survey's `access` is `open`. Check `mtcat.json` first, and don't treat that
`404` as a transport error.

There is no index of product directories. Directory listing is off. Build the paths from the slug and
the station id in `catalogue.json` or `mtcat.json`, which is safe here because the product path uses
the station id verbatim, unlike an artifact filename.

Both records are documented field by field in
[Per-station products](../reference/station-products.md).

---

## Selecting a format

Three formats are distributed, and which ones exist for a survey is stated, never implied.

| Format token | Where it appears | Granularity |
|---|---|---|
| `edi` | manifest `files[].format` | per station |
| `emtfxml` | manifest `files[].format` | per station |
| `edi-zip` | manifest `bundles[].format` | per survey |
| `xml-zip` | manifest `bundles[].format` | per survey |
| `mth5` | manifest `bundles[].format` | per survey |

The manifest is the answer that always works, because it is the thing the formats are derived from:

```python
import collections, json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
man = json.load(urllib.request.urlopen(f"{BASE}/data/manifest.json"))
per_station = collections.Counter(r["format"] for r in man["files"])
per_survey = collections.Counter(b["format"] for b in man["bundles"])
print(per_station, per_survey)
```

That prints `Counter({'edi': 1182, 'emtfxml': 1182}) Counter({'edi-zip': 19, 'xml-zip': 19, 'mth5': 19})`
against the current corpus. To ask the same question per survey, group `bundles` by `slug`.

MTCAT carries a shortcut. Each survey record has a `formats` list derived from that same manifest during
the same build, so a harvester can filter without fetching 828 kB:

```python
import json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]
cat = json.load(urllib.request.urlopen(f"{BASE}/data/mtcat.json"))
for s in cat["surveys"]:
    if "xml-zip" in s.get("formats", []):
        print(s["survey_id"])
```

Absence of the key means "not known" rather than "nothing served"; an empty list means the opposite, and
is what an embargoed survey serves. An AusMT build always derives the key from a manifest it has just
written, so an AusMT document always carries it. Absence is reserved for a producer with no manifest to
derive from.

---

## Watching for new or changed data

Two documents answer two different questions.

`feed.xml` answers "has a survey been added or updated?". It is an Atom feed, so an existing feed
reader handles it, and the entry id carries the slug you would then fetch.

`build.json` answers "is what I hold still current?". It is 300 bytes and its `build_id` changes on any
rebuild, including one that only changed a survey's metadata:

```bash
curl -s "$BASE/data/build.json" | jq -r .build_id
```

A polling client should compare `build_id`, not the `generated` timestamp on its own, and should send a
conditional request so an unchanged document costs a `304` instead of a download:

```python
import json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]                 # the portal root you are reading from
known_etag = None                               # persist this between polls; None on the first one
req = urllib.request.Request(f"{BASE}/data/build.json")
if known_etag:                                  # from the previous poll
    req.add_header("If-None-Match", known_etag)
try:
    resp = urllib.request.urlopen(req)
    known_etag = resp.headers.get("ETag")
    build_id = json.load(resp)["build_id"]
except urllib.error.HTTPError as e:
    if e.code != 304: raise                     # 304 means nothing changed
```

Poll gently. The site is one small server, the data changes on the order of days, and there is no
rate limiter to protect it from a tight loop.

---

## The releases tier

The documents above describe the current build, and the current build moves. Build directories are
pruned and the pointer to the current build is swapped every rebuild, so neither is a citable target.

The release tier is the citable one. It freezes one build's catalogue surface (`mtcat.json`,
`surveys.json`, `manifest.json`) plus every per-survey bundle into `/data/releases/<tag>/`, writes a
`release.json` provenance document beside them, and updates a newest-first index at
`/data/releases/releases.json`.

```text
/data/releases/releases.json          the index: tag, cut time, doi, build_id, counts, path
/data/releases/<tag>/release.json     that release's own record, including per-file size + sha256
/data/releases/<tag>/datacite.json    a DataCite record, prepared but not submitted
/data/releases/<tag>/mtcat.json       the frozen catalogue surface
/data/releases/<tag>/bundles/         the frozen artifacts
```

Every copied bundle is re-hashed from the bytes that landed in the release directory and checked
against the manifest's own SHA-256 claim. Any mismatch fails the cut and leaves no release behind. An
existing tag is never overwritten.

**No release has been cut yet.** `/data/releases/releases.json` returns `404`, and the portal's
Releases page says "No releases cut yet" and names the document it looked for.

A consumer should copy that distinction. A `404` or an empty `releases[]` means none is published. Any
other error means this request could not find out, which is a different fact and usually an operator's
problem.

The tooling mints nothing. It prepares a DataCite record that can be submitted as it stands, with the
minted DOI stamped back into the release that already exists. Until then a release's `doi` is `null`,
and a consumer renders that as plain text rather than as a link.

The documents are specified in the [Releases tier reference](../reference/releases.md), and the policy
is in [Versioning and releases](../data-model/versioning.md).

---

## What the portal does that this page does not

The browser portal builds custom downloads from an arbitrary station selection, zips them client-side
and writes a citation pack (`CITATIONS.txt`, `citations.bib`, `citations.ris`) into the archive. That
work happens in the browser, from the same documents listed above, and there is no server endpoint
behind it. If you want the same result from a script, select from `catalogue.json`, fetch through the
manifest, and assemble the citation from `surveys.json`'s `cite` and `creators` fields.
