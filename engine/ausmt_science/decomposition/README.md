# decomposition/ — Tier 3

Galvanic distortion decomposition: Groom–Bailey, McNeice–Jones (multi-site/multi-freq),
Garcia–Jones, and Lilley Mohr circles. **Generated offline only.**

## Engine decision: depend on the fork, don't re-implement

Recommendation: **depend on `bvkay/mtpy-v2 @ feature/groom-bailey-decomposition`**, pinned
to a specific commit, rather than re-implementing decomposition here.

Reasoning:
- This code runs in CI, offline. MTpy-v2's package weight is a *portal* concern, and the
  portal never imports MTpy — so "MTpy is package-heavy" does not apply to this repo.
- Re-implementing Groom–Bailey / McNeice–Jones correctly (and validating it) is weeks of
  work that already exists, tested, in the fork.
- Coupling risk is contained by the product contract: the portal reads `decomposition.json`
  (see docs developer/product-schema.md), never the library. The engine can be
  swapped — re-implemented, replaced, or upgraded — without the portal noticing.

When to revisit (i.e., extract just the algorithms into a lean module here):
- if the fork can't be pinned/maintained, or
- if you need decomposition in an environment where the full dependency tree is a problem
  (not the case for offline CI), or
- if only one routine is needed and the rest of MTpy is dead weight in the lock file.

Either way: pin hard (conda-lock or Docker), record the engine + commit in
`decomposition.json["engine"]`, and present every result as a **diagnostic, not a
definitive geological solution** (McNeice–Jones as the primary display; Garcia–Jones as
cross-validation; Groom–Bailey + Mohr circles under "Advanced analysis").

## Output
`decomposition.json` and optional `mohr.svg` per station — schema in docs developer/product-schema.md.
