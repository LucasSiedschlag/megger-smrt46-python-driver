# SMRT46 Communication

This document summarizes the behavior currently implemented in `smrt46_client/client.py`
and in the standalone CLI tools.

## Sources Used

- [`../docs/smrt46_logs/PdbDriverConnection.log`](../docs/smrt46_logs/PdbDriverConnection.log)
- [`../docs/smrt46_logs/PdbDriverManualTest1.log`](../docs/smrt46_logs/PdbDriverManualTest1.log)
- [`../docs/smrt46_logs/PdbDriverCurveABCTest1.log`](../docs/smrt46_logs/PdbDriverCurveABCTest1.log)
- [`../docs/smrt46_logs/PdbDriverTripvsBinaryInput.log`](../docs/smrt46_logs/PdbDriverTripvsBinaryInput.log)
- [`../docs/SMRT_command_set.txt`](../docs/SMRT_command_set.txt)

## Current Scope

`smrt46` support currently includes:

- synchronous TCP connection and ASCII command execution
- typed parsing for `QG`, `QRYMAX`, and `QRYALL`
- manual injection flow (`run_current_injection`)
- sequential per-phase curve flow (`run_curve_injection`)
- session-busy/connection-drop error normalization in the service layer

Some commands remain raw due to limited RX validation (`QC`).

## Transport

- Protocol: synchronous TCP
- Port fallback: `8000`
- Initial connection timeout: `3.0 s`
- Default command timeout: `2.0 s`
- Read path uses `;` framing with idle-gap fallback
- Disconnect sends best-effort `SU;` before TCP shutdown, matching the
  PowerDB session-release command observed in connection traces and the
  current-injection teardown pattern.

Runtime uses `config/smrt46_hosts.ini` with targets named `smrt46.<target>`.

## Discovery Observed in PowerDB

Bench-observed flow:

- UDP autodetection sent to port `8001` with payload `MEGGER`
- TCP session attempt on `:8000`

Example:

```text
Ether Detect(0): Sending UDP @ 8001, MEGGER
**AUTODETECT** 169.254.1.0:8000: Attempting to open socket...
```

The current package does not implement UDP autodetection; it connects directly using the provided host/port.

## Commands Exposed in the Client

Raw-compatible query methods:

- `qcfg()` -> `QC;`
- `qry()` -> `QRYALL;` (compatibility mapping)
- `qip()` -> typed parse of `QIP;`
- `qver()` -> typed parse of `QVER;`
- `raw(command)` -> arbitrary native command

Typed query methods:

- `query_gate_state()` -> typed parse of `QG`
- `query_max_limits()` -> typed parse of `QRYMAX`
- `query_all()` -> typed parse of `QRYALL`
- `qip()` -> typed parse of `QIP`
- `qver()` -> typed parse of `QVER`

High-level flows:

- `run_current_injection(...)`
- `run_curve_injection(...)`

## Implemented Curve Sequence (`run_curve_injection`)

### Bootstrap

1. Session preparation (`_prepare_current_output_session`).
2. Current bootstrap (`build_current_bootstrap_sequence`), including `QRYMAX` and `QRYALL`.
3. Curve current-limit validation against `QRYMAX`.

### Per Phase (A -> B -> C)

1. `RE;` before each phase (default rearm policy with `rearm_before_phase=True`).
2. Timer setup: `td2,t01m,t01cal,t01HD,TR,`.
3. Channel initialization:
   - phase 1 uses full vector init (`build_curve_phase_init_command`)
   - subsequent phases use per-channel init (`build_curve_channel_init_command`)
4. Baseline `QRYALL`:
   - fail if no valid snapshot is returned
   - fail if `target_bin` is already closed (stale latch)
5. Ramp:
   - set amplitude `cN,aX.XXXX,d0,`
   - `qg,` for gate check
   - `;` to apply each step
   - `QRYALL` every `qg_interval` steps (or at ramp end)
6. Stop conditions:
   - `din_closed`: target BIN closed in `QRYALL`
   - `deviation_alarm`: frame containing `ERROR: Deviation alarm`
   - `ramp_exhausted`: reached `stop_current_a` with no event
7. Between phases and on exit: `XU;` + all-off cleanup in `finally` via `stop_outputs()`.

### Result

`Smrt46CurveTestResult` includes:

- per-phase result (`phase`, `channel`, `stop_reason`, final amplitude, alarms)
- `success`/`aborted` and `final_state`
- `raw_payloads`, `history`, `notes`

## Current Framing

Read completion occurs when:

- `;` is found, or
- a short inactivity window occurs after bytes have already been received

This framing is validated for connection probes, current output, curve ramping,
binary-input trips, and current-collapse trips.

## Current Limitations

- `QC` / `qcfg()` remains a raw administrative payload.
- `qry()` remains a raw compatibility method; prefer `query_all()` for typed status.
- UDP autodiscovery is not implemented.
- Voltage injection must be validated separately with safe voltage-output wiring before production use.
