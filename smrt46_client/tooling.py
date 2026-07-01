from __future__ import annotations

import argparse
import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class Smrt46ToolSettings:
    host: str
    port: int
    connect_timeout: float
    command_timeout: float
    poll_interval: float
    verbose: bool
    discovery_udp_port: int
    target: str = "default"
    config_file: str = "config/smrt46_hosts.ini"
    log_file: Optional[str] = None
    session_log: Optional[str] = None


def load_ini_section(path: str, section: str) -> Dict[str, str]:
    config_path = Path(path)
    if not config_path.is_absolute() and not config_path.exists():
        # Keep default relative paths stable even when tools are launched
        # from outside the repository root.
        repo_relative = Path(__file__).resolve().parents[1] / config_path
        if repo_relative.exists():
            config_path = repo_relative
    if not config_path.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if not parser.has_section(section):
        return {}
    return {key: value for key, value in parser.items(section)}


def add_smrt46_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--config-file",
        default="config/smrt46_hosts.ini",
        help="INI file with named SMRT46 targets such as [smrt46.default].",
    )
    parser.add_argument(
        "--target",
        default="default",
        help="Target name loaded from [smrt46.<target>] in --config-file.",
    )
    parser.add_argument("--host", help="Override the SMRT46 host or IP for this run.")
    parser.add_argument("--port", type=int, help="Override the SMRT46 TCP port for this run.")
    parser.add_argument("--connect-timeout", type=float, help="Override the TCP connect timeout.")
    parser.add_argument("--timeout", type=float, help="Override the SMRT46 command timeout.")
    parser.add_argument("--poll-interval", type=float, help="Override the SMRT46 poll interval.")
    parser.add_argument("--log-file", help="Write human-readable logs to this file.")
    parser.add_argument("--session-log", help="Write raw session JSONL to this file.")
    parser.add_argument("--verbose", action="store_true")
    return parser


def resolve_smrt46_tool_settings(args: argparse.Namespace) -> Smrt46ToolSettings:
    config = load_ini_section(args.config_file, f"smrt46.{args.target}")

    host = args.host or config.get("host")
    if not host:
        raise SystemExit(
            "SMRT46 host is required. Use --host, set host in "
            f"[smrt46.{args.target}] inside {args.config_file}."
        )

    return Smrt46ToolSettings(
        host=host,
        port=args.port if args.port is not None else int(config.get("port", "8000")),
        connect_timeout=(
            args.connect_timeout
            if args.connect_timeout is not None
            else float(config.get("connect_timeout", "3.0"))
        ),
        command_timeout=args.timeout
        if args.timeout is not None
        else float(config.get("command_timeout", "2.0")),
        poll_interval=(
            args.poll_interval
            if args.poll_interval is not None
            else float(config.get("poll_interval", "0.05"))
        ),
        verbose=args.verbose,
        discovery_udp_port=int(config.get("discovery_udp_port", "8001")),
        target=args.target,
        config_file=args.config_file,
        log_file=args.log_file or _optional_env_value(config.get("log_file")),
        session_log=args.session_log or _optional_env_value(config.get("session_log")),
    )


def _optional_env_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
