from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smrt46_client.logging_utils import setup_logging
from smrt46_client.models import Smrt46StatusSnapshot

from tools.smrt46_probe_common import add_common_arguments, resolve_probe_settings
from tools.smrt46_tool_helpers import Smrt46ToolError, run_curve_test


def build_parser() -> argparse.ArgumentParser:
    parser = add_common_arguments(
        argparse.ArgumentParser(description="Run an SMRT46 curve test on a single phase.")
    )
    parser.add_argument("--phase", required=True, choices=["A", "B", "C"])
    ramp_group = parser.add_argument_group("ramp definition")
    ramp_group.add_argument("--nominal", type=float, default=None, metavar="AMPS")
    ramp_group.add_argument("--start-pct", type=float, default=80.0, metavar="PCT")
    ramp_group.add_argument("--stop-pct", type=float, default=120.0, metavar="PCT")
    ramp_group.add_argument(
        "--start", type=float, default=None, dest="start_current_a", metavar="AMPS"
    )
    ramp_group.add_argument(
        "--stop", type=float, default=None, dest="stop_current_a", metavar="AMPS"
    )
    parser.add_argument("--step", type=float, default=0.1, dest="step_size_a", metavar="AMPS")
    parser.add_argument("--cycles", type=float, default=8.0, metavar="N")
    parser.add_argument("--step-delay-ms", type=int, default=None, metavar="MS")
    parser.add_argument("--qg-interval", type=int, default=5, metavar="N")
    parser.add_argument("--trip-confirm-polls", type=int, default=1, metavar="N")
    parser.add_argument("--frequency", type=float, default=60.0)
    parser.add_argument("--target-bin", type=int, default=1, metavar="N")
    parser.add_argument("--test-name", default="smrt46_curve_test")
    parser.add_argument("--only-current-time", action="store_true")
    return parser


def _resolve_ramp(args: argparse.Namespace):
    if args.nominal is not None and (
        args.start_current_a is not None or args.stop_current_a is not None
    ):
        raise ValueError("--nominal cannot be combined with --start or --stop.")
    if args.nominal is not None:
        nominal = args.nominal
        return (
            round(nominal * args.start_pct / 100.0, 4),
            round(nominal * args.stop_pct / 100.0, 4),
            nominal,
        )
    if args.start_current_a is None or args.stop_current_a is None:
        raise ValueError("Specify either --nominal or both --start and --stop.")
    return args.start_current_a, args.stop_current_a, None


def _resolve_step_delay_ms(args: argparse.Namespace) -> int:
    if args.step_delay_ms is not None:
        return args.step_delay_ms
    return max(1, math.ceil(args.cycles * 1000.0 / args.frequency))


def build_current_time_reporters(
    phase_channel: int, start_time: float
) -> Tuple[Callable[[int, float], None], Callable[[Smrt46StatusSnapshot], None]]:
    last_sent_a: Optional[float] = None

    def _on_step(channel: int, amplitude: float) -> None:
        nonlocal last_sent_a
        if channel == phase_channel:
            last_sent_a = amplitude

    def _on_snapshot(snapshot: Smrt46StatusSnapshot) -> None:
        amplitude_by_channel = {
            measured.channel: measured.amplitude for measured in snapshot.currents
        }
        measured_a = amplitude_by_channel.get(phase_channel)
        send_text = "-" if last_sent_a is None else f"{last_sent_a:.4f}A"
        measured_text = "-" if measured_a is None else f"{measured_a:.4f}A"
        elapsed = time.monotonic() - start_time
        print(
            f"C{phase_channel} send={send_text} | "
            f"C{phase_channel} measured={measured_text} | "
            f"t={elapsed:.3f}s",
            flush=True,
        )

    return _on_step, _on_snapshot


def _format_stop_reason(stop_reason: str, amplitude: float) -> str:
    if stop_reason == "din_closed":
        return f"TRIP at {amplitude:.4f} A  [binary input]"
    if stop_reason == "phase_trip":
        return f"TRIP at {amplitude:.4f} A  [recloser signal]"
    if stop_reason == "ramp_exhausted":
        return f"NO TRIP — ramp exhausted at {amplitude:.4f} A"
    return f"ALARM — stopped at {amplitude:.4f} A"


def main() -> int:
    args = build_parser().parse_args()
    try:
        start_a, stop_a, nominal_a = _resolve_ramp(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    settings = resolve_probe_settings(args)
    logger = setup_logging(
        verbose=args.verbose and not args.only_current_time, log_file=settings.get("log_file")
    )
    step_delay_ms = _resolve_step_delay_ms(args)
    parameters = {
        "phases": [args.phase],
        "start_current_a": start_a,
        "stop_current_a": stop_a,
        "step_size_a": args.step_size_a,
        "step_delay_ms": step_delay_ms,
        "qg_interval": args.qg_interval,
        "trip_confirm_polls": args.trip_confirm_polls,
        "target_bin": args.target_bin,
        "frequency_hz": args.frequency,
        "rearm_before_phase": True,
    }
    nominal_label = f"  nominal={nominal_a:.3f}A" if nominal_a is not None else ""
    print(
        f"Curve test — phase {args.phase}  "
        f"{start_a:.3f}A → {stop_a:.3f}A  "
        f"step={args.step_size_a:.3f}A  "
        f"freq={args.frequency}Hz  "
        f"dwell={step_delay_ms}ms{nominal_label}",
        flush=True,
    )
    on_sample: Optional[Callable[[int, float], None]] = None
    on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None
    if args.only_current_time:
        phase_channel_map = {"A": 1, "B": 2, "C": 3}
        parameters["qg_interval"] = 1
        on_sample, on_snapshot = build_current_time_reporters(
            phase_channel_map[args.phase], time.monotonic()
        )
    try:
        response = run_curve_test(
            parameters,
            test_name=args.test_name,
            settings=settings,
            logger=logger,
            on_sample=on_sample,
            on_snapshot=on_snapshot,
        )
    except (Smrt46ToolError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operation": "smrt46_curve_test",
                    "target": settings["target"],
                    "error": str(exc),
                },
                indent=2,
            )
        )
        return 1
    phase_results = response.result.get("phases", [])
    for pr in phase_results:
        phase = pr.get("phase", "?")
        stop_reason = pr.get("stop_reason", "?")
        amplitude = float(pr.get("final_amplitude_a", 0.0))
        alarms = pr.get("alarms", [])
        print(f"\nPhase {phase}: {_format_stop_reason(stop_reason, amplitude)}")
        for alarm in alarms:
            print(f"  ! {alarm}")
    print()
    if not args.only_current_time:
        print(
            json.dumps(
                {
                    "ok": response.success,
                    "operation": "smrt46_curve_test",
                    "target": settings["target"],
                    "config_file": settings["config_file"],
                    "host": settings["host"],
                    "port": settings["port"],
                    "phase": args.phase,
                    "nominal_a": nominal_a,
                    "start_current_a": start_a,
                    "stop_current_a": stop_a,
                    "step_size_a": args.step_size_a,
                    "frequency_hz": args.frequency,
                    "result": response.result,
                },
                indent=2,
            )
        )
    return 0 if response.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
