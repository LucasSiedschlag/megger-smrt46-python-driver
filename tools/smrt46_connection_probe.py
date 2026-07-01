from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.smrt46_probe_common import add_common_arguments, resolve_probe_settings
from tools.smrt46_tool_helpers import Smrt46ToolError, connection_probe


def main() -> int:
    parser = add_common_arguments(
        argparse.ArgumentParser(
            description=(
                "SMRT46 Ethernet connection probe. "
                "Uses config/smrt46_hosts.ini and [smrt46.default] unless overridden."
            )
        )
    )
    args = parser.parse_args()
    settings = resolve_probe_settings(args)
    try:
        result = connection_probe(settings, logger=settings["logger"])
    except Smrt46ToolError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operation": "connection_probe",
                    "target": settings["target"],
                    "error": str(exc),
                },
                indent=2,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "operation": "connection_probe",
                "target": settings["target"],
                "config_file": settings["config_file"],
                "host": settings["host"],
                "port": settings["port"],
                "discovery_udp_port": settings["discovery_udp_port"],
                "result": result.to_dict(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
