from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.smrt46_connection_probe import main
from tools.smrt46_tool_helpers import Smrt46ToolError

from tests.fake_tool_response import FakeToolResponse


class Smrt46ConnectionProbeToolTests(unittest.TestCase):
    def test_direct_script_execution_supports_help(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "tools" / "smrt46_connection_probe.py"
        process = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, msg=process.stderr)
        self.assertIn("SMRT46 Ethernet connection probe", process.stdout)

    def test_main_runs_direct_probe_and_prints_json(self) -> None:
        output = io.StringIO()
        with patch("sys.argv", ["smrt46_connection_probe.py", "--host", "192.168.0.20"]):
            with patch(
                "tools.smrt46_connection_probe.connection_probe",
                return_value=FakeToolResponse(result={"operation": "connection_probe"}),
            ) as probe:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(probe.call_args.kwargs["logger"].name, "smrt46")
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["operation"], "connection_probe")
        self.assertEqual(payload["result"]["result"]["operation"], "connection_probe")

    def test_main_returns_error_payload_when_probe_fails(self) -> None:
        output = io.StringIO()
        with patch("sys.argv", ["smrt46_connection_probe.py", "--host", "192.168.0.20"]):
            with patch(
                "tools.smrt46_connection_probe.connection_probe",
                side_effect=Smrt46ToolError("probe failed"),
            ):
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("probe failed", payload["error"])


if __name__ == "__main__":
    unittest.main()
