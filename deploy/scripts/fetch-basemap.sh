#!/bin/sh
# Produce the self-hosted basemap files the portal's pmtiles provider serves:
#
#   $AUSMT_DATA_DIR/basemap/world.pmtiles    the whole world at z0-6 (the zoomed-out globe)
#   $AUSMT_DATA_DIR/basemap/region.pmtiles   Australia + surrounds at z0-15 (full detail)
#
# Both are extracted server-side from the Protomaps daily planet build (OpenStreetMap-derived;
# attribution "(c) OpenStreetMap contributors (c) Protomaps" rides the map layer) WITHOUT
# downloading the ~120 GB planet: the pmtiles CLI fetches only the tiles the extract needs.
# Extracts land via tmp + mv so a torn download can never be served; re-run any time to refresh
# (yearly is generous for a backdrop; the served filenames stay stable so nothing else changes).
#
# The CLI binary is PINNED by version and sha256: an unpinned curl|sh of a release binary is a
# supply-chain hole this deployment does not accept.
#
# Usage (on the box, from deploy/):   AUSMT_DATA_DIR=/srv/ausmt sh scripts/fetch-basemap.sh
set -eu

: "${AUSMT_DATA_DIR:?set AUSMT_DATA_DIR (e.g. /srv/ausmt)}"

PMTILES_VERSION="1.31.2"
PMTILES_SHA256_LINUX_X86_64="3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f"
PMTILES_URL="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/go-pmtiles_${PMTILES_VERSION}_Linux_x86_64.tar.gz"

# The daily planet build; the day is resolved from the published latest pointer so the script
# needs no date argument. Override AUSMT_BASEMAP_SOURCE to pin a specific build.
SOURCE="${AUSMT_BASEMAP_SOURCE:-$(curl -fsSL https://build-metadata.protomaps.dev/builds.json | grep -o '"key": *"[^"]*"' | tail -1 | cut -d'"' -f4 | sed 's#^#https://build.protomaps.com/#')}"
[ -n "$SOURCE" ] || { echo "ERROR: could not resolve the latest Protomaps build; set AUSMT_BASEMAP_SOURCE" >&2; exit 1; }

# Australia + surrounds: generous on every side so neighbouring coastlines have context.
REGION_BBOX="108,-45.5,157,-8"

OUT="$AUSMT_DATA_DIR/basemap"
WORK="$OUT/.work"
# The data root usually belongs to root or the container user, so the FIRST run needs a one-time
# bootstrap; every later run (including refreshes) works unprivileged.
if ! mkdir -p "$OUT" "$WORK" 2>/dev/null; then
	echo "ERROR: cannot create $OUT (the data root is not writable by $(id -un))." >&2
	echo "One-time bootstrap, then re-run this script:" >&2
	echo "  sudo mkdir -p $OUT && sudo chown $(id -un):$(id -gn) $OUT" >&2
	exit 1
fi

echo "fetch-basemap: pmtiles CLI v$PMTILES_VERSION (pinned)"
if [ ! -x "$WORK/pmtiles" ]; then
	curl -fsSL -o "$WORK/pmtiles.tgz" "$PMTILES_URL"
	echo "$PMTILES_SHA256_LINUX_X86_64  $WORK/pmtiles.tgz" | sha256sum -c - >/dev/null
	tar -xzf "$WORK/pmtiles.tgz" -C "$WORK" pmtiles
	rm -f "$WORK/pmtiles.tgz"
fi

echo "fetch-basemap: source build $SOURCE"

echo "fetch-basemap: extracting world.pmtiles (z0-6, whole planet)"
"$WORK/pmtiles" extract "$SOURCE" "$OUT/world.pmtiles.tmp" --maxzoom=6
mv "$OUT/world.pmtiles.tmp" "$OUT/world.pmtiles"

echo "fetch-basemap: extracting region.pmtiles (bbox $REGION_BBOX, z0-15)"
"$WORK/pmtiles" extract "$SOURCE" "$OUT/region.pmtiles.tmp" --bbox="$REGION_BBOX" --maxzoom=15
mv "$OUT/region.pmtiles.tmp" "$OUT/region.pmtiles"

ls -lh "$OUT"/world.pmtiles "$OUT"/region.pmtiles
echo "fetch-basemap: done. Flip portal.config.yaml basemap.provider to pmtiles (and regenerate"
echo "config.js) in the repo to serve these; rollback is flipping the provider back to carto."
