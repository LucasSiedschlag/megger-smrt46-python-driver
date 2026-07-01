from __future__ import annotations

import ipaddress
from typing import Any, Dict, List, Sequence, Tuple

from .exceptions import Smrt46ProtocolError
from .models import (
    Smrt46AlarmSet,
    Smrt46GateState,
    Smrt46IpConfig,
    Smrt46MaxLimits,
    Smrt46MeasuredCurrent,
    Smrt46MeasuredVoltage,
    Smrt46StatusSnapshot,
    Smrt46VersionComponent,
    Smrt46VersionInfo,
)


def clean_response(raw: str) -> str:
    """Normalize raw ASCII payloads from SMRT46."""

    cleaned = raw.replace("\r", "").strip().rstrip(";").strip()
    # Some benches emit colon-only placeholders (":" / "::::") between frames.
    # Treat them as empty noise so callers can keep polling for a valid payload.
    if cleaned and set(cleaned) == {":"}:
        return ""
    return cleaned


def parse_alarm_response(raw: str) -> Smrt46AlarmSet:
    cleaned = clean_response(raw)
    if not cleaned:
        return Smrt46AlarmSet(raw=cleaned, alarms=[])
    alarms = []
    for part in cleaned.split("|"):
        message = part.strip()
        if not message:
            continue
        marker_index = message.upper().find("ERROR:")
        if marker_index >= 0:
            message = message[marker_index + len("ERROR:") :].strip()
        alarms.append(message)
    return Smrt46AlarmSet(raw=cleaned, alarms=alarms)


def parse_qg_response(raw: str) -> Smrt46GateState:
    cleaned = clean_response(raw)
    if cleaned.startswith("GATE"):
        return Smrt46GateState(raw=cleaned, mask=cleaned[len("GATE") :])
    raise Smrt46ProtocolError(f"Unexpected QG response: {raw!r}")


def parse_qrymax_response(raw: str) -> Smrt46MaxLimits:
    cleaned = clean_response(raw)
    tokens = _split_tokens(cleaned)
    if len(tokens) != 13 or tokens[0] != "V" or tokens[5] != "I" or tokens[9] != "conti":
        raise Smrt46ProtocolError(f"Unexpected QRYMAX response: {raw!r}")
    return Smrt46MaxLimits(
        raw=cleaned,
        voltage_limits=[_to_float(token) for token in tokens[1:5]],
        current_limits=[_to_float(token) for token in tokens[6:9]],
        continuous_current_limits=[_to_float(token) for token in tokens[10:13]],
    )


def parse_qip_response(raw: str) -> Smrt46IpConfig:
    cleaned = clean_response(raw)
    tokens = _split_tokens(cleaned)
    if not tokens:
        raise Smrt46ProtocolError(f"Unexpected QIP response: {raw!r}")
    try:
        ipaddress.ip_address(tokens[0])
    except ValueError as exc:
        raise Smrt46ProtocolError(f"Unexpected QIP response: {raw!r}") from exc
    return Smrt46IpConfig(
        raw=cleaned,
        ip_address=tokens[0],
        mode=tokens[1] if len(tokens) > 1 else None,
        extra_fields=tokens[2:],
    )


def parse_qver_response(raw: str) -> Smrt46VersionInfo:
    cleaned = clean_response(raw)
    records = _split_records(cleaned)
    if not records:
        raise Smrt46ProtocolError(f"Unexpected QVER response: {raw!r}")
    components = [_parse_version_component(record, raw=raw) for record in records]
    return Smrt46VersionInfo(raw=cleaned, components=components)


def parse_qryall_response(raw: str) -> Smrt46StatusSnapshot:
    cleaned = clean_response(raw)
    tokens = _split_tokens(cleaned)
    if not tokens or tokens[0] != "V":
        raise Smrt46ProtocolError(f"Unexpected QRYALL response: {raw!r}")

    index = 1
    voltages, index = _parse_measurement_block(tokens, index, 4, is_current=False)
    if index >= len(tokens) or tokens[index] != "I":
        raise Smrt46ProtocolError(f"Missing current block in QRYALL response: {raw!r}")
    currents, index = _parse_measurement_block(tokens, index + 1, 3, is_current=True)

    if index + 7 > len(tokens):
        raise Smrt46ProtocolError(f"QRYALL response ended before runtime fields: {raw!r}")
    if tokens[index] != "BI" or tokens[index + 2] != "BO" or tokens[index + 4] != "EV":
        raise Smrt46ProtocolError(f"Unexpected BI/BO/EV segment in QRYALL response: {raw!r}")

    binary_inputs = tokens[index + 1]
    binary_outputs = tokens[index + 3]
    event_count = _to_int(tokens[index + 5])
    index += 6

    if index + 2 > len(tokens) or tokens[index] != "T":
        raise Smrt46ProtocolError(f"Missing elapsed time in QRYALL response: {raw!r}")
    elapsed_time_s = _to_float(tokens[index + 1])
    index += 2

    timer_values: Dict[str, float] = {}
    while index + 1 < len(tokens) and tokens[index].startswith("T") and tokens[index][1:].isdigit():
        timer_values[tokens[index]] = _to_float(tokens[index + 1])
        index += 2

    metadata = _parse_metadata(tokens[index:])
    return Smrt46StatusSnapshot(
        raw=cleaned,
        voltages=voltages,
        currents=currents,
        binary_inputs=binary_inputs,
        binary_outputs=binary_outputs,
        event_count=event_count,
        elapsed_time_s=elapsed_time_s,
        timer_values=timer_values,
        metadata=metadata,
    )


def parse_binary_inputs(qryall_response: str) -> str:
    return parse_qryall_response(qryall_response).binary_inputs


def is_binary_input_closed(bi_field: str, input_number: int) -> bool:
    if input_number < 1:
        raise ValueError("SMRT46 binary input index starts at 1.")
    if input_number > len(bi_field):
        raise ValueError(
            "SMRT46 binary input index out of range: "
            f"input={input_number}, available={len(bi_field)}."
        )
    idx = len(bi_field) - input_number
    return bi_field[idx] == "1"


def has_deviation_alarm(raw_response: str) -> bool:
    cleaned = clean_response(raw_response).lower()
    return "error:" in cleaned and "deviation alarm" in cleaned


def _split_tokens(cleaned: str) -> List[str]:
    if not cleaned:
        return []
    return [token.strip() for token in cleaned.split(",") if token.strip()]


def _split_records(cleaned: str) -> List[str]:
    if not cleaned:
        return []
    return [record.strip() for record in cleaned.split(";") if record.strip()]


def _parse_version_component(record: str, *, raw: str) -> Smrt46VersionComponent:
    tokens = _split_tokens(record)
    if not tokens or ":" not in tokens[0]:
        raise Smrt46ProtocolError(f"Unexpected QVER response: {raw!r}")
    name, firmware_version = tokens[0].split(":", 1)
    if not name or not firmware_version:
        raise Smrt46ProtocolError(f"Unexpected QVER response: {raw!r}")
    metadata: Dict[str, str] = {}
    for token in tokens[1:]:
        if ":" not in token:
            metadata[token] = ""
            continue
        key, value = token.split(":", 1)
        metadata[key] = value
    return Smrt46VersionComponent(
        name=name,
        firmware_version=firmware_version,
        cpld=metadata.pop("CPLD", None),
        boot=metadata.pop("Boot", None),
        metadata=metadata,
    )


def _parse_measurement_block(
    tokens: Sequence[str],
    start_index: int,
    count: int,
    *,
    is_current: bool,
) -> Tuple[List[Any], int]:
    values: List[Any] = []
    index = start_index
    for channel in range(1, count + 1):
        if index + 5 >= len(tokens):
            raise Smrt46ProtocolError("SMRT46 measurement block is incomplete.")
        enabled_flag = _to_int(tokens[index])
        state_code = _to_int(tokens[index + 1])
        amplitude = _to_float(tokens[index + 2])
        deviation = _to_float(tokens[index + 3])
        phase_deg = _to_float(tokens[index + 4])
        frequency_hz = _to_float(tokens[index + 5])
        if is_current:
            values.append(
                Smrt46MeasuredCurrent(
                    channel=channel,
                    enabled=bool(enabled_flag),
                    state_code=state_code,
                    source_code=state_code,
                    amplitude=amplitude,
                    deviation=deviation,
                    phase_deg=phase_deg,
                    frequency_hz=frequency_hz,
                )
            )
        else:
            values.append(
                Smrt46MeasuredVoltage(
                    channel=channel,
                    enabled=bool(enabled_flag),
                    state_code=state_code,
                    source_code=state_code,
                    amplitude=amplitude,
                    deviation=deviation,
                    phase_deg=phase_deg,
                    frequency_hz=frequency_hz,
                )
            )
        index += 6
    return values, index


def _parse_metadata(tokens: Sequence[str]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    index = 0
    while index < len(tokens):
        key = tokens[index]
        if index + 1 >= len(tokens):
            metadata[key] = None
            break
        value = tokens[index + 1]
        metadata[key] = _coerce_scalar(value)
        index += 2
    return metadata


def _coerce_scalar(value: str) -> Any:
    try:
        return _to_int(value)
    except ValueError:
        pass
    try:
        return _to_float(value)
    except ValueError:
        return value


def _to_float(value: str) -> float:
    return float(value)


def _to_int(value: str) -> int:
    return int(value)
