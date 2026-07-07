"""`python -m gateway.runner` — the runner's entrypoint inside the engine image (design §5). No
network, non-root, resource-capped by compose. Loops forever claiming jobs.
"""
from __future__ import annotations

import logging

from .runner import RunnerConfig, run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s gateway.runner %(message)s")

if __name__ == "__main__":
    run_forever(RunnerConfig.from_env())
