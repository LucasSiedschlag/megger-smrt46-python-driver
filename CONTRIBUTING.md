
# Contributing

Keep changes small, tested, and compatible with Python 3.9.9.

Before opening a pull request:

```bash
make check
make build
```

For protocol or parser changes, add tests that cover command framing, parsing, or runtime flow. Do not overwrite bench evidence under `docs/`.
