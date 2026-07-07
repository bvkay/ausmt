"""`python -m gateway` — bind uvicorn on 0.0.0.0:8000 (container-internal; compose publishes it
loopback-only and Caddy fronts it, design §1). create_app() runs fail_closed_startup(), so a
missing/short AUSMT_SUBMIT_KEY aborts before the port is bound.
"""
from __future__ import annotations

import logging

import uvicorn

from .app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")  # noqa: S104 -- container-internal; Caddy/compose bound externally
