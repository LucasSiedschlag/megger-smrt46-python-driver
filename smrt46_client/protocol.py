from __future__ import annotations

from typing import Optional, Sequence

DEFAULT_SMRT46_PORT = 8000
DEFAULT_SMRT46_CONNECT_TIMEOUT = 3.0
DEFAULT_SMRT46_COMMAND_TIMEOUT = 2.0
DEFAULT_SMRT46_IDLE_GAP = 0.05
DEFAULT_SMRT46_CHUNK_SIZE = 4096

SMRT46_DEFAULT_CURRENT_PHASES = (0.0, 120.0, 240.0)
SMRT46_DEFAULT_VOLTAGE_PHASES = (0.0, 120.0, 240.0)
SMRT46_DEFAULT_VOLTAGE_OUTPUT_PHASES = (0.0, 120.0, 240.0, 0.0)
SMRT46_DEFAULT_FREQUENCY_HZ = 60.0
SMRT46_PHASE_CHANNEL_MAP = {
    "A": (1, 0.0),
    "B": (2, 120.0),
    "C": (3, 240.0),
}


def normalize_command(command: str) -> str:
    normalized = command.strip()
    if not normalized:
        return ";"
    if normalized.endswith((";", ",")):
        return normalized
    return f"{normalized};"


def build_qcfg_command() -> str:
    return "QC;"


def build_qg_command() -> str:
    return "qg,"


def build_hsu_command() -> str:
    return "HSU;"


def build_qry_command() -> str:
    # Runtime status default currently mapped to QRYALL.
    # QRYALL is the validated operational status command.
    return "QRYALL;"


def build_qrymax_command() -> str:
    return "QRYMAX;"


def build_qip_command() -> str:
    return "QIP;"


def build_qver_command() -> str:
    return "QVER;"


def build_syssetf_command() -> str:
    return "SYSSETF,"


def build_su_command() -> str:
    return "SU;"


def build_reset_command() -> str:
    return "XU;"


def build_reconfigure_command() -> str:
    return "RE;"


def build_biv_threshold_command(post_index: int, threshold: int) -> str:
    return "BIV:{post}:{threshold};".format(post=post_index, threshold=threshold)


def build_qhs_command() -> str:
    return "QHS,"


def build_qg_runtime_command() -> str:
    return "qg,"


def build_runtime_timer_setup_command() -> str:
    return (
        "T01CAU,T01HD,T01AD,T02CAU,T02HD,T02AD,T03CAU,T03HD,T03AD,"
        "T04CAU,T04HD,T04AD,T05CAU,T05HD,T05AD,T06CAU,T06HD,T06AD,"
        "T07CAU,T07HD,T07AD,T08CAU,T08HD,T08AD,T09CAU,T09HD,T09AD,"
        "T10CAU,T10HD,T10AD,TR,"
    )


def build_trip_arm_setup_command() -> str:
    return "t01m,t01sto,t01cal,VFMIN40E,VFMIN00O,,TR,"


def build_open_circuit_alarm_command(enabled: bool = True) -> str:
    return "OCA:ON," if enabled else "OCA:OFF,"


def build_scaling_setup_command() -> str:
    return (
        "td2,DISON,HBOFF,HBV:OFF,"
        "v1,scale1.000,v2,scale1.000,v3,scale1.000,v4,scale1.000,"
        "c1,scale1.000,c2,scale1.000,c3,scale1.000,"
        "MAXV0.000000,MAXI0.000000,QHS,"
    )


def build_voltage_feedback_setup_command() -> str:
    return "V1,DFLACON,DFLDCON,V2,DFLACON,DFLDCON,V3,DFLACON,DFLDCON,V4,DFLACON,DFLDCON,QHS,"


def build_current_feedback_setup_command() -> str:
    return "C1,DFLACON,DFLDCON,C2,DFLACON,DFLDCON,C3,DFLACON,DFLDCON;QHS,"


def build_session_options_command() -> str:
    return "VASBAT0,T01AE:C0V0,parallel1,HEARTBEAT7,"


def build_ldlg_command(display_mode: str = "01") -> str:
    return "ldlg{mode},".format(mode=display_mode)


def build_timing_source_command() -> str:
    return "irigb0,iwfs0,"


def build_post_qry_setup_command() -> str:
    return "td2,t01m,t01cal,t01HD,TR,"


def build_curve_timer_setup() -> str:
    return "td2,t01m,t01cal,t01HD,TR,"


def build_wait_for_any_binary_input_command(mask: str = "XXXXXXXXX1") -> str:
    return "WANY{mask},".format(mask=mask)


def build_trigger_latch_command() -> str:
    return "TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,"


def build_trigger_stop_command() -> str:
    return "TSOSTO,"


def build_master_output_off_command() -> str:
    return "V0,OF,C0,OF,"


def build_qhs_flush_command() -> str:
    return ";"


def build_simulated_trip_command() -> str:
    return "XQ;"


def build_all_off_vector_command() -> str:
    return "V0C0,a0;"


def build_channel_standby_command() -> str:
    return "C0,off,V0,off;"


def build_channel_select_reset_command() -> str:
    return "V1,S,V2,S,V3,S,V4,S,C1,S,C2,S,C3,S;"


def build_current_bootstrap_sequence() -> list[str]:
    return [
        build_reset_command(),
        build_qhs_command(),
        build_reconfigure_command(),
        build_runtime_timer_setup_command(),
        build_trip_arm_setup_command(),
        build_open_circuit_alarm_command(),
        build_scaling_setup_command(),
        build_voltage_feedback_setup_command(),
        build_current_feedback_setup_command(),
        build_session_options_command(),
        build_ldlg_command(),
        build_timing_source_command(),
        build_qrymax_command(),
        build_qry_command(),
        build_post_qry_setup_command(),
        build_qg_runtime_command(),
    ]


def build_current_cleanup_sequence() -> list[str]:
    return [
        build_reset_command(),
        build_all_off_vector_command(),
        build_qhs_command(),
        build_channel_standby_command(),
        build_channel_select_reset_command(),
    ]


def build_curve_phase_init_command(
    phase: str,
    amplitude: float,
    *,
    frequency_hz: float = SMRT46_DEFAULT_FREQUENCY_HZ,
) -> str:
    normalized_phase = phase.strip().upper()
    if normalized_phase not in SMRT46_PHASE_CHANNEL_MAP:
        raise ValueError(f"Unsupported SMRT46 curve phase: {phase!r}.")
    if amplitude < 0.0:
        raise ValueError("SMRT46 curve amplitude cannot be negative.")
    active_channel, _ = SMRT46_PHASE_CHANNEL_MAP[normalized_phase]
    parts = [
        "v1,off,",
        "v2,p120.000,off,",
        "v3,p240.000,off,",
        "v4,off,",
    ]
    for channel_index, phase_deg in enumerate(SMRT46_DEFAULT_CURRENT_PHASES, start=1):
        channel_amplitude = amplitude if channel_index == active_channel else 0.0
        parts.append(
            ("c{channel},a{amplitude:.4f},d0,p{phase:.3f},f{frequency:.3f},on,").format(
                channel=channel_index,
                amplitude=channel_amplitude,
                phase=phase_deg,
                frequency=frequency_hz,
            )
        )
    parts.append("BO010,BO020,BO030,BO040,BO050,BO060;")
    return "".join(parts)


def build_curve_channel_init_command(
    channel: int,
    *,
    amplitude: float = 0.0,
    frequency_hz: float = SMRT46_DEFAULT_FREQUENCY_HZ,
) -> str:
    if channel < 1 or channel > 3:
        raise ValueError(f"Unsupported SMRT46 current channel: {channel!r}.")
    if amplitude < 0.0:
        raise ValueError("SMRT46 curve amplitude cannot be negative.")
    phase_deg = SMRT46_DEFAULT_CURRENT_PHASES[channel - 1]
    return ("c{channel},a{amplitude:.4f},d0,p{phase:.3f},f{frequency:.3f},on,").format(
        channel=channel,
        amplitude=amplitude,
        phase=phase_deg,
        frequency=frequency_hz,
    )


def build_curve_amplitude_step(channel: int, amplitude: float) -> str:
    if channel < 1 or channel > 3:
        raise ValueError(f"Unsupported SMRT46 current channel: {channel!r}.")
    if amplitude < 0.0:
        raise ValueError("SMRT46 curve amplitude cannot be negative.")
    return "c{channel},a{amplitude:.4f},d0,".format(
        channel=channel,
        amplitude=amplitude,
    )


def build_current_output_vector_command(
    currents: Sequence[Optional[float]],
    *,
    phases_deg: Sequence[float] = SMRT46_DEFAULT_CURRENT_PHASES,
    frequency_hz: float = SMRT46_DEFAULT_FREQUENCY_HZ,
    voltage_phases_deg: Sequence[float] = SMRT46_DEFAULT_VOLTAGE_PHASES,
) -> str:
    if len(currents) != 3:
        raise ValueError("SMRT46 current vector requires exactly 3 current channel entries.")
    if len(phases_deg) != 3:
        raise ValueError("SMRT46 current phase scaffold requires exactly 3 entries.")
    if len(voltage_phases_deg) != 3:
        raise ValueError("SMRT46 voltage phase scaffold requires exactly 3 entries.")

    parts = [
        "v1,off,",
        "v2,p{phase:.3f},off,".format(phase=voltage_phases_deg[1]),
        "v3,p{phase:.3f},off,".format(phase=voltage_phases_deg[2]),
        "v4,off,",
    ]
    for index, current in enumerate(currents, start=1):
        phase = phases_deg[index - 1]
        parts.append(_build_current_channel_fragment(index, current, phase, frequency_hz))
    parts.append(build_trigger_latch_command())
    return "".join(parts)


def build_current_injection_sequence(
    currents: Sequence[Optional[float]],
    *,
    phases_deg: Sequence[float] = SMRT46_DEFAULT_CURRENT_PHASES,
    frequency_hz: float = SMRT46_DEFAULT_FREQUENCY_HZ,
    voltage_phases_deg: Sequence[float] = SMRT46_DEFAULT_VOLTAGE_PHASES,
    binary_wait_mask: str = "XXXXXXXXX1",
) -> list[str]:
    return [
        build_current_output_vector_command(
            currents,
            phases_deg=phases_deg,
            frequency_hz=frequency_hz,
            voltage_phases_deg=voltage_phases_deg,
        ),
        build_wait_for_any_binary_input_command(binary_wait_mask),
        build_trigger_stop_command(),
        build_master_output_off_command(),
        build_qhs_command(),
        build_qhs_flush_command(),
    ]


def build_voltage_output_vector_command(
    voltages: Sequence[Optional[float]],
    *,
    phases_deg: Sequence[float] = SMRT46_DEFAULT_VOLTAGE_OUTPUT_PHASES,
    frequency_hz: float = SMRT46_DEFAULT_FREQUENCY_HZ,
    current_phases_deg: Sequence[float] = SMRT46_DEFAULT_CURRENT_PHASES,
) -> str:
    if len(voltages) != 4:
        raise ValueError("SMRT46 voltage vector requires exactly 4 voltage channel entries.")
    if len(phases_deg) != 4:
        raise ValueError("SMRT46 voltage phase scaffold requires exactly 4 entries.")
    if len(current_phases_deg) != 3:
        raise ValueError("SMRT46 current phase scaffold requires exactly 3 entries.")

    parts: list[str] = []
    for index, voltage in enumerate(voltages, start=1):
        phase = phases_deg[index - 1]
        parts.append(_build_voltage_channel_fragment(index, voltage, phase, frequency_hz))
    for index, phase in enumerate(current_phases_deg, start=1):
        parts.append(
            "c{channel},a0.0000,d0,p{phase:.3f},f{frequency:.3f},off,".format(
                channel=index,
                phase=phase,
                frequency=frequency_hz,
            )
        )
    parts.append(build_trigger_latch_command())
    return "".join(parts)


def build_voltage_injection_sequence(
    voltages: Sequence[Optional[float]],
    *,
    phases_deg: Sequence[float] = SMRT46_DEFAULT_VOLTAGE_OUTPUT_PHASES,
    frequency_hz: float = SMRT46_DEFAULT_FREQUENCY_HZ,
    binary_wait_mask: str = "XXXXXXXXX1",
) -> list[str]:
    return [
        build_voltage_output_vector_command(
            voltages,
            phases_deg=phases_deg,
            frequency_hz=frequency_hz,
        ),
        build_wait_for_any_binary_input_command(binary_wait_mask),
        build_trigger_stop_command(),
        build_master_output_off_command(),
        build_qhs_command(),
        build_qhs_flush_command(),
    ]


def _build_current_channel_fragment(
    channel_index: int,
    current: Optional[float],
    phase_deg: float,
    frequency_hz: float,
) -> str:
    if current is None:
        return "c{channel},p{phase:.3f},off,".format(channel=channel_index, phase=phase_deg)
    if current < 0:
        raise ValueError("SMRT46 current amplitude cannot be negative.")
    if current == 0.0:
        return "c{channel},a0.0000,d0,p{phase:.3f},off,".format(
            channel=channel_index,
            phase=phase_deg,
        )
    return "c{channel},a{amplitude:.4f},d0,p{phase:.3f},f{frequency:.3f},on,".format(
        channel=channel_index,
        amplitude=current,
        phase=phase_deg,
        frequency=frequency_hz,
    )


def _build_voltage_channel_fragment(
    channel_index: int,
    voltage: Optional[float],
    phase_deg: float,
    frequency_hz: float,
) -> str:
    if voltage is None:
        return ("v{channel},a0.0000,d0,p{phase:.3f},f{frequency:.3f},off,").format(
            channel=channel_index,
            phase=phase_deg,
            frequency=frequency_hz,
        )
    if voltage < 0:
        raise ValueError("SMRT46 voltage amplitude cannot be negative.")
    state = "on" if voltage > 0.0 else "off"
    return ("v{channel},a{amplitude:.4f},d0,p{phase:.3f},f{frequency:.3f},{state},").format(
        channel=channel_index,
        amplitude=voltage,
        phase=phase_deg,
        frequency=frequency_hz,
        state=state,
    )
