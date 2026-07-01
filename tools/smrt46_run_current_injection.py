from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smrt46_client.logging_utils import setup_logging
from smrt46_client.models import Smrt46StatusSnapshot

from tools.smrt46_probe_common import add_common_arguments, resolve_probe_settings
from tools.smrt46_tool_helpers import Smrt46ToolError, run_current_injection


def build_parser() -> argparse.ArgumentParser:
    parser = add_common_arguments(
        argparse.ArgumentParser(
            description=(
                "Run a direct SMRT46 current injection. "
                "Uses config/smrt46_hosts.ini and [smrt46.default] unless overridden."
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
    parser.add_argument(
        "--poll-count",
        type=int,
        default=1,
        help="Minimum number of runtime QRYALL polls before trip evaluation starts. Default: 1",
    )
    parser.add_argument(
        "--test-name", default="smrt46_current_injection", help="Name reported in the response."
    )
    parser.add_argument(
        "--only-current-time",
        action="store_true",
        help="Print compact current and elapsed-time lines during runtime polling.",
    )
    return parser


def parse_current_spec(spec: str) -> Dict[str, Any]:
    parts = [part.strip() for part in spec.split(":")]
    if len(parts) != 3:
        raise ValueError("Current spec must follow CHANNEL:AMPLITUDE:PHASE, for example 1:3.0:0.")
    channel_text, amplitude_text, phase_text = parts
    return {
        "channel": int(channel_text),
        "amplitude": float(amplitude_text),
        "phase_deg": float(phase_text),
    }


def build_current_payload(specs: List[str]) -> List[Dict[str, Any]]:
    currents = [parse_current_spec(spec) for spec in specs]
    currents.sort(key=lambda item: int(item["channel"]))
    return currents


def build_current_time_reporter(
    currents: List[Dict[str, Any]],
) -> Callable[[Smrt46StatusSnapshot], None]:
    selected_channels = [int(current["channel"]) for current in currents]
    last_emit_at = 0.0

    def _report(snapshot: Smrt46StatusSnapshot) -> None:
        nonlocal last_emit_at
        now = time.monotonic()
        if now - last_emit_at < 0.15:
            return
        amplitude_by_channel = {
            measured.channel: measured.amplitude for measured in snapshot.currents
        }
        values: List[str] = []
        for channel in selected_channels:
            amplitude = amplitude_by_channel.get(channel)
            amplitude_text = "-" if amplitude is None else f"{amplitude:.4f}A"
            values.append(f"C{channel}={amplitude_text}")
        print(f"{' '.join(values)} t={snapshot.elapsed_time_s:.4f}s", flush=True)
        last_emit_at = now

    return _report


def main() -> int:
    args = build_parser().parse_args()
    settings = resolve_probe_settings(args)
    currents = build_current_payload(args.currents)
    logger = setup_logging(
        verbose=args.verbose and not args.only_current_time, log_file=settings.get("log_file")
    )
    on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None
    if args.only_current_time:
        on_snapshot = build_current_time_reporter(currents)
    try:
        result = run_current_injection(
            currents,
            frequency_hz=args.frequency,
            poll_count=args.poll_count,
            test_name=args.test_name,
            settings=settings,
            logger=logger,
            on_snapshot=on_snapshot,
        )
    except (Smrt46ToolError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operation": "smrt46_current_injection",
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
                "operation": "smrt46_current_injection",
                "target": settings["target"],
                "config_file": settings["config_file"],
                "host": settings["host"],
                "port": settings["port"],
                "frequency_hz": args.frequency,
                "poll_count": args.poll_count,
                "currents": currents,
                "result": result.to_dict(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
