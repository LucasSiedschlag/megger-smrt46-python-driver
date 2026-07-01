from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Smrt46CommandResult:
    command: str
    response: str
    started_at: datetime
    completed_at: datetime
    duration_s: float

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["completed_at"] = self.completed_at.isoformat()
        return data


@dataclass
class RawAsciiResponse:
    command: str
    raw: str
    notes: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46CurrentChannelConfig:
    channel: int
    amplitude: float
    phase_deg: float
    frequency_hz: float = 60.0
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46CurrentInjectionRequest:
    currents: List[Smrt46CurrentChannelConfig]
    frequency_hz: float = 60.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "currents": [current.to_dict() for current in self.currents],
            "frequency_hz": self.frequency_hz,
        }


@dataclass
class Smrt46VoltageChannelConfig:
    channel: int
    amplitude: float
    phase_deg: float
    frequency_hz: float = 60.0
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46VoltageInjectionRequest:
    voltages: List[Smrt46VoltageChannelConfig]
    frequency_hz: float = 60.0
    stop_mode: str = "binary_input"
    target_bin: int = 1
    duration_s: Optional[float] = None
    poll_interval_s: float = 0.15
    safety_timeout_s: Optional[float] = 30.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voltages": [voltage.to_dict() for voltage in self.voltages],
            "frequency_hz": self.frequency_hz,
            "stop_mode": self.stop_mode,
            "target_bin": self.target_bin,
            "duration_s": self.duration_s,
            "poll_interval_s": self.poll_interval_s,
            "safety_timeout_s": self.safety_timeout_s,
        }


@dataclass
class Smrt46CurveTestConfig:
    phases: List[str]
    start_current_a: float
    stop_current_a: float
    step_size_a: float
    step_delay_ms: int = 80
    qg_interval: int = 5
    trip_confirm_polls: int = 1
    target_bin: int = 1
    frequency_hz: float = 60.0
    rearm_before_phase: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46MeasuredCurrent:
    channel: int
    enabled: bool
    state_code: int
    source_code: int
    amplitude: float
    deviation: float
    phase_deg: float
    frequency_hz: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46MeasuredVoltage:
    channel: int
    enabled: bool
    state_code: int
    source_code: int
    amplitude: float
    deviation: float
    phase_deg: float
    frequency_hz: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46StatusSnapshot:
    raw: str
    voltages: List[Smrt46MeasuredVoltage]
    currents: List[Smrt46MeasuredCurrent]
    binary_inputs: str
    binary_outputs: str
    event_count: int
    elapsed_time_s: float
    timer_values: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "voltages": [voltage.to_dict() for voltage in self.voltages],
            "currents": [current.to_dict() for current in self.currents],
            "binary_inputs": self.binary_inputs,
            "binary_outputs": self.binary_outputs,
            "event_count": self.event_count,
            "elapsed_time_s": self.elapsed_time_s,
            "timer_values": dict(self.timer_values),
            "metadata": dict(self.metadata),
        }


@dataclass
class Smrt46MaxLimits:
    raw: str
    voltage_limits: List[float]
    current_limits: List[float]
    continuous_current_limits: List[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46GateState:
    raw: str
    mask: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46AlarmSet:
    raw: str
    alarms: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46IpConfig:
    raw: str
    ip_address: str
    mode: Optional[str] = None
    extra_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46VersionComponent:
    name: str
    firmware_version: str
    cpld: Optional[str] = None
    boot: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46VersionInfo:
    raw: str
    components: List[Smrt46VersionComponent]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "components": [component.to_dict() for component in self.components],
        }


@dataclass
class Smrt46CurrentInjectionResult:
    request: Smrt46CurrentInjectionRequest
    command_sequence: List[str]
    initial_snapshot: Smrt46StatusSnapshot
    final_snapshot: Optional[Smrt46StatusSnapshot] = None
    alarms: List[str] = field(default_factory=list)
    observed_peak_currents: Dict[int, float] = field(default_factory=dict)
    trip_detected: bool = False
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "command_sequence": list(self.command_sequence),
            "initial_snapshot": self.initial_snapshot.to_dict(),
            "final_snapshot": (
                None if self.final_snapshot is None else self.final_snapshot.to_dict()
            ),
            "alarms": list(self.alarms),
            "observed_peak_currents": dict(self.observed_peak_currents),
            "trip_detected": self.trip_detected,
            "history": list(self.history),
        }


@dataclass
class Smrt46VoltageInjectionResult:
    request: Smrt46VoltageInjectionRequest
    command_sequence: List[str]
    initial_snapshot: Smrt46StatusSnapshot
    final_snapshot: Optional[Smrt46StatusSnapshot] = None
    alarms: List[str] = field(default_factory=list)
    observed_peak_voltages: Dict[int, float] = field(default_factory=dict)
    stop_reason: str = "unknown"
    trip_detected: bool = False
    history: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "command_sequence": list(self.command_sequence),
            "initial_snapshot": self.initial_snapshot.to_dict(),
            "final_snapshot": (
                None if self.final_snapshot is None else self.final_snapshot.to_dict()
            ),
            "alarms": list(self.alarms),
            "observed_peak_voltages": dict(self.observed_peak_voltages),
            "stop_reason": self.stop_reason,
            "trip_detected": self.trip_detected,
            "history": list(self.history),
            "notes": list(self.notes),
        }


@dataclass
class Smrt46CurvePhaseResult:
    phase: str
    channel: int
    stop_reason: str
    final_amplitude_a: float
    raw_final_qryall: Optional[str] = None
    alarms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Smrt46CurveTestResult:
    config: Smrt46CurveTestConfig
    phases: List[Smrt46CurvePhaseResult]
    command_sequence: List[str]
    aborted: bool
    success: bool
    final_state: str
    last_raw_response: str
    raw_payloads: List[str] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "phases": [phase.to_dict() for phase in self.phases],
            "command_sequence": list(self.command_sequence),
            "aborted": self.aborted,
            "success": self.success,
            "final_state": self.final_state,
            "last_raw_response": self.last_raw_response,
            "raw_payloads": list(self.raw_payloads),
            "history": list(self.history),
            "notes": list(self.notes),
        }
