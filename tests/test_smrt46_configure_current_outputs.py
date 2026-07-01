from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.smrt46_configure_current_outputs import main

from tests.fake_tool_response import FakeToolResponse


class Smrt46ConfigureCurrentOutputsToolTests(unittest.TestCase):
    def test_main_runs_direct_configuration_and_prints_json(self) -> None:
        args = [
            "smrt46_configure_current_outputs.py",
            "--host",
            "192.168.0.20",
            "--current",
            "2:5.0:120",
            "--current",
            "1:3.0:0",
            "--frequency",
            "60.0",
        ]
        output = io.StringIO()
        with patch("sys.argv", args):
            with patch(
                "tools.smrt46_configure_current_outputs.configure_current_outputs",
                return_value=FakeToolResponse(result={"commands": ["XU;", "QRYALL;"]}),
            ) as configure:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(configure.call_args.kwargs["frequency_hz"], 60.0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["result"]["commands"], ["XU;", "QRYALL;"])


if __name__ == "__main__":
    unittest.main()
