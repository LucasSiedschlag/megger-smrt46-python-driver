from __future__ import annotations

import logging
import socket
import time
from contextlib import suppress
from datetime import datetime
from typing import Any, Callable, Optional

from .exceptions import (
    Smrt46ConnectionError,
    Smrt46Error,
    Smrt46ProtocolError,
    Smrt46SessionBusyError,
    Smrt46TimeoutError,
)
from .models import (
    RawAsciiResponse,
    Smrt46CommandResult,
    Smrt46CurrentInjectionRequest,
    Smrt46CurrentInjectionResult,
    Smrt46CurvePhaseResult,
    Smrt46CurveTestConfig,
    Smrt46CurveTestResult,
    Smrt46GateState,
    Smrt46IpConfig,
    Smrt46MaxLimits,
    Smrt46StatusSnapshot,
    Smrt46VersionInfo,
    Smrt46VoltageInjectionRequest,
    Smrt46VoltageInjectionResult,
)
from .parser import (
    clean_response,
    is_binary_input_closed,
    parse_alarm_response,
    parse_qg_response,
    parse_qip_response,
    parse_qryall_response,
    parse_qrymax_response,
    parse_qver_response,
)
from .protocol import (
    DEFAULT_SMRT46_CHUNK_SIZE,
    DEFAULT_SMRT46_COMMAND_TIMEOUT,
    DEFAULT_SMRT46_CONNECT_TIMEOUT,
    DEFAULT_SMRT46_IDLE_GAP,
    DEFAULT_SMRT46_PORT,
    SMRT46_DEFAULT_CURRENT_PHASES,
    SMRT46_DEFAULT_VOLTAGE_OUTPUT_PHASES,
    SMRT46_PHASE_CHANNEL_MAP,
    build_current_bootstrap_sequence,
    build_current_cleanup_sequence,
    build_current_injection_sequence,
    build_curve_amplitude_step,
    build_curve_channel_init_command,
    build_curve_phase_init_command,
    build_curve_timer_setup,
    build_hsu_command,
    build_master_output_off_command,
    build_open_circuit_alarm_command,
    build_qcfg_command,
    build_qg_command,
    build_qip_command,
    build_qry_command,
    build_qrymax_command,
    build_qver_command,
    build_reconfigure_command,
    build_reset_command,
    build_simulated_trip_command,
    build_su_command,
    build_syssetf_command,
    build_trip_arm_setup_command,
    build_voltage_injection_sequence,
    normalize_command,
)


class Smrt46Client:
    """SMRT46 TCP client based on validated PowerDB-compatible command flows.

    The current and curve workflows are bench validated. Some administrative
    commands still intentionally return raw payloads until a typed model is
    needed by client code.
    """

    POST_RESET_SETTLE_DELAY_S = 0.2
    PHASE_CURRENT_COLLAPSE_RATIO = 0.2
    PHASE_CURRENT_COLLAPSE_MIN_A = 0.2
    VOLTAGE_COLLAPSE_RATIO = 0.1
    VOLTAGE_COLLAPSE_MIN_V = 0.5
    DISCONNECT_SETTLE_DELAY_S = 0.2

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_SMRT46_PORT,
        *,
        connect_timeout: float = DEFAULT_SMRT46_CONNECT_TIMEOUT,
        command_timeout: float = DEFAULT_SMRT46_COMMAND_TIMEOUT,
        read_idle_gap: float = DEFAULT_SMRT46_IDLE_GAP,
        logger: Optional[logging.Logger] = None,
        session_log_path: Optional[str] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.read_idle_gap = read_idle_gap
        self.logger = logger or logging.getLogger("smrt46")
        self.session_log_path = session_log_path
        self._sock: Optional[socket.socket] = None
        self._rx_buffer = ""

    def connect(self) -> None:
        if self._sock is not None:
            return
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
            sock.settimeout(min(self.command_timeout, 0.25))
        except ConnectionRefusedError as exc:
            raise Smrt46SessionBusyError(
                "SMRT46 refused the TCP connection. Another client session may already be active. "
                "Close the other client or reset the SMRT46 session before retrying."
            ) from exc
        except OSError as exc:
            raise Smrt46ConnectionError(
                f"Could not connect to SMRT46 at {self.host}:{self.port}: {exc}"
            ) from exc
        self._sock = sock
        self.logger.info("Connected to %s:%s", self.host, self.port)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            self._terminate_socket(sock)
        except (Smrt46Error, OSError) as exc:
            self.logger.debug("SMRT46 socket pre-close termination skipped: %s", exc)
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            sock.close()
        self.logger.info("Disconnected from %s:%s", self.host, self.port)

    def __enter__(self) -> "Smrt46Client":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def send_command(
        self,
        command: str,
        *,
        expect_response: bool = True,
        timeout: Optional[float] = None,
        expected_pattern: Optional[str] = None,
    ) -> Smrt46CommandResult:
        self._ensure_connected()
        assert self._sock is not None
        normalized = normalize_command(command)
        started = datetime.now()
        started_monotonic = time.monotonic()
        try:
            self._sock.sendall(normalized.encode("ascii"))
        except OSError as exc:
            self.close()
            if self._is_session_busy_transport_error(exc):
                raise Smrt46SessionBusyError(
                    "SMRT46 closed or reset the TCP connection while sending a command "
                    f"({normalized!r}). Another client session may already be active. "
                    "Close the other client or reset the SMRT46 session before retrying."
                ) from exc
            raise Smrt46ConnectionError(f"Failed to send command {normalized!r}: {exc}") from exc
        self._log_traffic("TX", normalized.rstrip())

        response = ""
        if expect_response:
            response = self._read_response(timeout=timeout or self.command_timeout)
            cleaned_response = clean_response(response)
            if "There is already a connection built." in cleaned_response:
                raise Smrt46SessionBusyError(
                    "SMRT46 reports that another application-layer connection is already built. "
                    "Close the previous client or reset the SMRT46 session before retrying."
                )
            if expected_pattern and expected_pattern not in response:
                raise Smrt46ProtocolError(
                    f"Expected pattern {expected_pattern!r} not present in "
                    f"response to {normalized!r}: {response!r}"
                )
            if cleaned_response:
                self._log_traffic("RX", cleaned_response)

        completed = datetime.now()
        return Smrt46CommandResult(
            command=normalized,
            response=response,
            started_at=started,
            completed_at=completed,
            duration_s=time.monotonic() - started_monotonic,
        )

    def qcfg(self) -> RawAsciiResponse:
        result = self.send_command(build_qcfg_command())
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=[
                "QC response currently returned as raw payload.",
            ],
        )

    def qg(self) -> RawAsciiResponse:
        result = self.send_command(build_qg_command())
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=["Connectivity probe based on PowerDB 'Testing connection' flow."],
        )

    def qry(self) -> RawAsciiResponse:
        result = self.send_command(build_qry_command())
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=[
                "Runtime status query is mapped to the validated QRYALL flow.",
                "Raw payload path kept for compatibility; prefer query_all() for typed status.",
            ],
        )

    def query_gate_state(self) -> Smrt46GateState:
        result = self._send_query_until_valid(
            build_qg_command(),
            validator=parse_qg_response,
            label="QG",
        )
        return parse_qg_response(result.response)

    def query_max_limits(self) -> Smrt46MaxLimits:
        result = self._send_query_until_valid(
            build_qrymax_command(),
            validator=parse_qrymax_response,
            label="QRYMAX",
        )
        return parse_qrymax_response(result.response)

    def query_all(self) -> Smrt46StatusSnapshot:
        result = self._send_query_until_valid(
            build_qry_command(),
            validator=parse_qryall_response,
            label="QRYALL",
        )
        return parse_qryall_response(result.response)

    def configure_current_outputs(
        self, request: Smrt46CurrentInjectionRequest
    ) -> list[Smrt46CommandResult]:
        self._ensure_connected()
        self._validate_current_request(request)
        results = self._prepare_current_output_session()
        for command in build_current_bootstrap_sequence():
            results.append(self._execute_runtime_command(command))
        for command in build_current_injection_sequence(self._build_current_vector_inputs(request)):
            results.append(self._execute_runtime_command(command))
        return results

    def configure_voltage_outputs(
        self, request: Smrt46VoltageInjectionRequest
    ) -> list[Smrt46CommandResult]:
        self._ensure_connected()
        self._validate_voltage_request(request)
        results = self._prepare_current_output_session()
        for command in build_current_bootstrap_sequence():
            results.append(self._execute_runtime_command(command))
        self._validate_voltage_limits(request, self._extract_max_limits(results))
        for command in build_voltage_injection_sequence(
            self._build_voltage_vector_inputs(request),
            frequency_hz=request.frequency_hz,
        ):
            results.append(self._execute_runtime_command(command))
        return results

    def stop_outputs(self) -> list[Smrt46CommandResult]:
        self._ensure_connected()
        results: list[Smrt46CommandResult] = []
        for command in build_current_cleanup_sequence():
            try:
                results.append(self._execute_runtime_command(command))
            except Smrt46Error as exc:
                self.logger.warning(
                    "SMRT46 cleanup command failed, continuing best-effort cleanup: "
                    "command=%r error=%s",
                    normalize_command(command),
                    exc,
                )
        return results

    def run_voltage_injection(
        self,
        request: Smrt46VoltageInjectionRequest,
        *,
        on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None,
    ) -> Smrt46VoltageInjectionResult:
        self._ensure_connected()
        self._validate_voltage_request(request)
        command_results: list[Smrt46CommandResult] = []
        initial_snapshot: Optional[Smrt46StatusSnapshot] = None
        final_snapshot: Optional[Smrt46StatusSnapshot] = None
        alarms: list[str] = []
        observed_peak_voltages: dict[int, float] = {}
        history: list[dict[str, Any]] = []
        notes: list[str] = []
        stop_reason = "unknown"
        trip_detected = False
        no_voltage_poll_count = 0
        started_at = time.monotonic()
        poll_interval_s = max(request.poll_interval_s, self.read_idle_gap, 0.05)
        try:
            command_results = self.configure_voltage_outputs(request)
            time.sleep(poll_interval_s)
            initial_snapshot = self.query_all()
            self._update_observed_voltage_peaks(observed_peak_voltages, initial_snapshot)
            if self._find_unobserved_voltage_outputs(request, initial_snapshot):
                no_voltage_poll_count += 1
            initial_trip = self._is_target_bin_closed(
                initial_snapshot.binary_inputs,
                target_bin=request.target_bin,
                phase="voltage",
            )
            history.append(
                self._build_voltage_runtime_history_entry(
                    phase="initial",
                    snapshot=initial_snapshot,
                    trip_detected=initial_trip,
                )
            )
            if on_snapshot is not None:
                on_snapshot(initial_snapshot)
            while True:
                elapsed_s = time.monotonic() - started_at
                if request.stop_mode == "duration" and request.duration_s is not None:
                    if elapsed_s >= request.duration_s:
                        stop_reason = "duration_elapsed"
                        break
                if request.safety_timeout_s is not None and elapsed_s >= request.safety_timeout_s:
                    stop_reason = "timeout"
                    notes.append(
                        "SMRT46 voltage injection stopped by safety timeout: "
                        f"{request.safety_timeout_s:.3f}s."
                    )
                    break

                time.sleep(poll_interval_s)
                snapshot, query_alarms = self._query_all_until_snapshot_or_alarm()
                if query_alarms:
                    alarms.extend(query_alarms)
                    history.append({"phase": "alarm", "alarms": list(query_alarms)})
                    stop_reason = "alarm"
                    break
                if snapshot is None:
                    raise Smrt46ProtocolError("QRYALL returned neither snapshot nor alarm.")
                final_snapshot = snapshot
                self._update_observed_voltage_peaks(observed_peak_voltages, snapshot)
                unobserved_channels = self._find_unobserved_voltage_outputs(
                    request,
                    snapshot,
                )
                if unobserved_channels:
                    no_voltage_poll_count += 1
                else:
                    no_voltage_poll_count = 0
                snapshot_trip_detected = self._is_target_bin_closed(
                    snapshot.binary_inputs,
                    target_bin=request.target_bin,
                    phase="voltage",
                )
                history.append(
                    self._build_voltage_runtime_history_entry(
                        phase="runtime_poll",
                        snapshot=snapshot,
                        trip_detected=snapshot_trip_detected,
                    )
                )
                if on_snapshot is not None:
                    on_snapshot(snapshot)
                if snapshot_trip_detected:
                    trip_detected = True
                    if not self._has_observed_all_voltage_outputs(
                        request,
                        observed_peak_voltages,
                    ):
                        unobserved_peak_channels = self._find_unobserved_peak_voltage_outputs(
                            request,
                            observed_peak_voltages,
                        )
                        stop_reason = "voltage_output_lost"
                        notes.append(
                            "SMRT46 target binary input closed before requested voltage "
                            "was observed on: "
                            + ", ".join(f"V{channel}" for channel in unobserved_peak_channels)
                            + ". Possible stale binary input, closed-circuit, or "
                            "overcurrent condition."
                        )
                    else:
                        stop_reason = "binary_input_closed"
                    break
                if no_voltage_poll_count >= 2:
                    stop_reason = "voltage_output_lost"
                    notes.append(
                        "SMRT46 voltage output did not reach the requested amplitude on: "
                        + ", ".join(f"V{channel}" for channel in unobserved_channels)
                        + ". Possible closed-circuit or overcurrent condition."
                    )
                    break
                collapsed_channels = self._find_collapsed_voltage_outputs(
                    request,
                    snapshot,
                    observed_peak_voltages,
                )
                if collapsed_channels:
                    stop_reason = "voltage_output_lost"
                    notes.append(
                        "SMRT46 voltage output dropped after being observed on: "
                        + ", ".join(f"V{channel}" for channel in collapsed_channels)
                        + ". Possible closed-circuit or overcurrent condition."
                    )
                    break
                if request.stop_mode == "manual":
                    continue
            if stop_reason in {"duration_elapsed", "manual_stop"}:
                command_results.append(
                    self._execute_runtime_command(build_simulated_trip_command())
                )
        except KeyboardInterrupt:
            stop_reason = "manual_stop"
            notes.append("SMRT46 voltage injection interrupted by caller.")
            with suppress(Smrt46Error):
                command_results.append(
                    self._execute_runtime_command(build_simulated_trip_command())
                )
        finally:
            with suppress(Smrt46Error):
                cleanup_results = self.stop_outputs()
                command_results.extend(cleanup_results)
        if initial_snapshot is None:
            raise Smrt46ProtocolError("Voltage injection did not produce an initial snapshot.")
        if final_snapshot is None:
            final_snapshot = initial_snapshot
        return Smrt46VoltageInjectionResult(
            request=request,
            command_sequence=[result.command for result in command_results],
            initial_snapshot=initial_snapshot,
            final_snapshot=final_snapshot,
            alarms=alarms,
            observed_peak_voltages=observed_peak_voltages,
            stop_reason=stop_reason,
            trip_detected=trip_detected,
            history=history,
            notes=notes,
        )

    def run_current_injection(
        self,
        request: Smrt46CurrentInjectionRequest,
        *,
        poll_count: int = 1,
        on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None,
    ) -> Smrt46CurrentInjectionResult:
        self._ensure_connected()
        self._validate_current_request(request)
        command_results: list[Smrt46CommandResult] = []
        initial_snapshot: Optional[Smrt46StatusSnapshot] = None
        final_snapshot: Optional[Smrt46StatusSnapshot] = None
        alarms: list[str] = []
        observed_peak_currents: dict[int, float] = {}
        history: list[dict[str, Any]] = []
        trip_detected = False
        settle_delay_s = max(self.read_idle_gap, 0.1)
        minimum_polls = max(poll_count, 1)
        polls = 0
        try:
            command_results = self.configure_current_outputs(request)
            time.sleep(settle_delay_s)
            initial_snapshot = self.query_all()
            self._update_observed_current_peaks(observed_peak_currents, initial_snapshot)
            history.append(
                self._build_runtime_history_entry(
                    phase="initial",
                    snapshot=initial_snapshot,
                    trip_detected=self._is_trip_detected(initial_snapshot),
                )
            )
            if on_snapshot is not None:
                on_snapshot(initial_snapshot)
            while True:
                time.sleep(settle_delay_s)
                snapshot, query_alarms = self._query_all_until_snapshot_or_alarm()
                if query_alarms:
                    alarms.extend(query_alarms)
                    history.append({"phase": "alarm", "alarms": list(query_alarms)})
                    break
                if snapshot is None:
                    raise Smrt46ProtocolError("QRYALL returned neither snapshot nor alarm.")
                final_snapshot = snapshot
                self._update_observed_current_peaks(observed_peak_currents, snapshot)
                snapshot_trip_detected = self._is_trip_detected(snapshot)
                history.append(
                    self._build_runtime_history_entry(
                        phase="runtime_poll",
                        snapshot=snapshot,
                        trip_detected=snapshot_trip_detected,
                    )
                )
                if on_snapshot is not None:
                    on_snapshot(snapshot)
                polls += 1
                if polls < minimum_polls:
                    continue
                if snapshot_trip_detected:
                    trip_detected = True
                    break
        finally:
            # Root-cause fix: keep teardown aligned with driver logs by forcing
            # explicit AllOff cleanup after each injection cycle.
            with suppress(Smrt46Error):
                cleanup_results = self.stop_outputs()
                command_results.extend(cleanup_results)
        if initial_snapshot is None:
            raise Smrt46ProtocolError("Current injection did not produce an initial snapshot.")
        return Smrt46CurrentInjectionResult(
            request=request,
            command_sequence=[result.command for result in command_results],
            initial_snapshot=initial_snapshot,
            final_snapshot=final_snapshot,
            alarms=alarms,
            observed_peak_currents=observed_peak_currents,
            trip_detected=trip_detected,
            history=history,
        )

    def run_curve_injection(
        self,
        config: Smrt46CurveTestConfig,
        *,
        on_step: Optional[Callable[[int, float], None]] = None,
        on_snapshot: Optional[Callable[[Smrt46StatusSnapshot], None]] = None,
    ) -> Smrt46CurveTestResult:
        self._ensure_connected()
        phase_sequence = self._normalize_curve_phase_sequence(config.phases)
        self._validate_curve_config(config)
        command_results: list[Smrt46CommandResult] = []
        phase_results: list[Smrt46CurvePhaseResult] = []
        raw_payloads: list[str] = []
        history: list[dict[str, Any]] = []
        notes: list[str] = []
        aborted = False
        last_raw_response = ""
        max_limits: Optional[Smrt46MaxLimits] = None

        def _record_command_result(result: Smrt46CommandResult) -> None:
            nonlocal last_raw_response
            command_results.append(result)
            cleaned = self._append_cleaned_payload(raw_payloads, result.response)
            if cleaned:
                last_raw_response = cleaned

        def _record_raw_payload(raw_payload: str) -> None:
            nonlocal last_raw_response
            if raw_payload:
                raw_payloads.append(raw_payload)
                last_raw_response = raw_payload

        try:
            command_results = self._prepare_current_output_session()
            for result in command_results:
                cleaned = self._append_cleaned_payload(raw_payloads, result.response)
                if cleaned:
                    last_raw_response = cleaned

            for command in build_current_bootstrap_sequence():
                result = self._execute_runtime_command(command)
                _record_command_result(result)
                if normalize_command(command) == build_qrymax_command():
                    max_limits = parse_qrymax_response(result.response)
            self._validate_curve_limits(config, max_limits)

            for phase_index, phase in enumerate(phase_sequence):
                channel, _ = SMRT46_PHASE_CHANNEL_MAP[phase]
                if config.rearm_before_phase:
                    result = self._execute_runtime_command(build_reconfigure_command())
                    _record_command_result(result)
                    # RE; can clear trip monitor/alarm settings used to detect
                    # recloser opening. Re-arm them before the next phase starts.
                    result = self._execute_runtime_command(build_trip_arm_setup_command())
                    _record_command_result(result)
                    result = self._execute_runtime_command(build_open_circuit_alarm_command())
                    _record_command_result(result)

                result = self._execute_runtime_command(build_curve_timer_setup())
                _record_command_result(result)

                if phase_index == 0:
                    init_command = build_curve_phase_init_command(
                        phase,
                        0.0,
                        frequency_hz=config.frequency_hz,
                    )
                else:
                    init_command = build_curve_channel_init_command(
                        channel,
                        amplitude=0.0,
                        frequency_hz=config.frequency_hz,
                    )
                result = self._execute_runtime_command(init_command)
                _record_command_result(result)

                (
                    baseline_snapshot,
                    baseline_alarms,
                    baseline_raw,
                ) = self._query_all_until_snapshot_or_alarm_with_raw()
                _record_raw_payload(baseline_raw)
                if baseline_alarms:
                    notes.extend(baseline_alarms)
                    phase_results.append(
                        Smrt46CurvePhaseResult(
                            phase=phase,
                            channel=channel,
                            stop_reason="deviation_alarm",
                            final_amplitude_a=0.0,
                            raw_final_qryall=None,
                            alarms=list(baseline_alarms),
                        )
                    )
                    history.append(
                        {
                            "phase": phase,
                            "channel": channel,
                            "stop_reason": "deviation_alarm",
                            "final_amplitude_a": 0.0,
                            "alarms": list(baseline_alarms),
                        }
                    )
                    aborted = True
                    break
                if baseline_snapshot is None:
                    raise Smrt46ProtocolError(
                        f"SMRT46 phase {phase} did not produce baseline QRYALL snapshot."
                    )
                if self._is_target_bin_closed(
                    baseline_snapshot.binary_inputs,
                    target_bin=config.target_bin,
                    phase=phase,
                ):
                    raise Smrt46ProtocolError(
                        "SMRT46 target binary input is already latched before phase start: "
                        "phase={phase}, bin={target_bin}, bi={binary_inputs!r}.".format(
                            phase=phase,
                            target_bin=config.target_bin,
                            binary_inputs=baseline_snapshot.binary_inputs,
                        )
                    )

                amplitude = round(config.start_current_a, 4)
                result = self._execute_runtime_command(
                    build_curve_amplitude_step(channel, amplitude)
                )
                command_results.append(result)
                cleaned = self._append_cleaned_payload(raw_payloads, result.response)
                if cleaned:
                    last_raw_response = cleaned
                if on_step is not None:
                    on_step(channel, amplitude)

                stop_reason = "ramp_exhausted"
                phase_alarms: list[str] = []
                final_qryall_raw: Optional[str] = baseline_snapshot.raw
                step_count = 0
                low_current_polls = 0

                while True:
                    gate_state, gate_alarms, gate_raw = self._query_gate_until_state_or_alarm()
                    _record_raw_payload(gate_raw)
                    if gate_alarms:
                        stop_reason = "phase_trip"
                        phase_alarms.extend(gate_alarms)
                        notes.extend(gate_alarms)
                        aborted = True
                        break
                    if gate_state is None:
                        raise Smrt46ProtocolError(
                            f"SMRT46 phase {phase} did not return a valid QG state."
                        )
                    if gate_state.mask != "0000":
                        raise Smrt46ProtocolError(
                            "SMRT46 gate mask blocked curve step: "
                            f"phase={phase}, channel={channel}, mask={gate_state.mask!r}."
                        )

                    result = self._execute_runtime_command(";")
                    _record_command_result(result)

                    if config.step_delay_ms > 0:
                        time.sleep(config.step_delay_ms / 1000.0)
                    step_count += 1

                    should_poll_qryall = (
                        step_count % config.qg_interval == 0 or amplitude >= config.stop_current_a
                    )
                    if should_poll_qryall:
                        snapshot, query_alarms, qryall_raw = (
                            self._query_all_until_snapshot_or_alarm_with_raw()
                        )
                        _record_raw_payload(qryall_raw)
                        if query_alarms:
                            stop_reason = "phase_trip"
                            phase_alarms.extend(query_alarms)
                            notes.extend(query_alarms)
                            aborted = True
                            break
                        if snapshot is None:
                            raise Smrt46ProtocolError(
                                f"SMRT46 QRYALL returned no snapshot in phase {phase}."
                            )
                        if on_snapshot is not None:
                            on_snapshot(snapshot)
                        final_qryall_raw = snapshot.raw
                        if self._is_target_bin_closed(
                            snapshot.binary_inputs,
                            target_bin=config.target_bin,
                            phase=phase,
                        ):
                            stop_reason = "din_closed"
                            break
                        if any(value > 0.0 for value in snapshot.timer_values.values()):
                            stop_reason = "phase_trip"
                            break
                        if self._is_phase_current_collapsed(
                            snapshot,
                            channel=channel,
                            commanded_amplitude=amplitude,
                        ):
                            low_current_polls += 1
                        else:
                            low_current_polls = 0
                        if low_current_polls >= config.trip_confirm_polls:
                            stop_reason = "phase_trip"
                            break

                    if amplitude >= config.stop_current_a:
                        stop_reason = "ramp_exhausted"
                        break

                    next_amplitude = min(config.stop_current_a, amplitude + config.step_size_a)
                    if next_amplitude <= amplitude:
                        stop_reason = "ramp_exhausted"
                        break
                    amplitude = round(next_amplitude, 4)
                    result = self._execute_runtime_command(
                        build_curve_amplitude_step(channel, amplitude)
                    )
                    _record_command_result(result)
                    if on_step is not None:
                        on_step(channel, amplitude)

                phase_result = Smrt46CurvePhaseResult(
                    phase=phase,
                    channel=channel,
                    stop_reason=stop_reason,
                    final_amplitude_a=amplitude,
                    raw_final_qryall=final_qryall_raw,
                    alarms=phase_alarms,
                )
                phase_results.append(phase_result)
                history.append(
                    {
                        "phase": phase,
                        "channel": channel,
                        "stop_reason": stop_reason,
                        "final_amplitude_a": amplitude,
                        "alarms": list(phase_alarms),
                    }
                )

                result = self._execute_runtime_command(build_reset_command())
                _record_command_result(result)
                if aborted:
                    break
        finally:
            with suppress(Smrt46Error):
                cleanup_results = self.stop_outputs()
                command_results.extend(cleanup_results)
                for result in cleanup_results:
                    cleaned = self._append_cleaned_payload(raw_payloads, result.response)
                    if cleaned:
                        last_raw_response = cleaned

        trip_detected = any(p.stop_reason in ("din_closed", "phase_trip") for p in phase_results)
        success = trip_detected or not aborted
        final_state = "COMPLETE" if success else "DEVIATION_ALARM"
        return Smrt46CurveTestResult(
            config=config,
            phases=phase_results,
            command_sequence=[result.command for result in command_results],
            aborted=aborted,
            success=success,
            final_state=final_state,
            last_raw_response=last_raw_response,
            raw_payloads=raw_payloads,
            history=history,
            notes=notes,
        )

    def hsu(self) -> RawAsciiResponse:
        result = self.send_command(build_hsu_command())
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=["Reset test set command observed at PowerDB session startup."],
        )

    def qip(self) -> Smrt46IpConfig:
        result = self.send_command(build_qip_command())
        return parse_qip_response(result.response)

    def qver(self) -> Smrt46VersionInfo:
        result = self.send_command(build_qver_command())
        return parse_qver_response(self._collect_qver_payload(result.response))

    def syssetf(self) -> RawAsciiResponse:
        result = self.send_command(build_syssetf_command())
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=["System frequency sync command observed before SU in PowerDB logs."],
        )

    def su(self) -> RawAsciiResponse:
        result = self.send_command(build_su_command(), expect_response=False)
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=["Software reset command sent without waiting for a response."],
        )

    def raw(self, command: str) -> RawAsciiResponse:
        result = self.send_command(command)
        return RawAsciiResponse(
            command=result.command,
            raw=result.response,
            notes=["Raw response returned without parsing."],
        )

    def initialize_ethernet_session(self) -> dict[str, RawAsciiResponse]:
        idle_before = self.qg()
        config = self.qcfg()
        idle_after = self.qg()
        startup = self.hsu()
        return {
            "idle_before": idle_before,
            "config": config,
            "idle_after": idle_after,
            "startup": startup,
        }

    def _read_response(self, *, timeout: float) -> str:
        self._ensure_connected()
        assert self._sock is not None
        started = time.monotonic()
        last_data_at: Optional[float] = None

        while True:
            if ";" in self._rx_buffer:
                frame, remainder = self._rx_buffer.split(";", 1)
                self._rx_buffer = remainder
                return clean_response(frame)

            now = time.monotonic()
            if now - started > timeout:
                if self._rx_buffer:
                    frame = clean_response(self._rx_buffer)
                    self._rx_buffer = ""
                    return frame
                raise Smrt46TimeoutError(f"No SMRT46 response received within {timeout:.2f}s.")
            try:
                chunk = self._sock.recv(DEFAULT_SMRT46_CHUNK_SIZE)
            except socket.timeout:
                if (
                    self._rx_buffer
                    and last_data_at is not None
                    and now - last_data_at >= self.read_idle_gap
                ):
                    frame = clean_response(self._rx_buffer)
                    self._rx_buffer = ""
                    return frame
                continue
            except ConnectionResetError as exc:
                self.close()
                raise Smrt46SessionBusyError(
                    "SMRT46 reset the TCP connection while starting the session. "
                    "Another client session may already be active. "
                    "Close the other client or reset the SMRT46 session before retrying."
                ) from exc
            except OSError as exc:
                if getattr(exc, "errno", None) == 104:
                    self.close()
                    raise Smrt46SessionBusyError(
                        "SMRT46 reset the TCP connection while starting the session. "
                        "Another client session may already be active. "
                        "Close the other client or reset the SMRT46 session before retrying."
                    ) from exc
                raise Smrt46ConnectionError(f"Failed while reading SMRT46 response: {exc}") from exc

            if not chunk:
                if self._rx_buffer:
                    frame = clean_response(self._rx_buffer)
                    self._rx_buffer = ""
                    return frame
                self.close()
                raise Smrt46ConnectionError("SMRT46 closed the connection.")

            self._rx_buffer += chunk.decode("ascii", errors="replace")
            last_data_at = time.monotonic()

    def _ensure_connected(self) -> None:
        if self._sock is None:
            raise Smrt46ConnectionError("SMRT46 client is not connected.")

    def _log_traffic(self, direction: str, payload: str) -> None:
        message = f"{direction} {'>' if direction == 'TX' else '<'} {payload}"
        self.logger.debug(message)

    def _terminate_socket(self, sock: socket.socket) -> None:
        # PowerDB sends SU during SMRT46 session startup/teardown flows. Sending it
        # before TCP close mirrors bench logs and helps the device release the active
        # application session for the next client.
        command = build_su_command()
        sock.sendall(command.encode("ascii"))
        self._log_traffic("TX", command.rstrip())
        time.sleep(self.DISCONNECT_SETTLE_DELAY_S)

    def _collect_qver_payload(self, first_response: str) -> str:
        frames = [clean_response(first_response)]
        while ";" in self._rx_buffer:
            frame, remainder = self._rx_buffer.split(";", 1)
            cleaned = clean_response(frame)
            if not cleaned.upper().startswith("DSP"):
                self._rx_buffer = frame + ";" + remainder
                break
            frames.append(cleaned)
            self._rx_buffer = remainder
            self._log_traffic("RX", cleaned)
        return ";".join(frame for frame in frames if frame)

    def _prepare_current_output_session(self) -> list[Smrt46CommandResult]:
        retry_delays_s = (0.5, 1.0, 2.0, 3.0)
        attempts = 1 + len(retry_delays_s)
        last_exc: Optional[Smrt46SessionBusyError] = None
        for attempt in range(attempts):
            if attempt > 0:
                self.close()
                time.sleep(max(self.read_idle_gap, retry_delays_s[attempt - 1]))
                self.connect()
                time.sleep(max(self.read_idle_gap, 0.1))
            try:
                results = self._run_current_output_startup_sequence()
                time.sleep(1.0)
                return results
            except Smrt46SessionBusyError as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise Smrt46SessionBusyError(
                "SMRT46 did not release a stable session after "
                f"{attempts} startup attempt(s). "
                "Close other clients and reset the SMRT46 session before retrying."
            ) from last_exc
        raise Smrt46SessionBusyError("SMRT46 startup session preparation failed.")

    def _run_current_output_startup_sequence(self) -> list[Smrt46CommandResult]:
        first_gate = self.send_command(build_qg_command())
        parse_qg_response(first_gate.response)
        hsu_result = self.send_command(build_hsu_command())
        qc_result = self.send_command(build_qcfg_command())
        # SYSSETF responds "Done!!" immediately when the device was recently active,
        # but gives no response on a fresh connection (PowerDB observes a 5 s timeout).
        # Always attempt a read with a short timeout so any buffered "Done!!" is
        # consumed before subsequent commands read from the socket.
        syssetf_cmd = build_syssetf_command()
        syssetf_started = datetime.now()
        syssetf_mono = time.monotonic()
        try:
            syssetf_result = self.send_command(syssetf_cmd, timeout=1.0)
        except Smrt46TimeoutError:
            syssetf_result = Smrt46CommandResult(
                command=syssetf_cmd,
                response="",
                started_at=syssetf_started,
                completed_at=datetime.now(),
                duration_s=time.monotonic() - syssetf_mono,
            )
        su_result = self.send_command(build_su_command(), expect_response=False)
        return [first_gate, hsu_result, qc_result, syssetf_result, su_result]

    def _execute_runtime_command(self, command: str) -> Smrt46CommandResult:
        normalized = normalize_command(command)
        if normalized == build_qrymax_command():
            return self._send_query_until_valid(
                normalized,
                validator=parse_qrymax_response,
                label="QRYMAX",
            )
        if normalized == build_qry_command():
            return self._send_query_until_valid(
                normalized,
                validator=parse_qryall_response,
                label="QRYALL",
            )
        if normalized == build_qg_command():
            result = self._send_query_until_valid(
                normalized,
                validator=parse_qg_response,
                label="QG",
            )
            parse_qg_response(result.response)
            return result
        if normalized == build_master_output_off_command():
            return self.send_command(normalized, expect_response=False)
        if normalized == ";":
            return self.send_command(normalized, expect_response=False)
        if normalized == "XU;":
            result = self.send_command(normalized, timeout=max(self.command_timeout, 5.0))
            if not self._is_reset_ack(result.response):
                raise Smrt46ProtocolError(
                    f"Unexpected reset response to {normalized!r}: {result.response!r}"
                )
            # Bench traces show short gaps after reset before further config.
            time.sleep(max(self.read_idle_gap, self.POST_RESET_SETTLE_DELAY_S))
            return result
        if normalized.startswith("BIV:"):
            return self._execute_biv_command(normalized)
        if normalized == "QHS,":
            result = self.send_command(normalized)
            cleaned = clean_response(result.response)
            if "ERROR:" in cleaned.upper():
                alarms = parse_alarm_response(cleaned).alarms
                message = "; ".join(alarms) if alarms else cleaned
                raise Smrt46ProtocolError(f"SMRT46 alarm response to QHS: {message}")
            if not self._is_qhs_ack(result.response):
                raise Smrt46ProtocolError(
                    f"Unexpected QHS response to {normalized!r}: {result.response!r}"
                )
            return result
        return self.send_command(normalized, expect_response=False)

    def _build_current_vector_inputs(
        self, request: Smrt46CurrentInjectionRequest
    ) -> list[Optional[float]]:
        currents: list[Optional[float]] = [None, None, None]
        for current in request.currents:
            currents[current.channel - 1] = current.amplitude if current.enabled else None
        return currents

    def _build_voltage_vector_inputs(
        self, request: Smrt46VoltageInjectionRequest
    ) -> list[Optional[float]]:
        voltages: list[Optional[float]] = [None, None, None, None]
        for voltage in request.voltages:
            voltages[voltage.channel - 1] = voltage.amplitude if voltage.enabled else None
        return voltages

    def _validate_current_request(self, request: Smrt46CurrentInjectionRequest) -> None:
        if not request.currents:
            raise Smrt46ProtocolError(
                "Current injection request must include at least one channel."
            )
        seen_channels = set()
        expected_phases = SMRT46_DEFAULT_CURRENT_PHASES
        for current in request.currents:
            if current.channel < 1 or current.channel > 3:
                raise Smrt46ProtocolError(
                    f"Unsupported SMRT46 current channel: {current.channel!r}."
                )
            if current.channel in seen_channels:
                raise Smrt46ProtocolError(
                    f"Duplicate SMRT46 current channel in request: {current.channel!r}."
                )
            seen_channels.add(current.channel)
            expected_phase = expected_phases[current.channel - 1]
            if abs(current.phase_deg - expected_phase) > 1e-6:
                raise Smrt46ProtocolError(
                    "Current phase does not match the validated SMRT46 scaffold for "
                    "this channel: channel={channel}, phase={phase}, expected={expected}.".format(
                        channel=current.channel,
                        phase=current.phase_deg,
                        expected=expected_phase,
                    )
                )
            if abs(current.frequency_hz - request.frequency_hz) > 1e-6:
                raise Smrt46ProtocolError(
                    "Channel frequency must match the request frequency: "
                    "channel={channel}, channel_frequency={channel_frequency}, "
                    "request_frequency={request_frequency}.".format(
                        channel=current.channel,
                        channel_frequency=current.frequency_hz,
                        request_frequency=request.frequency_hz,
                    )
                )

    def _validate_voltage_request(self, request: Smrt46VoltageInjectionRequest) -> None:
        if not request.voltages:
            raise Smrt46ProtocolError(
                "Voltage injection request must include at least one channel."
            )
        if request.frequency_hz <= 0.0:
            raise Smrt46ProtocolError("SMRT46 voltage frequency_hz must be > 0.")
        normalized_stop_mode = request.stop_mode.strip().lower()
        if normalized_stop_mode not in {"binary_input", "duration", "manual"}:
            raise Smrt46ProtocolError(
                "SMRT46 voltage stop_mode must be one of: binary_input, duration, manual."
            )
        request.stop_mode = normalized_stop_mode
        if request.target_bin < 1 or request.target_bin > 10:
            raise Smrt46ProtocolError("SMRT46 voltage target_bin must be in the range [1, 10].")
        if request.poll_interval_s <= 0.0:
            raise Smrt46ProtocolError("SMRT46 voltage poll_interval_s must be > 0.")
        if request.duration_s is not None and request.duration_s <= 0.0:
            raise Smrt46ProtocolError("SMRT46 voltage duration_s must be > 0 when set.")
        if request.stop_mode == "duration" and request.duration_s is None:
            raise Smrt46ProtocolError("SMRT46 voltage duration stop mode requires duration_s.")
        if request.safety_timeout_s is not None and request.safety_timeout_s <= 0.0:
            raise Smrt46ProtocolError("SMRT46 voltage safety_timeout_s must be > 0 when set.")
        seen_channels = set()
        for voltage in request.voltages:
            if voltage.channel < 1 or voltage.channel > 4:
                raise Smrt46ProtocolError(
                    f"Unsupported SMRT46 voltage channel: {voltage.channel!r}."
                )
            if voltage.channel in seen_channels:
                raise Smrt46ProtocolError(
                    f"Duplicate SMRT46 voltage channel in request: {voltage.channel!r}."
                )
            seen_channels.add(voltage.channel)
            if voltage.amplitude < 0.0:
                raise Smrt46ProtocolError("SMRT46 voltage amplitude cannot be negative.")
            expected_phase = SMRT46_DEFAULT_VOLTAGE_OUTPUT_PHASES[voltage.channel - 1]
            if abs(voltage.phase_deg - expected_phase) > 1e-6:
                raise Smrt46ProtocolError(
                    "Voltage phase does not match the validated SMRT46 scaffold for "
                    "this channel: channel={channel}, phase={phase}, expected={expected}.".format(
                        channel=voltage.channel,
                        phase=voltage.phase_deg,
                        expected=expected_phase,
                    )
                )
            if abs(voltage.frequency_hz - request.frequency_hz) > 1e-6:
                raise Smrt46ProtocolError(
                    "Channel frequency must match the request frequency: "
                    "channel={channel}, channel_frequency={channel_frequency}, "
                    "request_frequency={request_frequency}.".format(
                        channel=voltage.channel,
                        channel_frequency=voltage.frequency_hz,
                        request_frequency=request.frequency_hz,
                    )
                )

    def _normalize_curve_phase_sequence(self, phases: list[str]) -> list[str]:
        if not phases:
            raise Smrt46ProtocolError("SMRT46 curve config must include at least one phase.")
        normalized: list[str] = []
        seen: set[str] = set()
        for phase in phases:
            normalized_phase = str(phase).strip().upper()
            if normalized_phase not in SMRT46_PHASE_CHANNEL_MAP:
                raise Smrt46ProtocolError(f"Unsupported SMRT46 curve phase: {phase!r}.")
            if normalized_phase in seen:
                raise Smrt46ProtocolError(
                    f"Duplicate SMRT46 curve phase in request: {normalized_phase!r}."
                )
            seen.add(normalized_phase)
            normalized.append(normalized_phase)
        return normalized

    def _validate_curve_config(self, config: Smrt46CurveTestConfig) -> None:
        if config.start_current_a < 0.0:
            raise Smrt46ProtocolError("SMRT46 curve start_current_a must be >= 0.")
        if config.stop_current_a <= 0.0:
            raise Smrt46ProtocolError("SMRT46 curve stop_current_a must be > 0.")
        if config.start_current_a > config.stop_current_a:
            raise Smrt46ProtocolError("SMRT46 curve start_current_a must be <= stop_current_a.")
        if config.step_size_a <= 0.0:
            raise Smrt46ProtocolError("SMRT46 curve step_size_a must be > 0.")
        if config.step_delay_ms < 0:
            raise Smrt46ProtocolError("SMRT46 curve step_delay_ms must be >= 0.")
        if config.qg_interval < 1:
            raise Smrt46ProtocolError("SMRT46 curve qg_interval must be >= 1.")
        if config.trip_confirm_polls < 1:
            raise Smrt46ProtocolError("SMRT46 curve trip_confirm_polls must be >= 1.")
        if config.target_bin < 1 or config.target_bin > 10:
            raise Smrt46ProtocolError("SMRT46 curve target_bin must be in the range [1, 10].")
        if config.frequency_hz <= 0.0:
            raise Smrt46ProtocolError("SMRT46 curve frequency_hz must be > 0.")

    def _validate_curve_limits(
        self,
        config: Smrt46CurveTestConfig,
        limits: Optional[Smrt46MaxLimits],
    ) -> None:
        if limits is None:
            raise Smrt46ProtocolError("SMRT46 curve bootstrap did not produce QRYMAX limits.")
        continuous_limit = min(limits.continuous_current_limits)
        if config.stop_current_a > continuous_limit:
            raise Smrt46ProtocolError(
                "SMRT46 curve stop_current_a exceeds continuous current limit: "
                f"stop={config.stop_current_a:.4f}A, limit={continuous_limit:.4f}A."
            )

    def _extract_max_limits(self, results: list[Smrt46CommandResult]) -> Optional[Smrt46MaxLimits]:
        for result in results:
            if result.command == build_qrymax_command():
                return parse_qrymax_response(result.response)
        return None

    def _validate_voltage_limits(
        self,
        request: Smrt46VoltageInjectionRequest,
        limits: Optional[Smrt46MaxLimits],
    ) -> None:
        if limits is None:
            raise Smrt46ProtocolError("SMRT46 voltage bootstrap did not produce QRYMAX limits.")
        for voltage in request.voltages:
            if not voltage.enabled:
                continue
            limit = limits.voltage_limits[voltage.channel - 1]
            if voltage.amplitude > limit:
                raise Smrt46ProtocolError(
                    "SMRT46 voltage amplitude exceeds channel limit: "
                    "channel=V{channel}, amplitude={amplitude:.4f}V, limit={limit:.4f}V.".format(
                        channel=voltage.channel,
                        amplitude=voltage.amplitude,
                        limit=limit,
                    )
                )

    def _append_cleaned_payload(self, payloads: list[str], response: str) -> str:
        cleaned = clean_response(response)
        if cleaned:
            payloads.append(cleaned)
        return cleaned

    def _is_target_bin_closed(self, bi_field: str, *, target_bin: int, phase: str) -> bool:
        try:
            return is_binary_input_closed(bi_field, target_bin)
        except ValueError as exc:
            raise Smrt46ProtocolError(
                "Invalid BI payload while checking target binary input: "
                f"phase={phase}, bin={target_bin}, bi={bi_field!r}."
            ) from exc

    def _is_reset_ack(self, response: str) -> bool:
        return clean_response(response).lower().startswith("done")

    def _is_biv_ack(self, response: str) -> bool:
        cleaned = clean_response(response).lower()
        return cleaned.startswith("ok") or cleaned.startswith("done")

    def _is_qhs_ack(self, response: str) -> bool:
        cleaned = clean_response(response).lower()
        return cleaned.startswith("ack") or cleaned.startswith("ok")

    def _execute_biv_command(self, normalized: str) -> Smrt46CommandResult:
        timeout_s = max(self.command_timeout, 5.0)
        retry_delays_s = (0.3, 0.7)
        attempts = 1 + len(retry_delays_s)
        for attempt in range(attempts):
            try:
                result = self.send_command(normalized, timeout=timeout_s)
                if not self._is_biv_ack(result.response):
                    raise Smrt46ProtocolError(
                        f"Unexpected BIV response to {normalized!r}: {result.response!r}"
                    )
                # Keep pacing close to the validated driver trace.
                time.sleep(0.1)
                return result
            except (Smrt46TimeoutError, Smrt46ConnectionError) as exc:
                if attempt + 1 >= attempts:
                    raise
                self.logger.warning(
                    "SMRT46 BIV transport recovery %s/%s after error on %r: %s",
                    attempt + 1,
                    attempts,
                    normalized,
                    exc,
                )
                self._recover_after_biv_transport_error(backoff_s=retry_delays_s[attempt])
            except Smrt46ProtocolError as exc:
                if attempt + 1 >= attempts:
                    raise
                self.logger.warning(
                    "SMRT46 BIV command retry %s/%s after protocol error on %r: %s",
                    attempt + 1,
                    attempts,
                    normalized,
                    exc,
                )
                time.sleep(max(self.read_idle_gap, retry_delays_s[attempt]))
        raise Smrt46ProtocolError(f"BIV command failed after {attempts} attempts: {normalized!r}")

    def _recover_after_biv_transport_error(self, *, backoff_s: float) -> None:
        self.close()
        time.sleep(max(self.read_idle_gap, backoff_s))
        self.connect()
        time.sleep(max(self.read_idle_gap, self.POST_RESET_SETTLE_DELAY_S))
        try:
            reset_result = self.send_command("XU;", timeout=max(self.command_timeout, 5.0))
            if self._is_reset_ack(reset_result.response):
                time.sleep(max(self.read_idle_gap, self.POST_RESET_SETTLE_DELAY_S))
            else:
                self.logger.warning(
                    "SMRT46 post-reconnect XU returned unexpected response: %r",
                    reset_result.response,
                )
        except Smrt46Error as exc:
            self.logger.warning("SMRT46 post-reconnect XU failed before BIV retry: %s", exc)

    def _is_broken_pipe_error(self, exc: OSError) -> bool:
        if isinstance(exc, BrokenPipeError):
            return True
        if getattr(exc, "errno", None) == 32:
            return True
        return "broken pipe" in str(exc).lower()

    def _is_connection_reset_error(self, exc: OSError) -> bool:
        if isinstance(exc, ConnectionResetError):
            return True
        if getattr(exc, "errno", None) == 104:
            return True
        return "connection reset" in str(exc).lower()

    def _is_session_busy_transport_error(self, exc: OSError) -> bool:
        return self._is_broken_pipe_error(exc) or self._is_connection_reset_error(exc)

    def _send_query_until_valid(
        self,
        command: str,
        *,
        validator: Any,
        label: str,
        max_attempts: int = 2,
        max_followup_frames: int = 6,
    ) -> Smrt46CommandResult:
        last_response = ""
        for _ in range(max_attempts):
            for candidate in self._query_command_candidates(command, label=label):
                result = self.send_command(candidate)
                response = result.response
                for _ in range(max_followup_frames):
                    cleaned = clean_response(response)
                    if not cleaned:
                        try:
                            response = self._read_response(timeout=self.command_timeout)
                        except (Smrt46Error, AttributeError):
                            break
                        cleaned_follow_up = clean_response(response)
                        if cleaned_follow_up:
                            self._log_traffic("RX", cleaned_follow_up)
                        continue

                    last_response = response
                    try:
                        validator(response)
                        result.response = response
                        return result
                    except Smrt46ProtocolError:
                        try:
                            response = self._read_response(timeout=self.command_timeout)
                        except (Smrt46Error, AttributeError):
                            break
                        cleaned_follow_up = clean_response(response)
                        if cleaned_follow_up:
                            self._log_traffic("RX", cleaned_follow_up)
        raise Smrt46ProtocolError(
            "Unexpected {label} response after {attempts} attempt(s): {response!r}".format(
                label=label,
                attempts=max_attempts,
                response=last_response,
            )
        )

    @staticmethod
    def _query_command_candidates(command: str, *, label: str) -> tuple[str, ...]:
        if label != "QRYALL":
            return (command,)
        # Bench traces use both QRYALL; and QRYALL, depending on flow/firmware.
        candidates = [command, "QRYALL;", "QRYALL,"]
        unique: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in unique:
                unique.append(candidate)
        return tuple(unique)

    def _query_gate_until_state_or_alarm(
        self,
        *,
        max_frames: int = 8,
    ) -> tuple[Optional[Smrt46GateState], list[str], str]:
        result = self.send_command(build_qg_command())
        response = result.response
        raw_payload = ""
        for _ in range(max_frames):
            cleaned = clean_response(response)
            if cleaned:
                raw_payload = cleaned
            if "ERROR:" in cleaned.upper():
                return None, parse_alarm_response(cleaned).alarms, raw_payload
            try:
                return parse_qg_response(response), [], raw_payload
            except Smrt46ProtocolError:
                try:
                    response = self._read_response(timeout=self.command_timeout)
                except Smrt46Error:
                    break
                cleaned_follow_up = clean_response(response)
                if cleaned_follow_up:
                    self._log_traffic("RX", cleaned_follow_up)
        raise Smrt46ProtocolError(
            "Unexpected QG response while waiting for gate/alarm: {response!r}".format(
                response=response
            )
        )

    def _query_all_until_snapshot_or_alarm_with_raw(
        self,
        *,
        max_frames: int = 8,
    ) -> tuple[Optional[Smrt46StatusSnapshot], list[str], str]:
        last_response = ""
        for command in self._query_command_candidates(build_qry_command(), label="QRYALL"):
            result = self.send_command(command)
            response = result.response
            raw_payload = ""
            for _ in range(max_frames):
                cleaned = clean_response(response)
                if not cleaned:
                    try:
                        response = self._read_response(timeout=self.command_timeout)
                    except Smrt46Error:
                        break
                    cleaned_follow_up = clean_response(response)
                    if cleaned_follow_up:
                        self._log_traffic("RX", cleaned_follow_up)
                    continue

                raw_payload = cleaned
                if "ERROR:" in cleaned.upper():
                    return None, parse_alarm_response(cleaned).alarms, raw_payload
                try:
                    snapshot = parse_qryall_response(response)
                    return snapshot, [], snapshot.raw
                except Smrt46ProtocolError:
                    last_response = response
                    try:
                        response = self._read_response(timeout=self.command_timeout)
                    except Smrt46Error:
                        break
                    cleaned_follow_up = clean_response(response)
                    if cleaned_follow_up:
                        self._log_traffic("RX", cleaned_follow_up)
        raise Smrt46ProtocolError(
            "Unexpected QRYALL response while waiting for snapshot/alarm: {response!r}".format(
                response=last_response,
            )
        )

    def _query_all_until_snapshot_or_alarm(
        self,
        *,
        max_frames: int = 8,
    ) -> tuple[Optional[Smrt46StatusSnapshot], list[str]]:
        snapshot, alarms, _ = self._query_all_until_snapshot_or_alarm_with_raw(
            max_frames=max_frames
        )
        return snapshot, alarms

    def _is_trip_detected(self, snapshot: Smrt46StatusSnapshot) -> bool:
        if any(bit == "1" for bit in snapshot.binary_inputs):
            return True
        return any(value > 0.0 for value in snapshot.timer_values.values())

    def _update_observed_current_peaks(
        self,
        observed_peak_currents: dict[int, float],
        snapshot: Smrt46StatusSnapshot,
    ) -> None:
        for measured in snapshot.currents:
            previous = observed_peak_currents.get(measured.channel, 0.0)
            if measured.amplitude > previous:
                observed_peak_currents[measured.channel] = measured.amplitude

    def _update_observed_voltage_peaks(
        self,
        observed_peak_voltages: dict[int, float],
        snapshot: Smrt46StatusSnapshot,
    ) -> None:
        for measured in snapshot.voltages:
            previous = observed_peak_voltages.get(measured.channel, 0.0)
            if measured.amplitude > previous:
                observed_peak_voltages[measured.channel] = measured.amplitude

    def _find_collapsed_voltage_outputs(
        self,
        request: Smrt46VoltageInjectionRequest,
        snapshot: Smrt46StatusSnapshot,
        observed_peak_voltages: dict[int, float],
    ) -> list[int]:
        measured_by_channel = {
            measured.channel: measured.amplitude for measured in snapshot.voltages
        }
        collapsed: list[int] = []
        for voltage in request.voltages:
            if (not voltage.enabled) or voltage.amplitude <= 0.0:
                continue
            observed_peak = observed_peak_voltages.get(voltage.channel, 0.0)
            minimum_expected = max(
                self.VOLTAGE_COLLAPSE_MIN_V,
                voltage.amplitude * self.VOLTAGE_COLLAPSE_RATIO,
            )
            if observed_peak < minimum_expected:
                continue
            measured = measured_by_channel.get(voltage.channel)
            if measured is not None and measured < minimum_expected:
                collapsed.append(voltage.channel)
        return collapsed

    def _find_unobserved_voltage_outputs(
        self,
        request: Smrt46VoltageInjectionRequest,
        snapshot: Smrt46StatusSnapshot,
    ) -> list[int]:
        measured_by_channel = {
            measured.channel: measured.amplitude for measured in snapshot.voltages
        }
        unobserved: list[int] = []
        for voltage in request.voltages:
            if (not voltage.enabled) or voltage.amplitude <= 0.0:
                continue
            minimum_expected = max(
                self.VOLTAGE_COLLAPSE_MIN_V,
                voltage.amplitude * self.VOLTAGE_COLLAPSE_RATIO,
            )
            measured = measured_by_channel.get(voltage.channel)
            if measured is not None and measured < minimum_expected:
                unobserved.append(voltage.channel)
        return unobserved

    def _has_observed_all_voltage_outputs(
        self,
        request: Smrt46VoltageInjectionRequest,
        observed_peak_voltages: dict[int, float],
    ) -> bool:
        expected_channels = 0
        for voltage in request.voltages:
            if (not voltage.enabled) or voltage.amplitude <= 0.0:
                continue
            expected_channels += 1
            minimum_expected = max(
                self.VOLTAGE_COLLAPSE_MIN_V,
                voltage.amplitude * self.VOLTAGE_COLLAPSE_RATIO,
            )
            if observed_peak_voltages.get(voltage.channel, 0.0) < minimum_expected:
                return False
        return expected_channels > 0

    def _find_unobserved_peak_voltage_outputs(
        self,
        request: Smrt46VoltageInjectionRequest,
        observed_peak_voltages: dict[int, float],
    ) -> list[int]:
        unobserved: list[int] = []
        for voltage in request.voltages:
            if (not voltage.enabled) or voltage.amplitude <= 0.0:
                continue
            minimum_expected = max(
                self.VOLTAGE_COLLAPSE_MIN_V,
                voltage.amplitude * self.VOLTAGE_COLLAPSE_RATIO,
            )
            if observed_peak_voltages.get(voltage.channel, 0.0) < minimum_expected:
                unobserved.append(voltage.channel)
        return unobserved

    def _build_runtime_history_entry(
        self,
        *,
        phase: str,
        snapshot: Smrt46StatusSnapshot,
        trip_detected: bool,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "trip_detected": trip_detected,
            "elapsed_time_s": snapshot.elapsed_time_s,
            "binary_inputs": snapshot.binary_inputs,
            "binary_outputs": snapshot.binary_outputs,
            "event_count": snapshot.event_count,
            "timer_values": dict(snapshot.timer_values),
            "currents": [
                {
                    "channel": measured.channel,
                    "enabled": measured.enabled,
                    "amplitude": measured.amplitude,
                    "phase_deg": measured.phase_deg,
                    "frequency_hz": measured.frequency_hz,
                }
                for measured in snapshot.currents
            ],
        }

    def _build_voltage_runtime_history_entry(
        self,
        *,
        phase: str,
        snapshot: Smrt46StatusSnapshot,
        trip_detected: bool,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "trip_detected": trip_detected,
            "elapsed_time_s": snapshot.elapsed_time_s,
            "binary_inputs": snapshot.binary_inputs,
            "binary_outputs": snapshot.binary_outputs,
            "event_count": snapshot.event_count,
            "timer_values": dict(snapshot.timer_values),
            "voltages": [
                {
                    "channel": measured.channel,
                    "enabled": measured.enabled,
                    "amplitude": measured.amplitude,
                    "phase_deg": measured.phase_deg,
                    "frequency_hz": measured.frequency_hz,
                }
                for measured in snapshot.voltages
            ],
        }

    def _is_phase_current_collapsed(
        self,
        snapshot: Smrt46StatusSnapshot,
        *,
        channel: int,
        commanded_amplitude: float,
    ) -> bool:
        if commanded_amplitude <= 0.0:
            return False
        measured_amplitude: Optional[float] = None
        for measured in snapshot.currents:
            if measured.channel == channel:
                measured_amplitude = measured.amplitude
                break
        if measured_amplitude is None:
            return False
        minimum_expected = max(
            self.PHASE_CURRENT_COLLAPSE_MIN_A,
            commanded_amplitude * self.PHASE_CURRENT_COLLAPSE_RATIO,
        )
        return measured_amplitude < minimum_expected
