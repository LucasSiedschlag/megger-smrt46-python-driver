from __future__ import annotations

import io
import json
import logging
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from smrt46_client import Smrt46SessionBusyError, Smrt46TimeoutError
from tools.smrt46_probe_common import run_probe


class _FakeRawResponse:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def to_dict(self) -> dict[str, str]:
        return {"raw": self.raw}


class TimeoutThenSuccessClient:
    enter_calls = 0

    def __init__(self, *args, **kwargs) -> None:
        return None

    def __enter__(self) -> "TimeoutThenSuccessClient":
        type(self).enter_calls += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def initialize_ethernet_session(self) -> dict[str, _FakeRawResponse]:
        if type(self).enter_calls == 1:
            raise Smrt46TimeoutError("No SMRT46 response received within 2.00s.")
        return {
            "idle_before": _FakeRawResponse("GATE0000"),
            "config": _FakeRawResponse("<G4>,<Model:SMRT46P>"),
            "idle_after": _FakeRawResponse("GATE0000"),
            "startup": _FakeRawResponse("HSU"),
        }


class AlwaysBusyClient:
    enter_calls = 0

    def __init__(self, *args, **kwargs) -> None:
        return None

    def __enter__(self) -> "AlwaysBusyClient":
        type(self).enter_calls += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def initialize_ethernet_session(self) -> dict[str, _FakeRawResponse]:
        raise Smrt46SessionBusyError(
            "SMRT46 reports that another application-layer connection is already built."
        )


class Smrt46ProbeCommonTests(unittest.TestCase):
    def _settings(self) -> dict[str, object]:
        return {
            "target": "default",
            "config_file": "config/smrt46_hosts.ini",
            "host": "10.20.150.44",
            "port": 8000,
            "connect_timeout": 3.0,
            "timeout": 2.0,
            "poll_interval": 0.05,
            "discovery_udp_port": 8001,
            "logger": logging.getLogger("test-smrt46-probe-common"),
            "session_log": None,
        }

    @patch("tools.smrt46_probe_common.time.sleep", return_value=None)
    @patch("tools.smrt46_probe_common.Smrt46Client", TimeoutThenSuccessClient)
    def test_run_probe_retries_timeout_and_succeeds(self, _sleep) -> None:
        TimeoutThenSuccessClient.enter_calls = 0
        output = io.StringIO()
        with redirect_stdout(output):
            status = run_probe(
                settings=self._settings(),
                operation_name="connection_probe",
                operation=lambda client, init_result: {"status": "ok"},
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(TimeoutThenSuccessClient.enter_calls, 2)

    @patch("tools.smrt46_probe_common.time.sleep", return_value=None)
    @patch("tools.smrt46_probe_common.Smrt46Client", AlwaysBusyClient)
    def test_run_probe_returns_busy_after_all_retries(self, _sleep) -> None:
        AlwaysBusyClient.enter_calls = 0
        output = io.StringIO()
        with redirect_stdout(output):
            status = run_probe(
                settings=self._settings(),
                operation_name="connection_probe",
                operation=lambda client, init_result: {"status": "ok"},
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["attempts"], 4)
        self.assertEqual(AlwaysBusyClient.enter_calls, 4)


if __name__ == "__main__":
    unittest.main()
