# Why coordinates have an access policy

## What it is

A survey can declare how its station coordinates are served: `exact`, `generalised` to 0.1 degrees,
or `withheld`. Individual stations can override the survey default. The field is
`access.coordinates`, documented in
[survey.yaml Reference](../reference/survey-yaml.md#accesscoordinates).

## Why it is built that way

Before this, station coordinates were universally public by design. The access drawer told readers
that station locations and survey metadata are public even for embargoed surveys, because the
embargo machinery withheld bytes and response curves only. That was a deliberate stance, and it
was the wrong one for some real datasets. A station sits on somebody's land, often reached under a
land-access agreement, and sometimes on country whose custodians have a view about publishing site
positions. An embargo that hides the impedance and publishes the pin misses the point.

The custodian decides, not AusMT. That is the whole ruling. AusMT's job is to carry the decision
faithfully, which is why the three levels are coarse and easy to reason about rather than a
continuous precision dial. A curator can say what they mean in one word.

Three implementation choices carry most of the weight.

There is exactly one masking seam. Coordinates are parsed, quality-checked against their true
values, masked once in place, and only then emitted. No emitter applies its own mask, and the
portal never re-rounds, so there is no second copy of the rule to drift. Generalisation is one
rounding function in one module.

Withholding hides the position, not the station. A withheld station keeps its catalogue row, keeps
its response curves, and still lists inside its survey. Dropping the row instead would break the
positional alignment the whole data contract rests on, and it would also hide the science, which
is not what was asked for. The survey's position falls back to the curator-declared
`geographic_extent`, a value a human wrote down, never one computed from the stations it exists to
protect.

The failure mode is refusal. An unknown policy value or an override naming a station that does not
exist drops that survey from the build loudly. It never falls back to `exact`, because a silent
fallback would serve the exact position the curator asked to protect, at a green exit code. One
survey's typo fails that survey and leaves the rest of the corpus building.

Coordinate access is a separate concern from `coordinate_resolution`, which corrects a DMS sign bug
in EDI headers. The two are easy to confuse and must not be conflated: one is a rights decision,
the other is a data-quality fix.

## Where the depth is

The frozen design record is
[`maintainer/C42-CoordinateAccess.md`](https://github.com/bvkay/ausmt/blob/main/maintainer/C42-CoordinateAccess.md),
which includes the full leak inventory that motivated it. The implementation is
[`engine/extract/_coordaccess.py`](https://github.com/bvkay/ausmt/blob/main/engine/extract/_coordaccess.py).
