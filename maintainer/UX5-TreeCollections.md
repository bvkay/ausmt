# UX5 — Tree disclosure carets + Collections toggle group (frozen design)

Maintainer requests (2026-07-07): (1) a collection level in the country→org→survey rail, shown FIRST;
(2) expand/collapse triangles on the higher levels.

## D6. Collections toggle group — first, cross-cutting, push-only
Collections are CROSS-CUTTING (a programme can span orgs), so they are NOT a nesting level:
a "Collections" group renders FIRST in #tree, ABOVE all countries, only when the boot data has
collections (same non-empty gating as the Collections tab). One row per collection:
caret + checkbox + "<name> — <n> surveys · <m> stations". The checkbox is a PUSH-ONLY bulk
toggle with exactly the country/org semantics: on change, set every member survey's checkbox
to this checked state (member surveys identified by LABEL — COLL[cid].surveys holds survey
labels and the tree's survey checkboxes use value=<label>, a direct match) and call refresh().
No derived/indeterminate state (country/org don't either — noted as future polish in the doc).
The caret expands PASSIVE member rows (indented name + station count, NO checkbox — the org
hierarchy keeps per-survey toggling; avoids three-way sync). Org rows/counts are untouched —
member surveys still live under their orgs.

## D7. Disclosure carets — visibility is not filtering
Country, org, and collection rows gain a caret (▸/▾) with its OWN click target — the rows are
label-wrapped checkboxes, so the caret must be a separate element whose click neither toggles
the checkbox nor bubbles into the label. Default: everything expanded (today's appearance
preserved). Collapse hides the DESCENDANT ROWS ONLY (org rows + survey rows under a country;
survey rows under an org; member rows under a collection).
INVARIANT (test-pinned): collapsing/expanding NEVER changes any checkbox state and NEVER
changes the filter result — checked-but-hidden surveys remain visible on the map. Collapse
state is in-memory only (no persistence — polish item).

## D8. Tour tree step rides the carets
The D5 tree demo step must ensure its target row's ancestors are EXPANDED before
scrollIntoView (use the same caret API), and the exit hook restores the pre-step
expand/collapse state along with the scroll.

## Tests (each must be able to fail)
- Collections group renders FIRST (before any .country row) and only when collections exist
  (empty COLL → no group; prove the ordering assertion fails on the UX4 head).
- Collection checkbox push-sync: checking/unchecking flips exactly the member surveys'
  checkboxes (non-members untouched) and triggers refresh.
- THE invariant: collapse a country/org/collection with mixed checkbox states → assert every
  checkbox state identical before/after AND the visible-station filter result identical;
  expand → same. Prove it can fail by temporarily wiring collapse to uncheck (mutation on a
  scratch copy), not by trusting construction.
- Caret click does not toggle the row checkbox (regression for the click-target hazard).
- Tour step: ancestors expanded on enter; prior expand state restored on all three exit paths.

## Branch note

STACKED: fix/ux-feedback-round5 branches from the UX4 head 77d6903 (fix/ux-feedback-round4)
and merges AFTER UX4 — it builds directly on UX4's partitionMarkers/AUSLAMP_SET plumbing and
the D5 tour tree step (which D8 above extends).

## Preview verification (2026-07-07, real-data, both scratch builds)

611-station build (no kalkaroo): Collections group renders FIRST ("Collections" heading; row
"AusLAMP — 2 surveys · 453 stations"; passive members 396/57); push-toggle drives the map
(uncheck -> 158 = olympic-dam + vulcan only; recheck -> 611); all three caret levels collapse/
expand (collection members, 3 org rows, 4 survey rows hidden; ▸/▾ glyphs; expand -> 0 hidden);
the INVARIANT held live (checkbox states + visible count byte-identical through collapse and
expand; collapsed-rail screenshot shows exactly two rows while "611 shown" persists); caret
clicks toggled no checkbox; D8 tour restore verified on ALL THREE exit paths against collapsed
ancestors (degrade target "AusLAMP South Australia").

827-station build (with kalkaroo-2022): collection row unchanged ("2 surveys · 453 stations" —
kalkaroo correctly not a member); tour tree step targets "Kalkaroo 2022", expands its collapsed
ancestors, row visible, close restores; push-toggle 827 -> 374 -> 827. Zero console errors in
both runs.

Implementation notes vs the frozen text: the "Collections" group renders with a small
.treegroup heading (in the rail's caps-muted style); survey-row indent bumped 34px -> 52px so
nesting still reads with carets present; collection rows styled like .country (both are bulk
toggles). Falsifiability: the ordering probe FALSIFIED on the UX4 head (collIdx=-1); a scratch
mutant wiring collapse->uncheck-hidden failed the invariant with the exact state diff
(Alpha/Delta true->false), driver exit 1.
