from __future__ import annotations

import unittest

from smrt46_client.parser import (
    parse_alarm_response,
    parse_qg_response,
    parse_qip_response,
    parse_qryall_response,
    parse_qrymax_response,
    parse_qver_response,
)


class Smrt46ParserTests(unittest.TestCase):
    def test_parse_qg_response_extracts_gate_mask(self) -> None:
        result = parse_qg_response("GATE0000;")
        self.assertEqual(result.raw, "GATE0000")
        self.assertEqual(result.mask, "0000")

    def test_parse_qrymax_response_extracts_voltage_and_current_limits(self) -> None:
        result = parse_qrymax_response(
            "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
        )
        self.assertEqual(result.voltage_limits, [300.0, 300.0, 300.0, 150.0])
        self.assertEqual(result.current_limits, [60.0, 60.0, 60.0])
        self.assertEqual(result.continuous_current_limits, [32.0, 32.0, 32.0])

    def test_parse_qip_response_extracts_ip_and_mode(self) -> None:
        result = parse_qip_response("169.254.219.227,AutoCFG;")

        self.assertEqual(result.raw, "169.254.219.227,AutoCFG")
        self.assertEqual(result.ip_address, "169.254.219.227")
        self.assertEqual(result.mode, "AutoCFG")
        self.assertEqual(result.extra_fields, [])

    def test_parse_qver_response_extracts_dsp_components(self) -> None:
        result = parse_qver_response(
            "DSP0:6.41200,CPLD:8,Boot:1.052;"
            "DSP1:6.41200,CPLD:8,Boot:1.052;"
            "DSP2:6.41200,CPLD:8,Boot:1.052;"
        )

        self.assertEqual(result.raw.count("DSP"), 3)
        self.assertEqual(
            [component.name for component in result.components],
            ["DSP0", "DSP1", "DSP2"],
        )
        self.assertEqual(result.components[0].firmware_version, "6.41200")
        self.assertEqual(result.components[0].cpld, "8")
        self.assertEqual(result.components[0].boot, "1.052")

    def test_parse_qryall_response_extracts_idle_snapshot(self) -> None:
        result = parse_qryall_response(
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,125,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.00,12,SMRT,SSF:NA,44.26,67.15;"
        )
        self.assertEqual(len(result.voltages), 4)
        self.assertEqual(len(result.currents), 3)
        self.assertFalse(result.currents[0].enabled)
        self.assertEqual(result.currents[0].amplitude, 0.0)
        self.assertEqual(result.binary_inputs, "0000000000")
        self.assertEqual(result.binary_outputs, "000000")
        self.assertEqual(result.event_count, 0)
        self.assertEqual(result.elapsed_time_s, 0.0)
        self.assertEqual(result.timer_values["T10"], 0.0)
        self.assertEqual(result.metadata["P8000"], 125)
        self.assertEqual(result.metadata["P8k2"], 0)
        self.assertEqual(result.metadata["VDC"], "NA")
        self.assertEqual(result.metadata["BootCnt:50"], "DCAP0")
        self.assertEqual(result.metadata["Tmax"], 26.0)
        self.assertEqual(result.metadata["12"], "SMRT")
        self.assertEqual(result.metadata["SSF:NA"], 44.26)
        self.assertEqual(result.metadata["67.15"], None)

    def test_parse_qryall_response_extracts_live_current_measurements(self) -> None:
        result = parse_qryall_response(
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,1,11,3.0020,0.0193,0.000,60.000,1,21,5.0059,-0.0017,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000000,BO,000000,EV,2,T,0.1208,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,518,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.50,12,SMRT,SSF:NA,46.73,70.98;"
        )
        self.assertTrue(result.currents[0].enabled)
        self.assertTrue(result.currents[1].enabled)
        self.assertFalse(result.currents[2].enabled)
        self.assertEqual(result.currents[0].amplitude, 3.002)
        self.assertEqual(result.currents[1].amplitude, 5.0059)
        self.assertEqual(result.currents[1].phase_deg, 120.0)
        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.elapsed_time_s, 0.1208)
        self.assertEqual(result.metadata["P8000"], 518)
        self.assertEqual(result.metadata["SSF:NA"], 46.73)

    def test_parse_alarm_response_extracts_multiple_alarm_messages(self) -> None:
        result = parse_alarm_response(
            "ERROR: Open circuit alarm  on C1 | ERROR: Open circuit alarm  on C2 | "
        )
        self.assertEqual(
            result.alarms,
            ["Open circuit alarm  on C1", "Open circuit alarm  on C2"],
        )


if __name__ == "__main__":
    unittest.main()
