# Why coordinates have an access policy

A survey can declare how its station coordinates are served: `exact`, `generalised` to 0.1 degrees, or
`withheld`. Individual stations can override the survey default. The field is `access.coordinates`,
documented in [survey.yaml](../reference/survey-yaml.md#85-accesscoordinates).

A station sits on somebody's land, often reached under a land-access agreement, and sometimes on country
whose custodians have a view about publishing site positions. Access to the position is a separate
question from access to the data: an embargo that hides the impedance and publishes the pin misses the
point. The custodian decides, not AusMT, which is why the three levels are coarse rather than a
continuous precision dial.

Three implementation choices carry most of the weight.

One masking seam. Coordinates are parsed, quality-checked against their true values, masked once in
place, and only then emitted. No emitter applies its own mask and the portal never re-rounds, so there
is no second copy of the rule to drift. Generalisation is one rounding function in one module.

Withholding hides the position, not the station. A withheld station keeps its catalogue row, its
response curves and its place in its survey. Dropping the row would break the positional alignment the
data contract rests on and would hide the science, which was not asked for. The survey's position falls
back to the curator-declared `geographic_extent`, never a value computed from the stations it exists to
protect.

The failure mode is refusal. An unknown policy value or an override naming a station that does not
exist drops that survey from the build loudly. It never falls back to `exact`, because a silent fallback
would serve the exact position the curator asked to protect at a green exit code.

Coordinate access is separate from `coordinate_resolution`, which corrects a DMS sign bug in EDI
headers. One is a rights decision, the other a data-quality fix.

The implementation is
[`engine/extract/_coordaccess.py`](https://github.com/bvkay/ausmt/blob/main/engine/extract/_coordaccess.py),
which holds the mask seam, the rounding function and the per-station byte gate.
