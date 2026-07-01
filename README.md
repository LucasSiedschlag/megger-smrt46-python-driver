
# Megger SMRT46 Python Driver

Standalone Python communication driver for Megger SMRT46 relay test set automation.

This repository contains the SMRT46 TCP client, protocol builders/parsers, command-line tools, unit tests, and bench reference logs. It is intended for engineers who need a small Python library for SMRT46 Ethernet control without the larger automation application around it.

SEO keywords: Megger SMRT46 Python driver, SMRT46 automation, Megger relay test set Python, SMRT46 TCP protocol, SMRT46 current injection, SMRT46 voltage injection.

## Install for development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .[dev]
```

Python 3.9+ is supported. The operational baseline is Python 3.9.9.

## Configuration

Create a local config from the example:

```bash
cp config/smrt46_hosts.example.ini config/smrt46_hosts.ini
```

Default section:

```ini
[smrt46.default]
host = 192.168.0.20
port = 8000
connect_timeout = 3.0
command_timeout = 2.0
poll_interval = 0.05
discovery_udp_port = 8001
log_file =
session_log =
```

## Quick commands

Connection probe:

```bash
python3 -m tools.smrt46_connection_probe --target default --verbose
```

Current injection with expected trip/alarm:

```bash
python3 -m tools.smrt46_run_current_injection \
  --target default \
  --current 1:3.0:0 \
  --frequency 60 \
  --poll-count 1 \
  --only-current-time
```

For a fixed-duration current probe with no expected trip, use the Python API pattern in `docs/SMRT46_CLIENT_GUIDE.md`: `configure_current_outputs()` in a `try` block and `stop_outputs()` in `finally`.

Voltage injection:

```bash
python3 -m tools.smrt46_run_voltage_test \
  --target default \
  --voltage 2:50.0:120 \
  --stop-mode binary_input \
  --target-bin 1
```

Curve test:

```bash
python3 -m tools.smrt46_run_curve_test \
  --target default \
  --phase A \
  --start 4.0 \
  --stop 4.2 \
  --step 0.1 \
  --only-current-time
```

## Python API

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

## Development workflow

```bash
make test
make lint
make typecheck
make check
make build
```

Use `make help` to list targets.

## Repository contents

- `smrt46_client/` — TCP client, protocol builders, parsers, models, exceptions, and config tooling.
- `tools/` — CLI tools for connection probe, current output configuration, current injection, voltage injection, and curve tests.
- `tests/` — unit tests for parser/protocol/client/tool behavior.
- `docs/` — SMRT46 implementation notes, test plans, and bench logs.
- `config/` — example host configuration.

## Operational notes

- The SMRT46 usually accepts one TCP client at a time. Close PowerDB or other software sessions before using these tools.
- `session_log` writes JSONL TX/RX timing records when configured.
- The tools always try to stop outputs and clean up after injection operations.
