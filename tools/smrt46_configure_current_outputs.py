from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smrt46_client.logging_utils import setup_logging

from tools.smrt46_probe_common import add_common_arguments, resolve_probe_settings
from tools.smrt46_run_current_injection import build_current_payload
from tools.smrt46_tool_helpers import Smrt46ToolError, configure_current_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = add_common_arguments(
        argparse.ArgumentParser(
            description=(
                "Configure and arm SMRT46 current outputs without running post-injection polling."
            )
        )
    )
    parser.add_argument(
        "--current",
        dest="currents",
        action="append",
        required=True,
        metavar="CHANNEL:AMPLITUDE:PHASE",
    )
    parser.add_argument(
        "--frequency", type=float, default=60.0, help="Injection frequency in Hz. Default: 60.0"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = resolve_probe_settings(args)
    currents = build_current_payload(args.currents)
    logger = setup_logging(verbose=args.verbose, log_file=settings.get("log_file"))
    try:
        result = configure_current_outputs(
            currents, frequency_hz=args.frequency, settings=settings, logger=logger
        )
    except (Smrt46ToolError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operation": "smrt46_configure_current_outputs",
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
                "operation": "smrt46_configure_current_outputs",
                "target": settings["target"],
                "config_file": settings["config_file"],
                "host": settings["host"],
                "port": settings["port"],
                "frequency_hz": args.frequency,
                "currents": currents,
                "result": result.to_dict(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
