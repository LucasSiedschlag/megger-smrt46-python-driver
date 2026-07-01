from __future__ import annotations

import unittest

from smrt46_client import (
    RawAsciiResponse,
    Smrt46AlarmSet,
    Smrt46Client,
    Smrt46CommandResult,
    Smrt46CurrentChannelConfig,
    Smrt46CurrentInjectionRequest,
    Smrt46CurrentInjectionResult,
    Smrt46CurvePhaseResult,
    Smrt46CurveTestConfig,
    Smrt46CurveTestResult,
    Smrt46GateState,
    Smrt46IpConfig,
    Smrt46MaxLimits,
    Smrt46MeasuredCurrent,
    Smrt46MeasuredVoltage,
    Smrt46StatusSnapshot,
    Smrt46VoltageChannelConfig,
    Smrt46VoltageInjectionRequest,
    Smrt46VoltageInjectionResult,
)


class PublicApiTests(unittest.TestCase):
    def test_top_level_package_exports_core_client_models(self) -> None:
        exports = [
            RawAsciiResponse,
            Smrt46AlarmSet,
            Smrt46Client,
            Smrt46CommandResult,
            Smrt46CurrentChannelConfig,
            Smrt46CurrentInjectionRequest,
            Smrt46CurrentInjectionResult,
            Smrt46CurvePhaseResult,
            Smrt46CurveTestConfig,
            Smrt46CurveTestResult,
            Smrt46GateState,
            Smrt46IpConfig,
            Smrt46MaxLimits,
            Smrt46MeasuredCurrent,
            Smrt46MeasuredVoltage,
            Smrt46StatusSnapshot,
            Smrt46VoltageChannelConfig,
            Smrt46VoltageInjectionRequest,
            Smrt46VoltageInjectionResult,
        ]

        self.assertEqual(len(exports), 19)


if __name__ == "__main__":
    unittest.main()
