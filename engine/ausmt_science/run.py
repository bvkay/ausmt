"""DEPRECATED entry point.

There is exactly ONE canonical build pipeline now:

    python -m extract.build_portal --surveys <surveys_dir> --out <portal_data> --products <products>

`run.py` used to be a second, mt_metadata-based path that also wrote products. Having two
pipelines that both generate products is a correctness hazard (divergent outputs, a script
doubling as an import), so it has been retired. The mt_metadata/MTH5 extractor — the
long-term canonical model (Kelbert lens) — IS now the sole engine in `extract.build_portal`
(via the `--extractor mt_metadata` option, its only value). `run.py` is permanently retired and
only prints this notice; use the single pipeline shown above.
"""
import sys


def main(argv=None):
    sys.stderr.write(__doc__ + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
