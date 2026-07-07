# UX4 — AusLAMP separation, clustering tiers, zoom-scaled markers (frozen design)

Maintainer requests (2026-07-07): (1) separate AusLAMP surveys from legacy long-period so new users
aren't confused by lesser-quality legacy LP data; (2) group sites at continental AND state
zoom, individual from regional/provincial down; (3) markers read too large at national zoom
but right when zoomed in.

## D1. AusLAMP is a programme, not a data type
Classification is COLLECTION MEMBERSHIP, not a new data type: a station is "AusLAMP" iff its
survey slug is a member of the collection with id `auslamp` in collections.json (already
fetched at boot, data.js). LPMT remains the scientific data type for both classes — we never
fork the type vocabulary for a programme name. Pure helper:
  `isAuslampSurvey(slug, auslampSet)` and a boot-built `AUSLAMP_SET` (empty set when
  collections.json is absent or has no auslamp collection — graceful degrade: everything
  behaves as before the split).
Visual: AusLAMP keeps the existing LPMT teal (#2E8FA3, the flagship association); non-AusLAMP
long-period gets a muted slate tone (start at #6E8577, tune in preview against DIM_COL and
quality palettes). Legend (type colour-mode) gains the extra swatch: "AusLAMP (LPMT)" and
"Long period (other)". Tooltip appends " · AusLAMP" for members. Type filter chips are
UNCHANGED (type stays LPMT for both).

## D2. Never-cluster privilege moves from type to programme
UX3 exempted type==="LPMT" from clustering so the AusLAMP national grid reads as a grid.
That exemption now belongs to the AusLAMP class itself: partitionMarkers() splits on
isAuslampSurvey (member -> plain layerGroup, never clustered), everything else — including
legacy LPMT like olympic-dam-2004 — rides the markerClusterGroup. Rationale: at national
zoom the map should show THE GRID plus ordinary count bubbles; 58 legacy LP dots
masquerading as grid coverage is exactly the reported confusion. (Supersedes the
UX3 type-based rule; GDS stays clustering per the still-open maintainer decision.)

## D3. Clustering tiers
DISABLE_CLUSTERING_AT_ZOOM: 6 -> 7. Grouped at continental (z<=4) and state (z5-6) zoom;
every site individual from regional zoom (z>=7) down. maxClusterRadius stays 24;
spiderfyOnMaxZoom stays false. The pinned-value test updates 6 -> 7 with the new rationale
in its docstring. (Supersedes the C32 continental-only comment — update the map.js comment
block to carry the decision trail.)

## D4. Zoom-scaled marker radii
Pure step function, unit-tested, single source for both initial draw and zoomend updates:
  radiusForZoom(z): z<=4 -> 3.5 ; z===5 -> 4.5 ; z===6 -> 5 ; z>=7 -> 6
  weightForZoom(z): z<=4 -> 1.0 ; else 1.5
buildMarkers() uses radiusForZoom(map.getZoom()) instead of the literal 6; a zoomend
handler restyles all markers (preferCanvas is already on; restyle of ~1200 circleMarkers
per zoom step is acceptable). Cluster bubble sizes are UNCHANGED (count-driven). Values are
starting points — tune in the real-data preview and record the final table in this doc.

## Tests (all must be able to fail)
- partitionMarkers: auslamp-member LPMT -> unclustered; NON-member LPMT -> clustered (the
  new behaviour, must fail on pre-UX4 code); BBMT/AMT/GDS -> clustered; empty AUSLAMP_SET
  degrades to all-clustered.
- radiusForZoom/weightForZoom: pinned values above + monotone non-decreasing in z.
- DISABLE_CLUSTERING_AT_ZOOM === 7 pin (update existing test).
- isAuslampSurvey: membership true/false/absent-collection cases.
- Legend/colour: type-mode colour for member vs non-member LPMT differs; non-type colour
  modes (quality, dim) are IDENTICAL for both classes.

## Final values (preview-verified 2026-07-07)

Real-data subset built with the local engine (auslamp-sa 396 + auslamp-tas 57 + olympic-dam-2004
58 + vulcan-2022 100 = 611 stations across 4 surveys) and served against the wt-ux4 portal. The D4
starting values held under the real basemap (CARTO light) and were NOT changed — recorded here as
the frozen final table:

| zoom (z) | tier                | radius | weight |
|----------|---------------------|--------|--------|
| z<=4     | continental/national| 3.5    | 1.0    |
| z==5     | state               | 4.5    | 1.5    |
| z==6     | state               | 5      | 1.5    |
| z>=7     | regional/provincial | 6      | 1.5    |

Colours (type mode), final:
- AusLAMP (LPMT):       #2E8FA3 (flagship teal, unchanged)
- Long period (other):  #6E8577 (muted slate — verified distinguishable-but-related vs the teal on
  the CARTO light basemap; olive-slate reads clearly separate from teal at z7-8 while staying in the
  same muted blue-green family). NOT changed from the D1 starting value.
- BBMT contrast unchanged: #E0782F.

Preview observations (all as designed):
- z4 national: AusLAMP grid = individual small teal dots; the co-located legacy Olympic Dam + Vulcan
  (both ~-30.1,137.0 in the Gawler region — NOT geographically separate) collapse into ONE count
  bubble ("158"). This is exactly the "legacy LP masquerading as grid coverage" complaint, fixed.
- z5/z6 state: AusLAMP grid individual; legacy/BBMT still count bubbles (separating as z rises).
- z7 regional: clusters disabled (0 bubbles), radius 6; legacy Olympic Dam now individual muted-slate
  dots among the teal AusLAMP grid — the D1 colour split is legible.
- z8: whole-dataset colour census teal 453 / slate 58 / orange 100 = exact per-survey counts.
- zoomend restyle verified bidirectional (radii grow zooming in, shrink zooming out).
- Tooltip: AusLAMP member "EP001 · LPMT · AusLAMP · Q 3.9"; legacy "ROX000 · LPMT · Q 3.8" (no tag).
- No console errors on boot or during zoom.

## Deviation flagged for the maintainer: the colour-mode LEGEND swatch (D1)

[RESOLVED-MOOT by Amendment A1 below — no second colour remains to explain.]

D1 asks the "Legend (type colour-mode)" to gain two swatches ("AusLAMP (LPMT)" / "Long period
(other)"). The portal has NO on-map colour-mode legend component: the only place type colours appear
as labelled swatches is the Data-type FILTER-CHIP fieldset (#typeBoxes, index.html) — which D1
explicitly says stays UNCHANGED (type is LPMT for both classes). So there is no existing legend to
add swatches to, and the contract forbids improvising a new UI component. This lane therefore ships
the SUBSTANTIVE D1 colour split (markerColor teal vs slate, tooltip append) and its test, but does
NOT add a DOM legend swatch — that needs a maintainer decision on WHERE a colour-mode legend should live
(a new on-map legend control, or leave the map self-explanatory via tooltips). The colour/tooltip
tests fully cover the observable behaviour; only the legend-swatch DOM is deferred.

## Amendment A1 (maintainer, 2026-07-07) — revise D1; D2/D3/D4 stand exactly as built

The maintainer reviewed the built UX4 and revised the D1 visual treatment:

1. COLOUR SPLIT REMOVED. LPMT_OTHER_COL and the markerColor membership branch are deleted — ALL
   LPMT renders the flagship teal (TYPE_COL.LPMT #2E8FA3) in type mode regardless of AusLAMP
   membership. Colour modes are membership-blind everywhere (type now included; quality/dim were
   already). The colour rows of the "Final values" table above are SUPERSEDED accordingly.
2. TOOLTIP TYPE-LABEL SWAP. For AusLAMP members the tooltip's type slot shows "AusLAMP" INSTEAD OF
   the LPMT type label (not appended): member = `${id} · AusLAMP · Q n`; non-member unchanged =
   `${id} · LPMT · Q n`. The hover swap is now the SOLE AusLAMP/legacy visual distinction (plus the
   D2 clustering split). Implemented as a pure exported `tooltipText(s)` (Leaflet-free, same
   testability pattern as partitionMarkers).
3. TESTS: type-mode colour asserted IDENTICAL (teal) for member vs non-member LPMT; quality/dim
   membership-blind assertions kept; tooltip tests assert member contains "AusLAMP" and NOT "LPMT",
   non-member the reverse. Partition/zoom/radii tests untouched.
4. The D1 legend-swatch deviation (section above) is RESOLVED-MOOT: with a single LPMT colour there
   is no second swatch to explain.

## D5. Tour v4 — Find demo + tree browse steps (maintainer request, 2026-07-07)

Two new steps inserted after the filter-rail overview (tour grows 8 -> 10 steps). Both are map-view
steps whose enter actions force the map view (composing with tour v3's back-nav discipline), and both
get EXIT hooks — a new per-step `exit` callback run on ALL three ways of leaving a step (Next, Back,
and mid-tour close/Esc via stopTour) — so demo state never leaks.

- FIND DEMO (step 3, sel #find): the enter action saves the visitor's current Find value, types
  "AusLAMP" into the box and dispatches a REAL bubbling input event, so the live handler chain
  (refresh() + renderFind()) filters the map and renders the actual dropdown with real matches. Step
  text explains find-by-name filtering. The exit hook restores the saved value (dispatching input
  again, so the filter state is genuinely restored, not just cosmetically) and hides the dropdown —
  matching the click-away behaviour.
- TREE BROWSE (step 4, sel #tree): the enter action saves the tree's scroll position and brings one
  survey row into view — kalkaroo-2022 preferred (resolved via SLUG_TO_SURVEY, the authoritative
  slug->label map), degrading gracefully to the FIRST survey present when kalkaroo is absent (the
  tour must never crash on a data-dependent id; empty portal -> centred card, existing pattern).
  Step text explains the country -> organisation -> survey hierarchy. NOTE ON RESTORE SCOPE: the
  tree is a FLAT always-expanded scrollable list (buildTree() renders every row; there is no
  expand/collapse API), so "expand to show" is implemented as scrollIntoView of the survey row and
  restore = putting the saved scrollTop back on exit. The step changes NO checkbox state, so scroll
  position is the entire prior state.

### A1 + D5 preview verification (2026-07-07, real-data)

Run 1 (611-station build, kalkaroo-2022 ABSENT): colour census teal 511 / slate 0 / orange 100 (A1:
every LPMT teal, split gone); tooltips "EP001 · AusLAMP · Q 3.9" (member swap) vs "ROX000 · LPMT ·
Q 3.8" (legacy, unchanged); tour = 10 steps; Find demo live-filtered 611 -> 453 with the real
dropdown (collection + both surveys); tree step DEGRADED to "AusLAMP South Australia" (first survey)
— the graceful-degrade path exercised live; all exit paths clean (forward, back-re-entry, mid-tour
Esc at the Find step, Esc at the tree step, and the full 10-step walk to Done): find box empty,
dropdown closed, station count restored, map view, tour DOM removed, tree scroll back. No console
errors.

Run 2 (827-station rebuild WITH kalkaroo-2022, 216 stations): SLUG_TO_SURVEY resolves
kalkaroo-2022 -> "Kalkaroo 2022" and the tree step targets it (the preferred path); kalkaroo
correctly CLUSTERS (non-member: clustered 374 = kalkaroo 216 + olympic-dam 58 + vulcan 100;
unclustered 453 = the two AusLAMP surveys); D3 pin 7 and D4 radii unchanged. NOTE: with only 5
surveys the tree does not overflow (scrollHeight == clientHeight), so scrollIntoView is a
legitimate no-op and scrollTop stays 0 — in a production-sized tree the row scrolls to centre;
the row was verified fully visible inside the tree viewport.
