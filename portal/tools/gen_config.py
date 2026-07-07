#!/usr/bin/env python3
"""Regenerate config.js from portal.config.yaml.

portal.config.yaml is the single human-editable source of truth for branding, version and deployment.
config.js is the browser-side reflection the static pages load. Run this after editing the YAML:

    python3 tools/gen_config.py

Requires PyYAML (a declared engine dependency, installed in CI); the stdlib fallback parser was retired.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YAML = ROOT / "portal.config.yaml"
OUT = ROOT / "config.js"


def _load_yaml(text):
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        sys.exit("ERROR: gen_config.py requires PyYAML (pip install PyYAML). It is a declared engine "
                 "dependency and is installed in CI; the bespoke stdlib fallback parser was retired.")
    return yaml.safe_load(text)


def build_config(cfg):
    p = cfg.get("portal", {})
    d = cfg.get("deployment", {})
    a = cfg.get("analytics", {})
    f = cfg.get("flags", {})
    return {
        "portal_id": p.get("id", "ausmt"),
        "name": p.get("name", ""),
        "short_name": p.get("short_name", "AusMT"),
        "region": p.get("region", ""),
        "schema": p.get("schema", "MTCAT"),
        "schema_version": str(p.get("schema_version", "1.0")),
        "version": str(p.get("version", "0.0.0")),
        "pages_base_url": d.get("pages_base_url", "") or "",
        "mtcat_url": d.get("mtcat_url", "") or "",
        "data_base_url": d.get("data_base_url", "") or "",
        "analytics": {"enabled": bool(a.get("enabled", False)),
                      "plausible_domain": a.get("plausible_domain", "") or ""},
        "flags": {"survey_h5_enabled": bool(f.get("survey_h5_enabled", False)),
                  "collection_download_enabled": bool(f.get("collection_download_enabled", False))},
    }


def render(conf):
    body = json.dumps(conf, indent=2)
    return ("// AUTO-GENERATED from portal.config.yaml by tools/gen_config.py — do not edit by hand.\n"
            "// This is the browser-side reflection of the portal configuration (branding, version, analytics).\n"
            "// To change branding/version/deployment, edit portal.config.yaml and regenerate this file.\n"
            "window.AUSMT_CONFIG = " + body + ";\n")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cfg = _load_yaml(YAML.read_text(encoding="utf-8"))
    conf = build_config(cfg or {})
    out = render(conf)
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.strip() != out.strip():
            print("config.js is out of date — run: python3 tools/gen_config.py", file=sys.stderr)
            return 1
        print("config.js is in sync with portal.config.yaml")
        return 0
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT} (AusMT v{conf['version']} · {conf['schema']} {conf['schema_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
