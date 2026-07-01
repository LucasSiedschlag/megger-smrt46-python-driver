
# Development Notes

This repository is a standalone SMRT46 Python communication driver.

## Quality gates

```bash
make check
make build
```

Equivalent commands:

```bash
python3 -m unittest discover -s tests -v
python3 -m ruff check smrt46_client tests tools
python3 -m mypy
python3 -m pip wheel --no-deps --no-build-isolation -w dist .
```

## Manual bench checks

Run only with the SMRT46 connected to a safe test circuit and with no other TCP client open.

```bash
python3 -m tools.smrt46_connection_probe --target default --verbose
```

Current injection smoke test:

```bash
python3 -m tools.smrt46_run_current_injection \
  --target default \
  --current 1:3.0:0 \
  --frequency 60 \
  --poll-count 1 \
  --only-current-time
```

Voltage bench shape:

```bash
python3 -m tools.smrt46_run_voltage_test \
  --target default \
  --voltage 2:50.0:120 \
  --stop-mode binary_input \
  --target-bin 1
```

Curve bench shape:

```bash
python3 -m tools.smrt46_run_curve_test \
  --target default \
  --phase A \
  --start 4.0 \
  --stop 4.2 \
  --step 0.1 \
  --only-current-time
```

## Compatibility

Keep Python 3.9.9 compatible syntax and typing. Avoid APIs introduced only in Python 3.10+.
