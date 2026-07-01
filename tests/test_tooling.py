from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from pathlib import Path

from smrt46_client.tooling import add_smrt46_arguments, resolve_smrt46_tool_settings


class Smrt46ToolingTests(unittest.TestCase):
    def test_resolve_smrt46_tool_settings_reads_ini_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "smrt46_hosts.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[smrt46.default]",
                        "host = 192.168.0.20",
                        "discovery_udp_port = 8001",
                        "port = 9001",
                        "connect_timeout = 4.0",
                        "command_timeout = 6.5",
                        "poll_interval = 0.2",
                        "log_file = logs/smrt46.log",
                        "session_log = logs/smrt46-session.jsonl",
                    ]
                ),
                encoding="utf-8",
            )
            parser = add_smrt46_arguments(argparse.ArgumentParser())
            args = parser.parse_args(["--config-file", str(config_path)])
            settings = resolve_smrt46_tool_settings(args)

        self.assertEqual(settings.host, "192.168.0.20")
        self.assertEqual(settings.discovery_udp_port, 8001)
        self.assertEqual(settings.port, 9001)
        self.assertEqual(settings.connect_timeout, 4.0)
        self.assertEqual(settings.command_timeout, 6.5)
        self.assertEqual(settings.poll_interval, 0.2)
        self.assertEqual(settings.log_file, "logs/smrt46.log")
        self.assertEqual(settings.session_log, "logs/smrt46-session.jsonl")

    def test_smrt46_cli_arguments_override_ini_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "smrt46_hosts.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[smrt46.default]",
                        "host = 192.168.0.20",
                        "port = 8000",
                    ]
                ),
                encoding="utf-8",
            )
            parser = add_smrt46_arguments(argparse.ArgumentParser())
            args = parser.parse_args(
                [
                    "--config-file",
                    str(config_path),
                    "--host",
                    "10.0.0.20",
                    "--port",
                    "9100",
                    "--connect-timeout",
                    "5.0",
                    "--timeout",
                    "7.0",
                    "--poll-interval",
                    "0.1",
                    "--session-log",
                    "smrt46-session.jsonl",
                ]
            )
            settings = resolve_smrt46_tool_settings(args)

        self.assertEqual(settings.host, "10.0.0.20")
        self.assertEqual(settings.port, 9100)
        self.assertEqual(settings.connect_timeout, 5.0)
        self.assertEqual(settings.command_timeout, 7.0)
        self.assertEqual(settings.poll_interval, 0.1)
        self.assertEqual(settings.session_log, "smrt46-session.jsonl")

    def test_smrt46_requires_cli_or_ini_host(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = add_smrt46_arguments(argparse.ArgumentParser())
            args = parser.parse_args(["--config-file", str(Path(temp_dir) / "missing.ini")])
            with self.assertRaises(SystemExit) as ctx:
                resolve_smrt46_tool_settings(args)

        self.assertIn("SMRT46 host is required", str(ctx.exception))

    def test_smrt46_resolves_repo_relative_config_outside_repo_cwd(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config_dir = repo_root / "config"
        temp_config = config_dir / "smrt46_hosts.test.ini"
        temp_config.write_text(
            "\n".join(
                [
                    "[smrt46.default]",
                    "host = 10.1.2.3",
                    "port = 8111",
                ]
            ),
            encoding="utf-8",
        )
        parser = add_smrt46_arguments(argparse.ArgumentParser())
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                args = parser.parse_args(["--config-file", "config/smrt46_hosts.test.ini"])
                settings = resolve_smrt46_tool_settings(args)
        finally:
            os.chdir(original_cwd)
            temp_config.unlink(missing_ok=True)

        self.assertEqual(settings.host, "10.1.2.3")
        self.assertEqual(settings.port, 8111)
