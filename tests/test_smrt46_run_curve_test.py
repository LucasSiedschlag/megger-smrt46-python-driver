from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from smrt46_client.models import Smrt46MeasuredCurrent, Smrt46MeasuredVoltage, Smrt46StatusSnapshot
from tools.smrt46_run_curve_test import main

from tests.fake_tool_response import FakeToolResponse

CURVE_RESULT = {
    "test_name": "bench_curve",
    "phases": [{"phase": "A", "stop_reason": "din_closed", "final_amplitude_a": 4.2, "alarms": []}],
}


class Smrt46RunCurveTestToolTests(unittest.TestCase):
    def test_main_runs_direct_curve_and_prints_json(self) -> None:
        args = [
            "smrt46_run_curve_test.py",
            "--host",
            "192.168.0.20",
            "--phase",
            "A",
            "--start",
            "4.0",
            "--stop",
            "4.2",
            "--test-name",
            "bench_curve",
        ]
        output = io.StringIO()
        with patch("sys.argv", args):
            with patch(
                "tools.smrt46_run_curve_test.run_curve_test",
                return_value=FakeToolResponse(success=True, result=CURVE_RESULT),
            ) as run_curve:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertIsNone(run_curve.call_args.kwargs["on_sample"])
        text = output.getvalue()
        payload = json.loads(text[text.find("{") :])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["test_name"], "bench_curve")

    def test_main_sets_snapshot_callback_and_suppresses_json_in_only_current_time_mode(
        self,
    ) -> None:
        args = [
            "smrt46_run_curve_test.py",
            "--host",
            "192.168.0.20",
            "--phase",
            "A",
            "--start",
            "4.0",
            "--stop",
            "4.2",
            "--only-current-time",
        ]
        output = io.StringIO()

        def fake_run_curve(*args, **kwargs):
            kwargs["on_sample"](1, 4.0)
            kwargs["on_snapshot"](
                Smrt46StatusSnapshot(
                    raw="QRYALL",
                    voltages=[Smrt46MeasuredVoltage(1, False, 10, 10, 0.0, 0.0, 0.0, 60.0)],
                    currents=[Smrt46MeasuredCurrent(1, True, 11, 11, 3.8765, 0.0, 0.0, 60.0)],
                    binary_inputs="0000000000",
                    binary_outputs="000000",
                    event_count=1,
                    elapsed_time_s=0.2,
                )
            )
            return FakeToolResponse(success=True, result=CURVE_RESULT)

        with patch("sys.argv", args):
            with patch(
                "tools.smrt46_run_curve_test.run_curve_test", side_effect=fake_run_curve
            ) as run_curve:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(callable(run_curve.call_args.kwargs["on_sample"]))
        self.assertEqual(run_curve.call_args.args[0]["qg_interval"], 1)
        text = output.getvalue()
        self.assertIn("C1 send=4.0000A | C1 measured=3.8765A | t=", text)
        self.assertIn("Phase A: TRIP at 4.2000 A  [binary input]", text)
        self.assertNotIn('"operation": "smrt46_curve_test"', text)


if __name__ == "__main__":
    unittest.main()
