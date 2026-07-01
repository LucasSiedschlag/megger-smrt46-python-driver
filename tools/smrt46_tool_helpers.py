from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from smrt46_client import Smrt46Client
from smrt46_client.exceptions import (
    Smrt46ConnectionError,
    Smrt46Error,
    Smrt46ProtocolError,
    Smrt46SessionBusyError,
    Smrt46TimeoutError,
)
from smrt46_client.models import (
    Smrt46CurrentChannelConfig,
    Smrt46CurrentInjectionRequest,
    Smrt46CurrentInjectionResult,
    Smrt46CurveTestConfig,
    Smrt46StatusSnapshot,
    Smrt46VoltageChannelConfig,
    Smrt46VoltageInjectionRequest,
    Smrt46VoltageInjectionResult,
)


class Smrt46ToolError(Exception):
    """Tool-facing SMRT46 error with stable CLI text."""


@dataclass
class ToolResponse:
    equip: str
    success: bool
    result: Dict[str, Any]
    operation: Optional[str] = None
    test_name: Optional[str] = None
    final_state: Optional[str] = None
    raw: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None
    warnings: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "equip": self.equip,
            "success": self.success,
            "result": self.result,
        }
        if self.operation is not None:
            payload["operation"] = self.operation
        if self.test_name is not None:
            payload["test_name"] = self.test_name
        if self.final_state is not None:
            payload["final_state"] = self.final_state
        if self.raw is not None:
            payload["raw"] = self.raw
        payload["history"] = [] if self.history is None else list(self.history)
        payload["warnings"] = [] if self.warnings is None else list(self.warnings)
        payload["metadata"] = {} if self.metadata is None else dict(self.metadata)
        return payload


@contextmanager
def open_client(settings: Dict[str, Any], logger: Any) -> Iterator[Smrt46Client]:
    try:
        with Smrt46Client(
            settings["host"],
            settings["port"],
            connect_timeout=settings["connect_timeout"],
            command_timeout=settings["timeout"],
            read_idle_gap=settings["poll_interval"],
            logger=logger,
            session_log_path=settings.get("session_log"),
        ) as client:
            yield client
    except (
        Smrt46SessionBusyError,
        Smrt46ConnectionError,
        Smrt46TimeoutError,
        Smrt46ProtocolError,
        Smrt46Error,
    ) as exc:
        raise Smrt46ToolError(str(exc)) from exc


def build_current_request(
    currents: List[Dict[str, Any]],
    *,
    frequency_hz: float,
) -> Smrt46CurrentInjectionRequest:
    return Smrt46CurrentInjectionRequest(
        currents=[
            Smrt46CurrentChannelConfig(
                channel=int(current["channel"]),
                amplitude=float(current["amplitude"]),
                phase_deg=float(current["phase_deg"]),
                frequency_hz=float(current.get("frequency_hz", frequency_hz)),
                enabled=bool(current.get("enabled", True)),
            )
            for current in currents
        ],
        frequency_hz=frequency_hz,
    )


def build_voltage_request(parameters: Dict[str, Any]) -> Smrt46VoltageInjectionRequest:
    request_parameters = dict(parameters)
    frequency_hz = float(request_parameters.pop("frequency_hz", 60.0))
    voltages = request_parameters.pop("voltages")
    duration_s = request_parameters.pop("duration_s", None)
    safety_timeout_s = request_parameters.pop("safety_timeout_s", None)
    request = Smrt46VoltageInjectionRequest(
        voltages=[
            Smrt46VoltageChannelConfig(
                channel=int(voltage["channel"]),
                amplitude=float(voltage["amplitude"]),
                phase_deg=float(voltage["phase_deg"]),
                frequency_hz=float(voltage.get("frequency_hz", frequency_hz)),
                enabled=bool(voltage.get("enabled", True)),
            )
            for voltage in voltages
        ],
        frequency_hz=frequency_hz,
        stop_mode=str(request_parameters.pop("stop_mode", "binary_input")),
        target_bin=int(request_parameters.pop("target_bin", 1)),
        duration_s=None if duration_s is None else float(duration_s),
        poll_interval_s=float(request_parameters.pop("poll_interval_s", 0.15)),
        safety_timeout_s=None if safety_timeout_s is None else float(safety_timeout_s),
    )
    if request_parameters:
        raise ValueError(
            "SMRT46 voltage tests do not support extra top-level parameters: "
            f"{sorted(request_parameters)!r}."
        )
    return request


def build_curve_config(parameters: Dict[str, Any]) -> Smrt46CurveTestConfig:
    request_parameters = dict(parameters)
    config = Smrt46CurveTestConfig(
        phases=[str(phase) for phase in request_parameters.pop("phases")],
        start_current_a=float(request_parameters.pop("start_current_a")),
        stop_current_a=float(request_parameters.pop("stop_current_a")),
        step_size_a=float(request_parameters.pop("step_size_a")),
        step_delay_ms=int(request_parameters.pop("step_delay_ms", 80)),
        qg_interval=int(request_parameters.pop("qg_interval", 5)),
        trip_confirm_polls=int(request_parameters.pop("trip_confirm_polls", 1)),
        target_bin=int(request_parameters.pop("target_bin", 1)),
        frequency_hz=float(request_parameters.pop("frequency_hz", 60.0)),
        rearm_before_phase=bool(request_parameters.pop("rearm_before_phase", True)),
    )
    if request_parameters:
        raise ValueError(
            "SMRT46 curve tests do not support extra top-level parameters: "
            f"{sorted(request_parameters)!r}."
        )
    return config


def connection_probe(
    settings: Dict[str, Any],
    *,
    logger: Any,
) -> ToolResponse:
    with open_client(settings, logger) as client:
        gate_state = client.query_gate_state()
        version = client.qver()
        ip = client.qip()
        status = client.query_all()
        whoami = client.raw("WHOAMI;")
    warnings: List[str] = []
    warnings.extend(whoami.notes or [])
    return ToolResponse(
        equip="smrt46",
        operation="connection_probe",
        success=True,
        result={
            "gate_state": gate_state.to_dict(),
            "version": version.to_dict(),
            "ip": ip.to_dict(),
            "status": status.to_dict(),
            "whoami": whoami.to_dict(),
        },
        raw=status.raw,
        warnings=warnings,
    )


def configure_current_outputs(
    currents: List[Dict[str, Any]],
    *,
    frequency_hz: float,
    settings: Dict[str, Any],
    logger: Any,
) -> ToolResponse:
    request = build_current_request(currents, frequency_hz=frequency_hz)
    with open_client(settings, logger) as client:
        results = client.configure_current_outputs(request)
    return ToolResponse(
        equip="smrt46",
        operation="configure_current_outputs",
        success=True,
        result={
            "request": request.to_dict(),
            "command_results": [result.to_dict() for result in results],
            "commands": [result.command for result in results],
        },
        raw=results[-1].response if results else None,
    )


def run_current_injection(
    currents: List[Dict[str, Any]],
    *,
    frequency_hz: float,
    poll_count: int,
    test_name: str,
    settings: Dict[str, Any],
    logger: Any,
    on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None,
) -> ToolResponse:
    request = build_current_request(currents, frequency_hz=frequency_hz)
    with open_client(settings, logger) as client:
        result = client.run_current_injection(
            request,
            poll_count=poll_count,
            on_snapshot=on_snapshot,
        )
    injection_ok, injection_warnings = validate_current_measurement(result)
    has_alarms = bool(result.alarms)
    success = injection_ok and not has_alarms
    final_state = "INJECTION_COMPLETE"
    if has_alarms:
        final_state = "ALARM"
    elif not injection_ok:
        final_state = "NO_INJECTION"
    warnings = list(result.alarms)
    if not has_alarms:
        warnings.extend(injection_warnings)
    last_raw_response = (
        result.final_snapshot.raw
        if result.final_snapshot is not None
        else result.initial_snapshot.raw
    )
    payload = {
        "success": success,
        "final_state": final_state,
        "last_raw_response": last_raw_response,
        "history": list(result.history),
        "notes": list(warnings),
        "request": result.request.to_dict(),
        "command_sequence": result.command_sequence,
        "initial_snapshot": result.initial_snapshot.to_dict(),
        "final_snapshot": (
            None if result.final_snapshot is None else result.final_snapshot.to_dict()
        ),
        "alarms": result.alarms,
        "observed_peak_currents": dict(result.observed_peak_currents),
        "trip_detected": result.trip_detected,
        "trip_channels": extract_trip_channels(result.alarms),
    }
    return ToolResponse(
        equip="smrt46",
        test_name=test_name,
        success=success,
        final_state=final_state,
        result=payload,
        raw=last_raw_response,
        history=list(result.history),
        warnings=warnings,
    )


def run_voltage_test(
    parameters: Dict[str, Any],
    *,
    test_name: str,
    settings: Dict[str, Any],
    logger: Any,
    on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None,
) -> ToolResponse:
    request = build_voltage_request(parameters)
    with open_client(settings, logger) as client:
        result = client.run_voltage_injection(request, on_snapshot=on_snapshot)
    injection_ok, injection_warnings = validate_voltage_measurement(result)
    has_alarms = bool(result.alarms)
    success = (
        injection_ok
        and not has_alarms
        and result.stop_reason in {"binary_input_closed", "duration_elapsed", "manual_stop"}
    )
    final_state = "VOLTAGE_COMPLETE"
    if has_alarms:
        final_state = "ALARM"
    elif result.stop_reason == "timeout":
        final_state = "TIMEOUT"
    elif result.stop_reason == "voltage_output_lost":
        final_state = "OUTPUT_LOST"
    elif not injection_ok:
        final_state = "NO_VOLTAGE"
    elif result.stop_reason == "binary_input_closed":
        final_state = "TRIPPED"
    elif result.stop_reason == "duration_elapsed":
        final_state = "DURATION_COMPLETE"
    elif result.stop_reason == "manual_stop":
        final_state = "MANUAL_STOP"
    warnings = list(result.alarms)
    warnings.extend(result.notes)
    if not has_alarms:
        warnings.extend(injection_warnings)
    last_raw_response = (
        result.final_snapshot.raw
        if result.final_snapshot is not None
        else result.initial_snapshot.raw
    )
    payload = {
        "success": success,
        "final_state": final_state,
        "last_raw_response": last_raw_response,
        "history": list(result.history),
        "notes": list(warnings),
        "request": result.request.to_dict(),
        "command_sequence": result.command_sequence,
        "initial_snapshot": result.initial_snapshot.to_dict(),
        "final_snapshot": (
            None if result.final_snapshot is None else result.final_snapshot.to_dict()
        ),
        "alarms": result.alarms,
        "observed_peak_voltages": dict(result.observed_peak_voltages),
        "stop_reason": result.stop_reason,
        "trip_detected": result.trip_detected,
    }
    return ToolResponse(
        equip="smrt46",
        test_name=test_name,
        success=success,
        final_state=final_state,
        result=payload,
        raw=last_raw_response,
        history=list(result.history),
        warnings=warnings,
    )


def run_curve_test(
    parameters: Dict[str, Any],
    *,
    test_name: str,
    settings: Dict[str, Any],
    logger: Any,
    on_sample: Optional[Callable[[int, float], None]] = None,
    on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None,
) -> ToolResponse:
    config = build_curve_config(parameters)
    with open_client(settings, logger) as client:
        result = client.run_curve_injection(
            config,
            on_step=on_sample,
            on_snapshot=on_snapshot,
        )
    payload = result.to_dict()
    payload["test_name"] = test_name
    return ToolResponse(
        equip="smrt46",
        test_name=test_name,
        success=result.success,
        final_state=result.final_state,
        result=payload,
        raw=result.last_raw_response or None,
        history=list(result.history),
        warnings=list(result.notes),
    )


def validate_current_measurement(
    result: Smrt46CurrentInjectionResult,
) -> Tuple[bool, List[str]]:
    if result.final_snapshot is None and not result.observed_peak_currents:
        return False, ["Current injection did not produce a final QRYALL snapshot."]
    warnings: List[str] = []
    measured_by_channel: Dict[int, float] = dict(result.observed_peak_currents)
    if result.final_snapshot is not None:
        for current in result.final_snapshot.currents:
            previous = measured_by_channel.get(current.channel, 0.0)
            if current.amplitude > previous:
                measured_by_channel[current.channel] = current.amplitude
    for requested in result.request.currents:
        if (not requested.enabled) or requested.amplitude <= 0.0:
            continue
        measured = measured_by_channel.get(requested.channel)
        if measured is None:
            warnings.append(
                f"Current channel C{requested.channel} was requested but is "
                "missing in final snapshot."
            )
            continue
        minimum_expected = max(0.05, requested.amplitude * 0.1)
        if measured < minimum_expected:
            warnings.append(
                "Current injection not observed on C{channel}: requested={requested:.4f}A, "
                "measured={measured:.4f}A.".format(
                    channel=requested.channel,
                    requested=requested.amplitude,
                    measured=measured,
                )
            )
    return not warnings, warnings


def validate_voltage_measurement(
    result: Smrt46VoltageInjectionResult,
) -> Tuple[bool, List[str]]:
    if result.final_snapshot is None and not result.observed_peak_voltages:
        return False, ["Voltage injection did not produce a final QRYALL snapshot."]
    warnings: List[str] = []
    measured_by_channel: Dict[int, float] = dict(result.observed_peak_voltages)
    if result.final_snapshot is not None:
        for voltage in result.final_snapshot.voltages:
            previous = measured_by_channel.get(voltage.channel, 0.0)
            if voltage.amplitude > previous:
                measured_by_channel[voltage.channel] = voltage.amplitude
    for requested in result.request.voltages:
        if (not requested.enabled) or requested.amplitude <= 0.0:
            continue
        measured = measured_by_channel.get(requested.channel)
        if measured is None:
            warnings.append(
                f"Voltage channel V{requested.channel} was requested but is "
                "missing in final snapshot."
            )
            continue
        minimum_expected = max(0.5, requested.amplitude * 0.1)
        if measured < minimum_expected:
            warnings.append(
                "Voltage injection not observed on V{channel}: requested={requested:.4f}V, "
                "measured={measured:.4f}V.".format(
                    channel=requested.channel,
                    requested=requested.amplitude,
                    measured=measured,
                )
            )
    return not warnings, warnings


def extract_trip_channels(alarms: List[str]) -> List[str]:
    channels: List[str] = []
    for alarm in alarms:
        matches = re.findall(r"\bC([123])\b", alarm)
        for channel in matches:
            label = f"C{channel}"
            if label not in channels:
                channels.append(label)
    return channels
