from __future__ import annotations

import logging
import unittest
from typing import Union
from unittest.mock import patch

from smrt46_client.client import Smrt46Client
from smrt46_client.exceptions import Smrt46ProtocolError, Smrt46SessionBusyError
from smrt46_client.models import Smrt46CurveTestConfig, Smrt46StatusSnapshot
from smrt46_client.parser import (
    has_deviation_alarm,
    is_binary_input_closed,
    parse_alarm_response,
    parse_binary_inputs,
)
from smrt46_client.protocol import (
    build_curve_amplitude_step,
    build_curve_phase_init_command,
    build_curve_timer_setup,
)


class ScriptedSmrt46Client(Smrt46Client):
    def __init__(self, responses: dict[str, list[Union[str, Exception]]]) -> None:
        super().__init__("127.0.0.1", logger=logging.getLogger("test"))
        self._responses = {key: list(value) for key, value in responses.items()}
        self.commands: list[str] = []

    def connect(self) -> None:
        self._sock = object()  # type: ignore[assignment]

    def close(self) -> None:
        self._sock = None

    def send_command(self, command: str, **kwargs):
        normalized = command if command.endswith((";", ",")) else f"{command};"
        self.commands.append(normalized)

        class Result:
            def __init__(self, response: str, cmd: str) -> None:
                self.command = cmd
                self.response = response

        queue = self._responses.get(normalized)
        event = queue.pop(0) if queue else ""
        if isinstance(event, Exception):
            raise event
        response = event
        return Result(response, normalized)


def _qryall_payload(bi_field: str, *, t01: float = 0.0, measured_c1_a: float = 4.0) -> str:
    return (
        "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
        f"I,1,11,{measured_c1_a:.4f},0.0100,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
        f"BI,{bi_field},BO,000000,EV,1,T,0.1200,T01,{t01:.1f},"
        "T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0;"
    )


class Smrt46CurveTests(unittest.TestCase):
    def test_parser_helpers_for_binary_input_and_deviation_alarm(self) -> None:
        raw = _qryall_payload("0000000001")
        bi = parse_binary_inputs(raw)
        self.assertEqual(bi, "0000000001")
        self.assertTrue(is_binary_input_closed(bi, 1))
        self.assertFalse(is_binary_input_closed(bi, 2))
        self.assertTrue(has_deviation_alarm("ERROR: Deviation alarm on C1"))
        self.assertFalse(has_deviation_alarm("ERROR: Open circuit alarm on C1"))
        wrapped = parse_alarm_response("DSP 2 ErrCnt=1,10:ERROR: Open circuit alarm on C1 ,;")
        self.assertEqual(wrapped.alarms, ["Open circuit alarm on C1 ,"])

    def test_parser_binary_input_index_edges_and_out_of_range(self) -> None:
        bi = "1000000001"
        self.assertTrue(is_binary_input_closed(bi, 1))
        self.assertTrue(is_binary_input_closed(bi, 10))
        with self.assertRaises(ValueError):
            is_binary_input_closed(bi, 11)

    def test_protocol_helpers_build_curve_commands(self) -> None:
        self.assertEqual(build_curve_timer_setup(), "td2,t01m,t01cal,t01HD,TR,")
        self.assertEqual(build_curve_amplitude_step(2, 4.02), "c2,a4.0200,d0,")
        init_command = build_curve_phase_init_command("B", 0.0, frequency_hz=60.0)
        self.assertIn("c2,a0.0000,d0,p120.000,f60.000,on,", init_command)
        self.assertTrue(init_command.endswith("BO010,BO020,BO030,BO040,BO050,BO060;"))

    def test_run_curve_injection_stops_on_bin_close(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000001"),  # stop condition
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertFalse(result.aborted)
        self.assertEqual(result.final_state, "COMPLETE")
        self.assertEqual(result.phases[0].stop_reason, "din_closed")
        self.assertEqual(result.phases[0].phase, "A")
        self.assertIn("QRYALL;", result.command_sequence)

    def test_run_curve_injection_stops_on_timer_trip_without_bin_close(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000000", t01=0.4),  # timer-based trip
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertFalse(result.aborted)
        self.assertEqual(result.final_state, "COMPLETE")
        self.assertEqual(result.phases[0].stop_reason, "phase_trip")

    def test_run_curve_injection_stops_on_sustained_current_collapse(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000000", measured_c1_a=0.13),  # collapse poll #1
                    _qryall_payload("0000000000", measured_c1_a=0.12),  # collapse poll #2
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertFalse(result.aborted)
        self.assertEqual(result.final_state, "COMPLETE")
        self.assertEqual(result.phases[0].stop_reason, "phase_trip")

    def test_run_curve_injection_uses_qryall_interval(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": [
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                ],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000000"),  # interval poll
                    _qryall_payload("0000000000"),  # final poll when exhausted
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.04,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=2,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertEqual(result.phases[0].stop_reason, "ramp_exhausted")
        self.assertEqual(client.commands.count("QRYALL;"), 4)

    def test_run_curve_injection_reapplies_trip_monitor_after_rearm(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000000"),  # final poll when exhausted
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.0,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
            rearm_before_phase=True,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertEqual(result.phases[0].stop_reason, "ramp_exhausted")
        self.assertGreaterEqual(
            client.commands.count("t01m,t01sto,t01cal,VFMIN40E,VFMIN00O,,TR,"),
            2,
        )
        self.assertGreaterEqual(client.commands.count("OCA:ON,"), 2)

    def test_run_curve_injection_emits_step_callback_for_each_amplitude(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": [
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                ],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000000"),  # interval poll
                    _qryall_payload("0000000000"),  # final poll when exhausted
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.04,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=2,
            target_bin=1,
        )
        samples: list[tuple[int, float]] = []

        with patch("smrt46_client.client.time.sleep", return_value=None):
            _ = client.run_curve_injection(
                config,
                on_step=lambda channel, amplitude: samples.append((channel, amplitude)),
            )

        self.assertEqual(samples, [(1, 4.0), (1, 4.02), (1, 4.04)])

    def test_run_curve_injection_emits_snapshot_callback_when_qryall_runs(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": [
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                    "GATE0000;",
                ],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000000"),  # step 1
                    _qryall_payload("0000000000"),  # step 2
                    _qryall_payload("0000000000"),  # step 3
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.04,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )
        snapshots: list[Smrt46StatusSnapshot] = []

        with patch("smrt46_client.client.time.sleep", return_value=None):
            _ = client.run_curve_injection(config, on_snapshot=snapshots.append)

        self.assertEqual(len(snapshots), 3)
        self.assertEqual(snapshots[0].currents[0].channel, 1)

    def test_run_curve_injection_aborts_on_any_error_frame(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "ERROR: Open circuit alarm on C1;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertTrue(result.aborted)
        self.assertEqual(result.final_state, "COMPLETE")
        self.assertEqual(result.phases[0].stop_reason, "phase_trip")
        self.assertIn("Open circuit alarm on C1", result.notes[0])

    def test_run_curve_injection_aborts_on_wrapped_error_frame(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": [
                    "GATE0000;",
                    "GATE0000;",
                    "DSP 2 ErrCnt=1,10:ERROR: Open circuit alarm on C2 ,;",
                ],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)
        self.assertTrue(result.aborted)
        self.assertEqual(result.final_state, "COMPLETE")
        self.assertEqual(result.phases[0].stop_reason, "phase_trip")
        self.assertIn("Open circuit alarm on C2", result.notes[0])

    def test_run_curve_injection_raises_on_non_zero_gate_and_runs_cleanup(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "GATE0001;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            with self.assertRaises(Smrt46ProtocolError):
                client.run_curve_injection(config)

        self.assertIn("XU;", client.commands)

    def test_run_curve_injection_handles_session_busy_and_attempts_cleanup(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", Smrt46SessionBusyError("session busy")],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            with self.assertRaises(Smrt46SessionBusyError):
                client.run_curve_injection(config)

        self.assertIn("XU;", client.commands)

    def test_run_curve_injection_fails_when_bin_already_latched(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000001"),  # baseline already latched
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            with self.assertRaises(Smrt46ProtocolError):
                client.run_curve_injection(config)

    def test_run_curve_injection_rejects_malformed_bi_payload(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("1"),  # malformed baseline BI field length
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=2,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            with self.assertRaises(Smrt46ProtocolError):
                client.run_curve_injection(config)

    def test_run_curve_injection_accepts_ok_qhs_during_cleanup(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE", "DONE"],
                "BIV:1:0;": ["OK"],
                "BIV:2:0;": ["OK"],
                "QHS,": ["OK", "OK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _qryall_payload("0000000000"),  # bootstrap
                    _qryall_payload("0000000000"),  # baseline
                    _qryall_payload("0000000001"),  # stop condition
                ],
            }
        )
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            target_bin=1,
        )

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client.run_curve_injection(config)

        self.assertTrue(result.success)

    def test_run_curve_injection_rejects_invalid_config(self) -> None:
        client = ScriptedSmrt46Client({})
        client.connect()
        config = Smrt46CurveTestConfig(
            phases=["A", "A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=0,
            target_bin=1,
        )

        with self.assertRaises(Smrt46ProtocolError):
            client.run_curve_injection(config)

        config = Smrt46CurveTestConfig(
            phases=["A"],
            start_current_a=4.0,
            stop_current_a=4.2,
            step_size_a=0.02,
            step_delay_ms=0,
            qg_interval=1,
            trip_confirm_polls=0,
            target_bin=1,
        )

        with self.assertRaises(Smrt46ProtocolError):
            client.run_curve_injection(config)


if __name__ == "__main__":
    unittest.main()
