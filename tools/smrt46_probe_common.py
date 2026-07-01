from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smrt46_client import (
    Smrt46Client,
    Smrt46ConnectionError,
    Smrt46Error,
    Smrt46SessionBusyError,
    Smrt46TimeoutError,
)
from smrt46_client.logging_utils import setup_logging
from smrt46_client.tooling import add_smrt46_arguments, resolve_smrt46_tool_settings


def add_common_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    return add_smrt46_arguments(parser)


def resolve_probe_settings(args: argparse.Namespace) -> dict[str, Any]:
    settings = resolve_smrt46_tool_settings(args)
    return {
        "target": settings.target,
        "config_file": settings.config_file,
        "host": settings.host,
        "port": settings.port,
        "connect_timeout": settings.connect_timeout,
        "timeout": settings.command_timeout,
        "poll_interval": settings.poll_interval,
        "discovery_udp_port": settings.discovery_udp_port,
        "logger": setup_logging(verbose=settings.verbose, log_file=settings.log_file),
        "session_log": settings.session_log,
    }


def run_probe(
    *,
    settings: dict[str, Any],
    operation_name: str,
    operation,
) -> int:
    retry_delays_s = (0.5, 1.0, 2.0)
    attempts = 1 + len(retry_delays_s)
    init_result: dict[str, Any] = {}
    payload: Any = None
    last_retryable_error: Optional[Smrt46Error] = None
    for attempt_index in range(attempts):
        if attempt_index > 0:
            time.sleep(retry_delays_s[attempt_index - 1])
        try:
            with Smrt46Client(
                settings["host"],
                settings["port"],
                connect_timeout=settings["connect_timeout"],
                command_timeout=settings["timeout"],
                read_idle_gap=settings["poll_interval"],
                logger=settings["logger"],
                session_log_path=settings["session_log"],
            ) as client:
                init_result = client.initialize_ethernet_session()
                payload = operation(client, init_result)
            last_retryable_error = None
            break
        except (Smrt46SessionBusyError, Smrt46TimeoutError, Smrt46ConnectionError) as exc:
            last_retryable_error = exc
            continue
        except Smrt46Error as exc:
            return _print_generic_error(exc, attempts=attempt_index + 1)
    if last_retryable_error is not None:
        if isinstance(last_retryable_error, Smrt46SessionBusyError):
            return _print_session_busy_error(last_retryable_error, attempts=attempts)
        return _print_generic_error(last_retryable_error, attempts=attempts)

    print(
        json.dumps(
            {
                "ok": True,
                "operation": operation_name,
                "target": settings["target"],
                "config_file": settings["config_file"],
                "host": settings["host"],
                "port": settings["port"],
                "discovery_udp_port": settings["discovery_udp_port"],
                "initialize": {
                    "idle_before": cast(Any, init_result["idle_before"]).to_dict(),
                    "config": cast(Any, init_result["config"]).to_dict(),
                    "idle_after": cast(Any, init_result["idle_after"]).to_dict(),
                    "startup": cast(Any, init_result["startup"]).to_dict(),
                },
                "result": payload,
            },
            indent=2,
        )
    )
    return 0


def _print_session_busy_error(exc: Smrt46SessionBusyError, *, attempts: int) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "attempts": attempts,
                "hint": (
                    "The SMRT46 refused a new TCP client. Another tool is likely connected, "
                    "for example PowerDB. Close the previous client or reset the SMRT46 "
                    "session, then retry."
                ),
            },
            indent=2,
        )
    )
    return 2


def _print_generic_error(exc: Smrt46Error, *, attempts: int) -> int:
    print(
        json.dumps(
            {
                "ok": False,
                "error": str(exc),
                "attempts": attempts,
            },
            indent=2,
        )
    )
    return 1
