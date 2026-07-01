
# SMRT46 Client Guide

This package exposes the SMRT46 TCP client directly through `smrt46_client`.

The public API is intentionally small:

- `Smrt46Client` manages the TCP session.
- Request dataclasses describe current, voltage, and curve operations.
- Result/status dataclasses expose `.to_dict()` for JSON logging.
- `Smrt46Error` subclasses give stable failure categories.

## Basic connection and status

```python
from smrt46_client import Smrt46Client

with Smrt46Client("192.168.0.20", 8000) as client:
    status = client.query_all()
    print(status.to_dict())
```

Useful read-only calls:

- `query_all()` returns typed voltage/current/binary-input status.
- `query_gate_state()` returns the `QG` gate mask.
- `query_max_limits()` returns voltage/current limits.
- `qip()` and `qver()` return typed IP/version information.
- `raw(command)` sends a command and returns an unparsed response.

## Safe bounded current probe

Use this pattern when you want current output for a fixed time and do not expect a trip.

```python
import time

from smrt46_client import (
    Smrt46Client,
    Smrt46CurrentChannelConfig,
    Smrt46CurrentInjectionRequest,
)

request = Smrt46CurrentInjectionRequest(
    currents=[
        Smrt46CurrentChannelConfig(channel=1, amplitude=10.0, phase_deg=0.0),
        Smrt46CurrentChannelConfig(channel=2, amplitude=20.0, phase_deg=120.0),
        Smrt46CurrentChannelConfig(channel=3, amplitude=30.0, phase_deg=240.0),
    ],
    frequency_hz=60.0,
)

with Smrt46Client("192.168.0.20", 8000) as client:
    try:
        client.configure_current_outputs(request)
        time.sleep(0.5)
        snapshot = client.query_all()
        print(snapshot.to_dict())
    finally:
        client.stop_outputs()
```

Bench result shape confirmed with current probes connected:

- C1 requested `10 A`, measured about `9.9997 A`.
- C2 requested `20 A`, measured about `20.0023 A`.
- C3 requested `30 A`, measured about `30.0028 A`.
- Cleanup returned all current and voltage outputs to zero.

## Trip-oriented current injection

`run_current_injection()` is for tests that should stop on trip/alarm. It is not a fixed-duration current pulse.

```python
from smrt46_client import (
    Smrt46Client,
    Smrt46CurrentChannelConfig,
    Smrt46CurrentInjectionRequest,
)

request = Smrt46CurrentInjectionRequest(
    currents=[Smrt46CurrentChannelConfig(channel=1, amplitude=3.0, phase_deg=0.0)],
    frequency_hz=60.0,
)

with Smrt46Client("192.168.0.20", 8000) as client:
    result = client.run_current_injection(request, poll_count=1)
    print(result.to_dict())
```

Use `configure_current_outputs()` plus `stop_outputs()` instead when there is no expected trip.

## Curve test

Curve tests ramp current and stop on one of these conditions:

- target binary input closes;
- current collapses after being observed;
- timer/recloser signal indicates trip;
- ramp reaches the stop current.

```python
from smrt46_client import Smrt46Client, Smrt46CurveTestConfig

config = Smrt46CurveTestConfig(
    phases=["A"],
    start_current_a=10.0,
    stop_current_a=30.0,
    step_size_a=0.2,
    step_delay_ms=150,
    qg_interval=1,
    trip_confirm_polls=2,
    target_bin=1,
)

with Smrt46Client("192.168.0.20", 8000) as client:
    result = client.run_curve_injection(config)
    print(result.to_dict())
```

Bench-confirmed behavior:

- no binary input: ramp stopped by current-collapse/recloser detection around `20.6 A`;
- BI1 activated during ramp: stopped as binary-input trip at `13.0 A`.

## Voltage injection

Run voltage tests only when the voltage outputs are connected to a safe load/test circuit.

```python
from smrt46_client import (
    Smrt46Client,
    Smrt46VoltageChannelConfig,
    Smrt46VoltageInjectionRequest,
)

request = Smrt46VoltageInjectionRequest(
    voltages=[Smrt46VoltageChannelConfig(channel=2, amplitude=50.0, phase_deg=120.0)],
    frequency_hz=60.0,
    stop_mode="binary_input",
    target_bin=1,
)

with Smrt46Client("192.168.0.20", 8000) as client:
    result = client.run_voltage_injection(request)
    print(result.to_dict())
```

## CLI tools

All tools read `config/smrt46_hosts.ini` by default and accept `--host`, `--port`, `--timeout`, `--session-log`, and `--verbose` overrides.

Read-only connection probe:

```bash
python3 -m tools.smrt46_connection_probe --target default --verbose
```

Trip-oriented current injection:

```bash
python3 -m tools.smrt46_run_current_injection \
  --target default \
  --current 1:3.0:0 \
  --only-current-time
```

Curve test:

```bash
python3 -m tools.smrt46_run_curve_test \
  --target default \
  --phase A \
  --start 10 \
  --stop 30 \
  --step 0.2 \
  --step-delay-ms 150 \
  --qg-interval 1 \
  --target-bin 1 \
  --only-current-time
```

Voltage test:

```bash
python3 -m tools.smrt46_run_voltage_test \
  --target default \
  --voltage 2:50.0:120 \
  --stop-mode binary_input \
  --target-bin 1
```
