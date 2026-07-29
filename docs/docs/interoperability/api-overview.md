# How AusMT serves data

AusMT has one machine interface and it is a set of files. Everything a program needs sits under
`/data/` as a static JSON document or a downloadable artifact, written once per build and served by a
web server that does no computation on the way out.

Every path in this documentation is relative to the portal root, so `/data/mtcat.json` means
`<portal root>/data/mtcat.json`; the examples take that root from a `BASE` variable you set to the
deployment you are reading from.

This page is the architecture. The [data reference](api-reference.md) lists every document and shows
the fetch patterns. [Tool integration](tool-integration.md) covers reading the artifacts from MT
software.

---

## Read-only static files

The build (`engine/extract/build_portal.py`) writes a directory tree. Caddy serves that tree. There is
no application server, no database and no query planner between a request and a file on disk.

Three things follow, and each one is checkable from a shell:

```console
$ BASE=${AUSMT_BASE:?the portal root you are reading from}
$ curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BASE/data/mtcat.json"
405
$ curl -s -o /dev/null -w '%{size_download}\n' "$BASE/data/mtcat.json?survey=vulcan-2022"
275587
$ curl -s -o /dev/null -w '%{http_code}\n' "$BASE/data/"
404
```

`GET` and `HEAD` are the only methods that do anything. A query string is accepted and ignored, so the
filtered request returns the whole document at its full length. Directory listing is off, so you cannot
walk the tree; you read an index document and follow the paths it gives you.

Selection happens in your client. That is the trade this design makes, and the
[limits](#what-does-not-exist) section below states what it costs.

---

## Caching and transport

Every response carries `ETag` and `Last-Modified`, so a conditional request works:

```console
$ ETAG=$(curl -sI "$BASE/data/mtcat.json" | tr -d '\r' | awk '/^etag:/{print $2}')
$ curl -s -o /dev/null -w '%{http_code}\n' -H "If-None-Match: $ETAG" "$BASE/data/mtcat.json"
304
```

Responses are gzipped when the client asks for it, and byte ranges are supported (`Range: bytes=0-99`
answers `206`), so a large bundle download can resume.

No `Cache-Control` header is set. A proxy or CDN in front of the site therefore applies its own
heuristic freshness rather than an instruction from us, and a cached copy can be stale for a while. If
being current matters to your workflow, read `data/build.json` and compare its `build_id` rather than
trusting a cache.

Builds land in timestamped directories under the data root, at `builds/<timestamp>/`, and a `current`
symlink is moved across them with `mv -T`, which is a real `rename(2)`. There is no window in which
`current` is missing or half updated, and Caddy resolves the symlink per request, so a swap takes
effect on the next request with no restart. A build that fails, or that passes but fails its verify
step, leaves `current` pointing at the previous build.

What the swap does not protect is a client reading several documents across a rebuild boundary. That
client can straddle two builds. Read `build.json` before and after if the documents have to agree with
each other.

---

## Cross-origin access

The `/data` handler sets `Access-Control-Allow-Origin: *`, so browser JavaScript on any origin can
fetch any data document directly:

```console
$ curl -sI "$BASE/data/mtcat.json" | grep -i access-control
access-control-allow-origin: *
```

The header is scoped to `/data` by that handler and nothing else carries it. `/src/contract.js`, for
instance, is a portal page asset and answers with no CORS header, so a browser application on another
origin has to fetch it server-side or hard-code the values it needs.

There is no preflight handler. An `OPTIONS` request answers `405`. A plain `fetch()` for JSON never
preflights, so this costs you nothing in practice, but a request that sets a custom header will
preflight and then fail. Don't set one.

---

## Integrity

Every artifact row in the download manifest carries the `size` and the `sha256` of the bytes the server
will hand you, so a download is checkable end to end without asking us anything:

```bash
curl -sO "$BASE/data/bundles/vulcan-2022-edi.zip"
python3 - <<'PY'
import hashlib, json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]
man = json.load(urllib.request.urlopen(f"{BASE}/data/manifest.json"))
row = next(b for b in man["bundles"] if b["url"] == "bundles/vulcan-2022-edi.zip")
print(row["sha256"] == hashlib.sha256(open("vulcan-2022-edi.zip", "rb").read()).hexdigest())
PY
```

The same digest appears in two other places, and they agree. `catalogue.json` carries the source
transfer-function file's SHA-256 in column 14, which for a served EDI is the same file and so the same
digest. Each station's `station.json` records `provenance.input_file` and `provenance.input_sha256` for
the file its derived products were computed from.

---

## Access levels and embargo by omission

A survey declares one of three access levels. `open` serves bytes. `metadata_only` and `embargoed` do
not, and anything the build cannot recognise fails closed alongside them.

An embargoed survey keeps its whole discovery record. Its title, organisation, licence, footprint,
creators, contributors and every one of its stations with coordinates stay public in `mtcat.json`.
There is no access control in front of its data, because the build writes not one row in the download
manifest for it.

In the live corpus, `kalkaroo-2022` and `vulcan-2024-25` are embargoed. Neither appears in
`manifest.files` or `manifest.bundles`, and the bundle path you would guess for them is a `404`:

```console
$ curl -s -o /dev/null -w '%{http_code}\n' "$BASE/data/bundles/kalkaroo-2022-edi.zip"
404
```

Kalkaroo's 216 stations are all still in `mtcat.json` with their coordinates and band, so a map or a
search index built from the catalogue shows the survey exists and says who to ask.

Per-station products follow the same rule with one wrinkle. `station.json` is written for every
station, and a withheld one carries `"withheld": true`, an `access` block giving the level and the
embargo date, and no derived science. `dimensionality.json` is not written at all for a withheld
station, because it is a pure interpretation of the transfer function being withheld, so that path
answers `404`.

For a client this means there is no authorisation branch to write. If a byte exists, it is in the
manifest. If it is not in the manifest, no request will produce it.

Coordinates are a separate axis. A custodian can ask for a station's position to be generalised
(rounded to 0.1°, roughly 11 km) or withheld (served as `null`). See
[Coordinate access](../rationale/coordinate-access.md) for why, and the bounding-box pattern in the
[reference](api-reference.md#bounding-box-fetch) for what it means when you filter on position.

---

## What does not exist

Query parameters do nothing. The server will not filter, search, sort, paginate, or render the
catalogue as GeoJSON or CSV. Everything the site knows how to do, it has already done by the time you
make a request.

Nor is there any authentication. That is not an omission waiting to be fixed. The read surface is the
public subset by construction, so a private survey is withheld by having no bytes on the server rather
than by having a guard in front of them. There is nothing for a credential to unlock.

Both of those are choices about scale. The live corpus is 21 surveys, 1,418 stations and 2,421
downloadable artifacts: a 276 kB discovery document, a 320 kB station catalogue and an 828 kB
download manifest. A client can hold all three in memory and filter them in a loop faster than a
query API would finish its TLS handshake. A query tier would add an always-on service to keep
alive, an invalidation story for its cache, and a second place where every access rule has to be
implemented correctly, and none of that buys a reader anything measurable at this size. The corpus
that would change the answer is one where the catalogue no longer fits in a client's memory or a
single request; AusMT is roughly two orders of magnitude away, and this page should be rewritten
when it isn't.

There is an upside worth naming. Nothing here can fail separately from the files. There is no service
to run out of connections and no index that can fall behind the data it indexes. Load changes how fast
you get an answer, never which answer you get. Copy the `/data` tree onto any static host and you have
a working AusMT endpoint.

---

## The one dynamic surface

`/gateway` is a real service, and it is for contributing rather than reading. At the public name only
four routes answer: `POST /gateway/submit`, `POST /gateway/request-key`, `GET /gateway/healthz` and
`GET /gateway/status/*`. Every other path under `/gateway`, which is the whole curator and admin
workbench, is an explicit `404` at the public edge and reachable only over the project's private
network.

```console
$ curl -s -o /dev/null -w '%{http_code}\n' "$BASE/gateway/healthz"
200
```

None of it reads survey data. See [Submission](../operations/submission.md) for what it does.
