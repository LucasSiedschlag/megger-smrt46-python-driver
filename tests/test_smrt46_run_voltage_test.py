from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.smrt46_run_voltage_test import build_voltage_payload, main, parse_voltage_spec

from tests.fake_tool_response import FakeToolResponse

VOLTAGE_RESULT = {
    "success": True,
    "final_state": "TRIPPED",
    "stop_reason": "binary_input_closed",
    "trip_detected": True,
    "request": {
        "voltages": [
            {
                "channel": 2,
                "amplitude": 50.0,
                "phase_deg": 120.0,
                "frequency_hz": 60.0,
                "enabled": True,
            }
        ],
    },
    "final_snapshot": {"voltages": [{"channel": 2, "amplitude": 0.0, "phase_deg": 120.0}]},
    "observed_peak_voltages": {2: 50.0},
    "notes": ["Local generator amplifier over current on V2"],
}


class Smrt46RunVoltageTestToolTests(unittest.TestCase):
    def test_parse_voltage_spec_extracts_channel_amplitude_and_phase(self) -> None:
        self.assertEqual(
            parse_voltage_spec("2:50.0:120"), {"channel": 2, "amplitude": 50.0, "phase_deg": 120.0}
        )

    def test_build_voltage_payload_sorts_by_channel(self) -> None:
        self.assertEqual(
            build_voltage_payload(["2:50.0:120", "1:10.0:0"]),
            [
                {"channel": 1, "amplitude": 10.0, "phase_deg": 0.0},
                {"channel": 2, "amplitude": 50.0, "phase_deg": 120.0},
            ],
        )

    def test_main_defaults_to_compact_voltage_degree_output(self) -> None:
        output = io.StringIO()
        with patch(
            "sys.argv",
            ["smrt46_run_voltage_test.py", "--host", "192.168.0.20", "--voltage", "2:50.0:120"],
        ):
            with patch(
                "tools.smrt46_run_voltage_test.run_voltage_test",
                return_value=FakeToolResponse(
                    success=True, final_state="TRIPPED", result=VOLTAGE_RESULT
                ),
            ) as run_voltage:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(callable(run_voltage.call_args.kwargs["on_snapshot"]))
        text = output.getvalue()
        self.assertIn("ok=true", text)
        self.assertIn("V2=0.0000V", text)
        self.assertIn("peak=50.0000V", text)

    def test_main_prints_json_when_requested(self) -> None:
        output = io.StringIO()
        with patch(
            "sys.argv",
            [
                "smrt46_run_voltage_test.py",
                "--host",
                "192.168.0.20",
                "--voltage",
                "2:50.0:120",
                "--json",
            ],
        ):
            with patch(
                "tools.smrt46_run_voltage_test.run_voltage_test",
                return_value=FakeToolResponse(
                    test_name="smrt46_voltage_test", result=VOLTAGE_RESULT
                ),
            ) as run_voltage:
                with redirect_stdout(output):
                    exit_code = main()
        self.assertEqual(exit_code, 0)
        self.assertIsNone(run_voltage.call_args.kwargs["on_snapshot"])
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["operation"], "smrt46_voltage_test")


if __name__ == "__main__":
    unittest.main()
