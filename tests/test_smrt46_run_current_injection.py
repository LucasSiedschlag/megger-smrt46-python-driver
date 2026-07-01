from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.smrt46_run_current_injection import build_current_payload, main, parse_current_spec

from tests.fake_tool_response import FakeToolResponse


class Smrt46RunCurrentInjectionToolTests(unittest.TestCase):
    def test_parse_current_spec_extracts_channel_amplitude_and_phase(self) -> None:
        self.assertEqual(
            parse_current_spec("2:5.0:120"), {"channel": 2, "amplitude": 5.0, "phase_deg": 120.0}
        )

    def test_build_current_payload_sorts_by_channel(self) -> None:
        self.assertEqual(
            build_current_payload(["2:5.0:120", "1:3.0:0"]),
            [
                {"channel": 1, "amplitude": 3.0, "phase_deg": 0.0},
                {"channel": 2, "amplitude": 5.0, "phase_deg": 120.0},
            ],
        )

    def test_main_runs_direct_injection_and_prints_json(self) -> None:
        args = [
            "smrt46_run_current_injection.py",
            "--host",
            "192.168.0.20",
            "--current",
            "2:5.0:120",
            "--current",
            "1:3.0:0",
            "--frequency",
            "60.0",
            "--poll-count",
            "2",
            "--test-name",
            "bench_trip",
        ]
        output = io.StringIO()
        with patch("sys.argv", args):
            with patch(
                "tools.smrt46_run_current_injection.run_current_injection",
                return_value=FakeToolResponse(test_name="bench_trip", result={"alarms": []}),
            ) as run_current:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(run_current.call_args.kwargs["poll_count"], 2)
        self.assertEqual(run_current.call_args.kwargs["test_name"], "bench_trip")
        self.assertIsNone(run_current.call_args.kwargs["on_snapshot"])
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["currents"][0]["channel"], 1)
        self.assertEqual(payload["result"]["test_name"], "bench_trip")

    def test_main_sets_snapshot_callback_in_only_current_time_mode(self) -> None:
        args = [
            "smrt46_run_current_injection.py",
            "--host",
            "192.168.0.20",
            "--current",
            "1:3.0:0",
            "--only-current-time",
        ]
        output = io.StringIO()
        with patch("sys.argv", args):
            with patch(
                "tools.smrt46_run_current_injection.run_current_injection",
                return_value=FakeToolResponse(),
            ) as run_current:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(callable(run_current.call_args.kwargs["on_snapshot"]))


if __name__ == "__main__":
    unittest.main()
