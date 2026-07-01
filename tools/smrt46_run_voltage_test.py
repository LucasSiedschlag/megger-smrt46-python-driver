from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smrt46_client.logging_utils import setup_logging
from smrt46_client.models import Smrt46StatusSnapshot

from tools.smrt46_probe_common import add_common_arguments, resolve_probe_settings
from tools.smrt46_tool_helpers import Smrt46ToolError, run_voltage_test


def build_parser() -> argparse.ArgumentParser:
    parser = add_common_arguments(
        argparse.ArgumentParser(description="Run a direct SMRT46 voltage injection.")
    )
    parser.add_argument(
        "--voltage",
        dest="voltages",
        action="append",
        required=True,
        metavar="CHANNEL:AMPLITUDE:PHASE",
    )
    parser.add_argument(
        "--frequency", type=float, default=60.0, help="Injection frequency in Hz. Default: 60.0"
    )
    parser.add_argument(
        "--stop-mode", choices=["binary_input", "duration", "manual"], default="binary_input"
    )
    parser.add_argument("--target-bin", type=int, default=1)
    parser.add_argument("--duration", type=float, default=None, dest="duration_s")
    parser.add_argument("--runtime-poll-interval", type=float, default=0.15, dest="poll_interval_s")
    parser.add_argument("--safety-timeout", type=float, default=30.0, dest="safety_timeout_s")
    parser.add_argument("--test-name", default="smrt46_voltage_test")
    parser.add_argument("--json", action="store_true", help="Print the full JSON result.")
    parser.add_argument(
        "--only-voltage-degree",
        action="store_true",
        help="Print compact voltage, phase degree, and elapsed time.",
    )
    parser.add_argument("--only-voltage-time", action="store_true", help=argparse.SUPPRESS)
    return parser


def parse_voltage_spec(spec: str) -> Dict[str, Any]:
    parts = [part.strip() for part in spec.split(":")]
    if len(parts) != 3:
        raise ValueError(
            "Voltage spec must follow CHANNEL:AMPLITUDE:PHASE, for example 2:50.0:120."
        )
    channel_text, amplitude_text, phase_text = parts
    return {
        "channel": int(channel_text),
        "amplitude": float(amplitude_text),
        "phase_deg": float(phase_text),
    }


def build_voltage_payload(specs: list[str]) -> list[Dict[str, Any]]:
    voltages = [parse_voltage_spec(spec) for spec in specs]
    voltages.sort(key=lambda item: int(item["channel"]))
    return voltages


def build_voltage_degree_reporter(
    voltages: list[Dict[str, Any]], start_time: float
) -> Callable[[Smrt46StatusSnapshot], None]:
    selected_channels = [int(voltage["channel"]) for voltage in voltages]
    last_emit_at = 0.0

    def _report(snapshot: Smrt46StatusSnapshot) -> None:
        nonlocal last_emit_at
        now = time.monotonic()
        if now - last_emit_at < 0.15:
            return
        amplitude_by_channel = {
            measured.channel: measured.amplitude for measured in snapshot.voltages
        }
        phase_by_channel = {measured.channel: measured.phase_deg for measured in snapshot.voltages}
        values: list[str] = []
        for channel in selected_channels:
            amplitude = amplitude_by_channel.get(channel)
            phase = phase_by_channel.get(channel)
            amplitude_text = "-" if amplitude is None else f"{amplitude:.4f}V"
            phase_text = "-" if phase is None else f"{phase:.3f}deg"
            values.append(f"V{channel}={amplitude_text} angle={phase_text}")
        elapsed_s = time.monotonic() - start_time
        print(f"{' '.join(values)} t={elapsed_s:.4f}s", flush=True)
        last_emit_at = now

    return _report


def print_compact_result(result: Any) -> None:
    payload = result.to_dict()
    result_payload = payload["result"]
    request = result_payload["request"]
    final_snapshot = result_payload.get("final_snapshot") or {}
    measured_voltages = {
        int(voltage["channel"]): voltage for voltage in final_snapshot.get("voltages", [])
    }
    peak_voltages = {
        int(channel): amplitude
        for channel, amplitude in result_payload.get("observed_peak_voltages", {}).items()
    }
    values: list[str] = []
    for voltage in request["voltages"]:
        channel = int(voltage["channel"])
        measured = measured_voltages.get(channel, {})
        peak = peak_voltages.get(channel)
        measured_amplitude = measured.get("amplitude")
        measured_phase = measured.get("phase_deg")
        measured_text = "-" if measured_amplitude is None else f"{measured_amplitude:.4f}V"
        peak_text = "-" if peak is None else f"{peak:.4f}V"
        phase_text = "-" if measured_phase is None else f"{measured_phase:.3f}deg"
        values.append(f"V{channel}={measured_text} peak={peak_text} angle={phase_text}")
    print(
        "ok={ok} state={state} stop={stop} trip={trip} {values}".format(
            ok=str(payload["success"]).lower(),
            state=payload["final_state"],
            stop=result_payload["stop_reason"],
            trip=str(result_payload["trip_detected"]).lower(),
            values=" ".join(values),
        ),
        flush=True,
    )
    messages = result_payload.get("notes") or payload.get("warnings") or []
    for message in messages:
        print(f"message={message}", flush=True)


def main() -> int:
    args = build_parser().parse_args()
    settings = resolve_probe_settings(args)
    voltages = build_voltage_payload(args.voltages)
    compact_output = not args.json or args.only_voltage_time or args.only_voltage_degree
    logger = setup_logging(verbose=args.verbose, log_file=settings.get("log_file"))
    on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None
    if compact_output:
        on_snapshot = build_voltage_degree_reporter(voltages, time.monotonic())
    try:
        result = run_voltage_test(
            {
                "voltages": voltages,
                "frequency_hz": args.frequency,
                "stop_mode": args.stop_mode,
                "target_bin": args.target_bin,
                "duration_s": args.duration_s,
                "poll_interval_s": args.poll_interval_s,
                "safety_timeout_s": args.safety_timeout_s,
            },
            test_name=args.test_name,
            settings=settings,
            logger=logger,
            on_snapshot=on_snapshot,
        )
    except (Smrt46ToolError, ValueError) as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "operation": "smrt46_voltage_test",
                        "target": settings["target"],
                        "error": str(exc),
                    },
                    indent=2,
                )
            )
        else:
            print(f"ok=false operation=smrt46_voltage_test error={exc}", flush=True)
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "operation": "smrt46_voltage_test",
                    "target": settings["target"],
                    "config_file": settings["config_file"],
                    "host": settings["host"],
                    "port": settings["port"],
                    "result": result.to_dict(),
                },
                indent=2,
            )
        )
    else:
        print_compact_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
