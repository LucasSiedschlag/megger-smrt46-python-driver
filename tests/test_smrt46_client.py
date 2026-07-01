from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from typing import List, Union
from unittest.mock import patch

from smrt46_client.client import Smrt46Client
from smrt46_client.exceptions import (
    Smrt46ConnectionError,
    Smrt46ProtocolError,
    Smrt46SessionBusyError,
    Smrt46TimeoutError,
)
from smrt46_client.models import (
    Smrt46CurrentChannelConfig,
    Smrt46CurrentInjectionRequest,
    Smrt46StatusSnapshot,
    Smrt46VoltageChannelConfig,
    Smrt46VoltageInjectionRequest,
)


class FakeSocket:
    def __init__(self, recv_events: List[Union[bytes, Exception]]) -> None:
        self.recv_events = list(recv_events)
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, size: int) -> bytes:
        if not self.recv_events:
            raise TimeoutError()
        event = self.recv_events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    def shutdown(self, how: int) -> None:
        return None

    def close(self) -> None:
        return None


class BrokenPipeOnSendSocket(FakeSocket):
    def sendall(self, data: bytes) -> None:
        raise BrokenPipeError(32, "Broken pipe")


class ConnectionResetOnSendSocket(FakeSocket):
    def sendall(self, data: bytes) -> None:
        raise ConnectionResetError(104, "Connection reset by peer")


class SocketWithLifecycle:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.shutdown_calls: list[int] = []
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def shutdown(self, how: int) -> None:
        self.shutdown_calls.append(how)

    def close(self) -> None:
        self.closed = True


class RecordingSmrt46Client(Smrt46Client):
    def __init__(self) -> None:
        super().__init__("127.0.0.1", logger=logging.getLogger("test"))
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

        responses = {
            "qg,": "GATE0000",
            "QC;": "<G4>,<Model:SMRT46P>",
            "HSU;": "HSU",
        }
        return Result(responses.get(normalized, ""), normalized)


class ScriptedSmrt46Client(Smrt46Client):
    def __init__(self, responses: dict[str, list[str]]) -> None:
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
        response = queue.pop(0) if queue else ""
        return Result(response, normalized)


class RetryPrepareClient(Smrt46Client):
    def __init__(self) -> None:
        super().__init__("127.0.0.1", logger=logging.getLogger("test"))
        self._first_gate_attempt = True
        self.commands: list[str] = []
        self.connect_calls = 0
        self.close_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        self._sock = object()  # type: ignore[assignment]

    def close(self) -> None:
        self.close_calls += 1
        self._sock = None

    def send_command(self, command: str, **kwargs):
        normalized = command if command.endswith((";", ",")) else f"{command};"
        self.commands.append(normalized)
        if normalized == "qg," and self._first_gate_attempt:
            self._first_gate_attempt = False
            raise Smrt46SessionBusyError("session busy")

        class Result:
            def __init__(self, response: str, cmd: str) -> None:
                self.command = cmd
                self.response = response

        responses = {
            "qg,": "GATE0000;",
            "HSU;": "HSU;",
            "QC;": "<G4>,<Model:SMRT46P>;",
        }
        return Result(responses.get(normalized, ""), normalized)


class RetryPrepareAfterQcfgBusyClient(Smrt46Client):
    def __init__(self) -> None:
        super().__init__("127.0.0.1", logger=logging.getLogger("test"))
        self._busy_after_gate = True
        self.commands: list[str] = []
        self.connect_calls = 0
        self.close_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        self._sock = object()  # type: ignore[assignment]

    def close(self) -> None:
        self.close_calls += 1
        self._sock = None

    def send_command(self, command: str, **kwargs):
        normalized = command if command.endswith((";", ",")) else f"{command};"
        self.commands.append(normalized)
        if normalized == "QC;" and self._busy_after_gate:
            self._busy_after_gate = False
            raise Smrt46SessionBusyError("session busy")

        class Result:
            def __init__(self, response: str, cmd: str) -> None:
                self.command = cmd
                self.response = response

        responses = {
            "qg,": "GATE0000;",
            "HSU;": "HSU;",
            "QC;": "<G4>,<Model:SMRT46P>;",
        }
        return Result(responses.get(normalized, ""), normalized)


class RetryBivTimeoutClient(Smrt46Client):
    def __init__(self) -> None:
        super().__init__("127.0.0.1", logger=logging.getLogger("test"))
        self._biv_attempts = 0
        self.commands: list[str] = []
        self.connect_calls = 0
        self.close_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        self._sock = object()  # type: ignore[assignment]

    def close(self) -> None:
        self.close_calls += 1
        self._sock = None

    def send_command(self, command: str, **kwargs):
        normalized = command if command.endswith((";", ",")) else f"{command};"
        self.commands.append(normalized)
        if normalized.startswith("BIV:"):
            self._biv_attempts += 1
            if self._biv_attempts == 1:
                raise Smrt46TimeoutError("No SMRT46 response received within 5.00s.")

        class Result:
            def __init__(self, response: str, cmd: str) -> None:
                self.command = cmd
                self.response = response

        if normalized == "XU;":
            return Result("DONE;", normalized)
        return Result("DONE;", normalized)


class CleanupContinuesAfterXuTimeoutClient(Smrt46Client):
    def __init__(self) -> None:
        super().__init__("127.0.0.1", logger=logging.getLogger("test"))
        self.commands: list[str] = []

    def connect(self) -> None:
        self._sock = object()  # type: ignore[assignment]

    def close(self) -> None:
        self._sock = None

    def send_command(self, command: str, **kwargs):
        normalized = command if command.endswith((";", ",")) else f"{command};"
        self.commands.append(normalized)
        if normalized == "XU;":
            raise Smrt46TimeoutError("No SMRT46 response received within 5.00s.")

        class Result:
            def __init__(self, response: str, cmd: str) -> None:
                self.command = cmd
                self.response = response

        if normalized == "QHS,":
            return Result("ACK", normalized)
        return Result("", normalized)


class Smrt46ClientTests(unittest.TestCase):
    def _sample_request(self) -> Smrt46CurrentInjectionRequest:
        return Smrt46CurrentInjectionRequest(
            currents=[
                Smrt46CurrentChannelConfig(channel=1, amplitude=3.0, phase_deg=0.0),
                Smrt46CurrentChannelConfig(channel=2, amplitude=5.0, phase_deg=120.0),
            ],
            frequency_hz=60.0,
        )

    def test_connect_maps_connection_refused_to_session_busy(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        with patch(
            "smrt46_client.client.socket.create_connection",
            side_effect=ConnectionRefusedError("busy"),
        ):
            with self.assertRaises(Smrt46SessionBusyError):
                client.connect()

    def test_initialize_ethernet_session_matches_expected_sequence(self) -> None:
        client = RecordingSmrt46Client()
        client.connect()
        result = client.initialize_ethernet_session()

        self.assertEqual(client.commands, ["qg,", "QC;", "qg,", "HSU;"])
        self.assertEqual(result["idle_before"].raw, "GATE0000")
        self.assertEqual(result["config"].raw, "<G4>,<Model:SMRT46P>")
        self.assertEqual(result["idle_after"].raw, "GATE0000")
        self.assertEqual(result["startup"].raw, "HSU")

    def test_send_command_does_not_write_session_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_log = Path(temp_dir) / "smrt46-session.jsonl"
            client = Smrt46Client(
                "127.0.0.1",
                logger=logging.getLogger("test"),
                session_log_path=str(session_log),
            )
            client._sock = FakeSocket([b"GATE0000;"])  # type: ignore[assignment]

            result = client.send_command("qg,")

            self.assertEqual(result.response, "GATE0000")
            self.assertFalse(session_log.exists())

    def test_qip_returns_typed_ip_config(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b"169.254.219.227,AutoCFG;"])  # type: ignore[assignment]

        result = client.qip()

        self.assertEqual(result.raw, "169.254.219.227,AutoCFG")
        self.assertEqual(result.ip_address, "169.254.219.227")
        self.assertEqual(result.mode, "AutoCFG")

    def test_qver_returns_typed_components_and_consumes_buffered_frames(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket(
            [
                b"DSP0:6.41200,CPLD:8,Boot:1.052;"
                b"DSP1:6.41200,CPLD:8,Boot:1.052;"
                b"DSP2:6.41200,CPLD:8,Boot:1.052;"
            ]
        )  # type: ignore[assignment]

        result = client.qver()

        self.assertEqual(
            [component.name for component in result.components],
            ["DSP0", "DSP1", "DSP2"],
        )
        self.assertEqual(result.components[0].firmware_version, "6.41200")
        self.assertEqual(result.components[0].cpld, "8")
        self.assertEqual(result.components[0].boot, "1.052")
        self.assertEqual(client._rx_buffer, "")

    def test_read_response_raises_connection_error_when_socket_closes_immediately(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b""])  # type: ignore[assignment]

        with self.assertRaises(Smrt46ConnectionError):
            client._read_response(timeout=0.2)

    def test_close_sends_best_effort_su_before_closing_socket(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        sock = SocketWithLifecycle()
        client._sock = sock  # type: ignore[assignment]

        with patch("smrt46_client.client.time.sleep") as sleep_mock:
            client.close()

        self.assertEqual(sock.sent, [b"SU;"])
        self.assertTrue(sock.shutdown_calls)
        self.assertTrue(sock.closed)
        sleep_mock.assert_called_once_with(client.DISCONNECT_SETTLE_DELAY_S)

    def test_read_response_maps_connection_reset_to_session_busy(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([ConnectionResetError(104, "Connection reset by peer")])  # type: ignore[assignment]

        with self.assertRaises(Smrt46SessionBusyError):
            client._read_response(timeout=0.2)

    def test_send_command_maps_existing_connection_message_to_session_busy(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b"There is already a connection built.;"])  # type: ignore[assignment]

        with self.assertRaises(Smrt46SessionBusyError):
            client.send_command("qg,")

    def test_send_command_maps_broken_pipe_to_session_busy(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = BrokenPipeOnSendSocket([])  # type: ignore[assignment]

        with self.assertRaises(Smrt46SessionBusyError):
            client.send_command("qg,")

    def test_send_command_maps_connection_reset_on_send_to_session_busy(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = ConnectionResetOnSendSocket([])  # type: ignore[assignment]

        with self.assertRaises(Smrt46SessionBusyError):
            client.send_command("qg,")

    def test_prepare_current_output_session_reconnects_after_session_busy(self) -> None:
        client = RetryPrepareClient()
        client.connect()

        with patch("smrt46_client.client.time.sleep", return_value=None):
            results = client._prepare_current_output_session()

        self.assertEqual(client.connect_calls, 2)
        self.assertGreaterEqual(client.close_calls, 1)
        self.assertEqual(
            [result.command for result in results],
            ["qg,", "HSU;", "QC;", "SYSSETF,", "SU;"],
        )

    def test_prepare_current_output_session_retries_if_qcfg_hits_session_busy(self) -> None:
        client = RetryPrepareAfterQcfgBusyClient()
        client.connect()

        with patch("smrt46_client.client.time.sleep", return_value=None):
            results = client._prepare_current_output_session()

        self.assertEqual(client.connect_calls, 2)
        self.assertGreaterEqual(client.close_calls, 1)
        self.assertEqual(
            [result.command for result in results],
            ["qg,", "HSU;", "QC;", "SYSSETF,", "SU;"],
        )
        self.assertEqual(
            client.commands,
            ["qg,", "HSU;", "QC;", "qg,", "HSU;", "QC;", "SYSSETF,", "SU;"],
        )

    def test_send_command_splits_concatenated_frames_without_desync(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b"ACK;V,300.000,300.000,300.000,150.0000;"])  # type: ignore[assignment]

        first = client.send_command("QHS,")
        second = client.send_command("QRYMAX;")

        self.assertEqual(first.response, "ACK")
        self.assertEqual(second.response, "V,300.000,300.000,300.000,150.0000")

    def test_execute_runtime_command_accepts_done_bang_bang_for_reset(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b"Done!!;"])  # type: ignore[assignment]

        result = client._execute_runtime_command("XU;")

        self.assertEqual(result.response, "Done!!")

    def test_execute_runtime_command_accepts_done_for_biv_ack(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b"DONE;"])  # type: ignore[assignment]

        result = client._execute_runtime_command("BIV:1:0;")

        self.assertEqual(result.response, "DONE")

    def test_execute_runtime_command_retries_biv_after_timeout(self) -> None:
        client = RetryBivTimeoutClient()
        client.connect()

        with patch("smrt46_client.client.time.sleep", return_value=None):
            result = client._execute_runtime_command("BIV:1:0;")

        self.assertEqual(result.command, "BIV:1:0;")
        self.assertEqual(result.response, "DONE;")
        self.assertEqual(client._biv_attempts, 2)
        self.assertGreaterEqual(client.connect_calls, 2)
        self.assertGreaterEqual(client.close_calls, 1)
        self.assertEqual(client.commands, ["BIV:1:0;", "XU;", "BIV:1:0;"])

    def test_stop_outputs_continues_best_effort_after_xu_timeout(self) -> None:
        client = CleanupContinuesAfterXuTimeoutClient()
        client.connect()

        with patch("smrt46_client.client.time.sleep", return_value=None):
            results = client.stop_outputs()

        self.assertEqual(
            client.commands,
            ["XU;", "V0C0,a0;", "QHS,", "C0,off,V0,off;", "V1,S,V2,S,V3,S,V4,S,C1,S,C2,S,C3,S;"],
        )
        self.assertEqual(
            [result.command for result in results],
            ["V0C0,a0;", "QHS,", "C0,off,V0,off;", "V1,S,V2,S,V3,S,V4,S,C1,S,C2,S,C3,S;"],
        )

    def test_execute_runtime_command_accepts_ok_for_qhs_ack(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket([b"OK;"])  # type: ignore[assignment]

        result = client._execute_runtime_command("QHS,")

        self.assertEqual(result.response, "OK")

    def test_query_max_limits_parses_typed_response(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ]
            }
        )
        client.connect()

        result = client.query_max_limits()

        self.assertEqual(result.voltage_limits, [300.0, 300.0, 300.0, 150.0])
        self.assertEqual(result.current_limits, [60.0, 60.0, 60.0])
        self.assertEqual(result.continuous_current_limits, [32.0, 32.0, 32.0])

    def test_query_all_parses_typed_snapshot(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "QRYALL;": [
                    "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
                    "I,1,11,3.0020,0.0193,0.000,60.000,1,21,5.0059,-0.0017,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
                    "BI,0000000000,BO,000000,EV,2,T,0.1208,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
                    "P8000,518,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.50,12,SMRT,SSF:NA,46.73,70.98;"
                ]
            }
        )
        client.connect()

        result = client.query_all()

        self.assertEqual(result.currents[0].amplitude, 3.002)
        self.assertEqual(result.currents[1].amplitude, 5.0059)
        self.assertEqual(result.event_count, 2)

    def test_query_all_retries_until_non_ack_payload(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "QRYALL;": [
                    "ACK;",
                    "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
                    "I,1,11,3.0020,0.0193,0.000,60.000,1,21,5.0059,-0.0017,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
                    "BI,0000000000,BO,000000,EV,2,T,0.1208,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
                    "P8000,518,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.50,12,SMRT,SSF:NA,46.73,70.98;",
                ]
            }
        )
        client.connect()

        result = client.query_all()

        self.assertEqual(result.currents[0].amplitude, 3.002)
        self.assertGreaterEqual(len(client.commands), 2)
        self.assertEqual(client.commands[0], "QRYALL;")
        self.assertIn(client.commands[1], {"QRYALL;", "QRYALL,"})

    def test_query_all_consumes_followup_frame_without_retransmit(self) -> None:
        client = Smrt46Client("127.0.0.1", logger=logging.getLogger("test"))
        client._sock = FakeSocket(
            [
                b"ACK;V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
                b"I,1,11,3.0020,0.0193,0.000,60.000,1,21,5.0059,-0.0017,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
                b"BI,0000000000,BO,000000,EV,2,T,0.1208,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
                b"P8000,518,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.50,12,SMRT,SSF:NA,46.73,70.98;"
            ]
        )  # type: ignore[assignment]

        result = client.query_all()

        self.assertEqual(result.currents[0].amplitude, 3.002)
        self.assertEqual(len(client._sock.sent), 1)  # type: ignore[union-attr]

    def test_configure_current_outputs_matches_manual_runtime_sequence(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "QHS,": ["ACK", "ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
                    "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
                    "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,P8000,125,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.00,12,SMRT,SSF:NA,44.26,67.15;"
                ],
            }
        )
        client.connect()

        results = client.configure_current_outputs(self._sample_request())

        self.assertEqual(
            [result.command for result in results],
            [
                "qg,",
                "HSU;",
                "QC;",
                "SYSSETF,",
                "SU;",
                "XU;",
                "QHS,",
                "RE;",
                "T01CAU,T01HD,T01AD,T02CAU,T02HD,T02AD,T03CAU,T03HD,T03AD,T04CAU,T04HD,T04AD,T05CAU,T05HD,T05AD,T06CAU,T06HD,T06AD,T07CAU,T07HD,T07AD,T08CAU,T08HD,T08AD,T09CAU,T09HD,T09AD,T10CAU,T10HD,T10AD,TR,",
                "t01m,t01sto,t01cal,VFMIN40E,VFMIN00O,,TR,",
                "OCA:ON,",
                "td2,DISON,HBOFF,HBV:OFF,v1,scale1.000,v2,scale1.000,v3,scale1.000,v4,scale1.000,c1,scale1.000,c2,scale1.000,c3,scale1.000,MAXV0.000000,MAXI0.000000,QHS,",
                "V1,DFLACON,DFLDCON,V2,DFLACON,DFLDCON,V3,DFLACON,DFLDCON,V4,DFLACON,DFLDCON,QHS,",
                "C1,DFLACON,DFLDCON,C2,DFLACON,DFLDCON,C3,DFLACON,DFLDCON;QHS,",
                "VASBAT0,T01AE:C0V0,parallel1,HEARTBEAT7,",
                "ldlg01,",
                "irigb0,iwfs0,",
                "QRYMAX;",
                "QRYALL;",
                "td2,t01m,t01cal,t01HD,TR,",
                "qg,",
                "v1,off,v2,p120.000,off,v3,p240.000,off,v4,off,c1,a3.0000,d0,p0.000,f60.000,on,c2,a5.0000,d0,p120.000,f60.000,on,c3,p240.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
                "WANYXXXXXXXXX1,",
                "TSOSTO,",
                "V0,OF,C0,OF,",
                "QHS,",
                ";",
            ],
        )

    def test_run_current_injection_returns_snapshot_and_alarm(self) -> None:
        _IDLE = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,P8000,125,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.00,12,SMRT,SSF:NA,44.26,67.15;"
        )
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE"],
                "QHS,": ["ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    _IDLE,  # consumed by bootstrap QRYALL;
                    _IDLE,  # initial_snapshot (amplitude=0.0)
                    "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
                    "I,1,11,3.0020,0.0193,0.000,60.000,1,21,5.0059,-0.0017,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
                    "BI,0000000000,BO,000000,EV,2,T,0.1208,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,P8000,518,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.50,12,SMRT,SSF:NA,46.73,70.98;",
                    "ERROR: Open circuit alarm  on C1 | ERROR: Open circuit alarm  on C2 | ",
                ],
            }
        )
        client.connect()

        result = client.run_current_injection(self._sample_request(), poll_count=2)

        self.assertEqual(result.initial_snapshot.currents[0].amplitude, 0.0)
        self.assertIsNotNone(result.final_snapshot)
        assert result.final_snapshot is not None
        self.assertEqual(result.final_snapshot.currents[0].amplitude, 3.002)
        self.assertEqual(result.alarms, ["Open circuit alarm  on C1", "Open circuit alarm  on C2"])
        self.assertFalse(result.trip_detected)
        self.assertEqual(result.history[-1]["phase"], "alarm")
        self.assertIn("qg,", result.command_sequence)

    def test_run_current_injection_rejects_non_validated_phase_scaffold(self) -> None:
        client = ScriptedSmrt46Client({})
        client.connect()
        request = Smrt46CurrentInjectionRequest(
            currents=[Smrt46CurrentChannelConfig(channel=1, amplitude=3.0, phase_deg=10.0)],
            frequency_hz=60.0,
        )

        with self.assertRaises(Smrt46ProtocolError):
            client.run_current_injection(request)

    def test_qhs_error_response_preserves_alarm_text(self) -> None:
        client = ScriptedSmrt46Client(
            {
                "QHS,": ["ERROR: Local generator amplifier over current on V1 | "],
            }
        )
        client.connect()

        with self.assertRaisesRegex(
            Smrt46ProtocolError,
            "Local generator amplifier over current on V1",
        ):
            client._execute_runtime_command("QHS,")

    def test_run_current_injection_loops_until_trip_detected(self) -> None:
        idle = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,125,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.00,12,SMRT,SSF:NA,44.26,67.15;"
        )
        tripped = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,120.000,0.000,0,30,0.0,0.0,240.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,1,11,3.0000,0.0050,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,1000000000,BO,000000,EV,2,T,0.4200,T01,0.4,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,170,P8k2,0,VDC,NA,BootCnt:50,DCAP0,Tmax,26.00,12,SMRT,SSF:NA,46.80,71.40;"
        )
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "QHS,": ["ACK", "ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [
                    idle,  # bootstrap QRYALL
                    idle,  # initial snapshot
                    tripped,  # first runtime poll detects trip
                ],
            }
        )
        client.connect()

        observed_snapshots: List[Smrt46StatusSnapshot] = []
        result = client.run_current_injection(
            self._sample_request(),
            poll_count=1,
            on_snapshot=observed_snapshots.append,
        )

        self.assertEqual(result.alarms, [])
        self.assertIsNotNone(result.final_snapshot)
        assert result.final_snapshot is not None
        self.assertEqual(result.final_snapshot.binary_inputs, "1000000000")
        self.assertTrue(result.trip_detected)
        self.assertEqual(result.history[0]["phase"], "initial")
        self.assertEqual(result.history[-1]["phase"], "runtime_poll")
        self.assertTrue(result.history[-1]["trip_detected"])
        self.assertEqual(len(observed_snapshots), 2)

    def test_run_voltage_injection_stops_on_binary_input(self) -> None:
        idle = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,4248,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,36.75,12,SMRT,SSF:NA,44.11,67.58;"
        )
        active = (
            "V,0,10,0.0,0.0,0.000,60.000,1,20,49.9984,-0.1955,120.000,60.000,0,30,0.0,0.0,240.000,60.000,0,40,0.0,0.0,0.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000000,BO,000000,EV,2,T,0.1121,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,4685,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.00,12,SMRT,SSF:NA,46.67,67.15;"
        )
        tripped = (
            "V,0,10,0.0,0.0,0.000,60.000,0,20,0.0,0.0,120.000,60.000,0,30,0.0,0.0,240.000,60.000,0,40,0.0,0.0,0.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000001,BO,000000,EV,0,T,1.2625,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,4320,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,36.75,12,SMRT,SSF:NA,44.33,65.03;"
        )
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "QHS,": ["ACK", "ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [idle, active, tripped],
            }
        )
        client.connect()
        request = Smrt46VoltageInjectionRequest(
            voltages=[
                Smrt46VoltageChannelConfig(
                    channel=2,
                    amplitude=50.0,
                    phase_deg=120.0,
                    frequency_hz=60.0,
                )
            ],
            frequency_hz=60.0,
            stop_mode="binary_input",
            target_bin=1,
            poll_interval_s=0.01,
            safety_timeout_s=2.0,
        )

        result = client.run_voltage_injection(request)

        self.assertEqual(result.stop_reason, "binary_input_closed")
        self.assertTrue(result.trip_detected)
        self.assertEqual(result.observed_peak_voltages[2], 49.9984)
        self.assertIsNotNone(result.final_snapshot)
        assert result.final_snapshot is not None
        self.assertEqual(result.final_snapshot.binary_inputs, "0000000001")
        self.assertIn(
            "v1,a0.0000,d0,p0.000,f60.000,off,v2,a50.0000,d0,p120.000,f60.000,on,v3,a0.0000,d0,p240.000,f60.000,off,v4,a0.0000,d0,p0.000,f60.000,off,c1,a0.0000,d0,p0.000,f60.000,off,c2,a0.0000,d0,p120.000,f60.000,off,c3,a0.0000,d0,p240.000,f60.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
            result.command_sequence,
        )

    def test_run_voltage_injection_stops_when_voltage_collapses_without_binary_input(self) -> None:
        idle = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1829,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,43.50,67.15;"
        )
        active = (
            "V,1,10,68.9980,0.0,0.000,60.000,0,20,0.0,0.0,120.000,60.000,0,30,0.0,0.0,240.000,60.000,0,40,0.0,0.0,0.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000000,BO,000000,EV,2,T,0.1121,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1880,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,46.67,67.15;"
        )
        collapsed = (
            "V,0,10,0.0,0.0,0.000,60.000,0,20,0.0,0.0,120.000,60.000,0,30,0.0,0.0,240.000,60.000,0,40,0.0,0.0,0.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.3000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1898,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,43.46,67.58;"
        )
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "QHS,": ["ACK", "ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [idle, active, collapsed],
            }
        )
        client.connect()
        request = Smrt46VoltageInjectionRequest(
            voltages=[
                Smrt46VoltageChannelConfig(
                    channel=1,
                    amplitude=69.0,
                    phase_deg=0.0,
                    frequency_hz=60.0,
                )
            ],
            frequency_hz=60.0,
            stop_mode="binary_input",
            target_bin=1,
            poll_interval_s=0.01,
            safety_timeout_s=5.0,
        )

        result = client.run_voltage_injection(request)

        self.assertEqual(result.stop_reason, "voltage_output_lost")
        self.assertFalse(result.trip_detected)
        self.assertEqual(result.observed_peak_voltages[1], 68.998)
        self.assertIn("Possible closed-circuit or overcurrent", result.notes[0])
        self.assertIsNotNone(result.final_snapshot)
        assert result.final_snapshot is not None
        self.assertEqual(result.final_snapshot.voltages[0].amplitude, 0.0)

    def test_run_voltage_injection_stops_when_voltage_never_starts(self) -> None:
        idle = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1829,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,43.50,67.15;"
        )
        still_zero = (
            "V,0,10,0.0,0.0,0.000,60.000,0,20,0.0,0.0,120.000,60.000,0,30,0.0,0.0,240.000,60.000,0,40,0.0,0.0,0.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.1500,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1898,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,43.46,67.58;"
        )
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "QHS,": ["ACK", "ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [idle, idle, still_zero],
            }
        )
        client.connect()
        request = Smrt46VoltageInjectionRequest(
            voltages=[
                Smrt46VoltageChannelConfig(
                    channel=1,
                    amplitude=69.0,
                    phase_deg=0.0,
                    frequency_hz=60.0,
                )
            ],
            frequency_hz=60.0,
            stop_mode="binary_input",
            target_bin=1,
            poll_interval_s=0.01,
            safety_timeout_s=5.0,
        )

        result = client.run_voltage_injection(request)

        self.assertEqual(result.stop_reason, "voltage_output_lost")
        self.assertEqual(result.observed_peak_voltages, {})
        self.assertIn("did not reach the requested amplitude", result.notes[0])
        self.assertIsNotNone(result.final_snapshot)
        assert result.final_snapshot is not None
        self.assertEqual(result.final_snapshot.voltages[0].amplitude, 0.0)

    def test_run_voltage_injection_prefers_output_lost_when_bi_closes_before_voltage(
        self,
    ) -> None:
        idle = (
            "V,0,10,0.0,0.0,0.000,0.000,0,20,0.0,0.0,0.000,0.000,0,30,0.0,0.0,0.000,0.000,0,40,0.0,0.0,360.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,0.000,60.000,0,31,0.0,0.0,0.000,60.000,"
            "BI,0000000000,BO,000000,EV,0,T,0.0000,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1829,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,43.50,67.15;"
        )
        closed_before_voltage = (
            "V,0,10,0.0,0.0,0.000,60.000,0,20,0.0,0.0,120.000,60.000,0,30,0.0,0.0,240.000,60.000,0,40,0.0,0.0,0.000,60.000,"
            "I,0,11,0.0,0.0,0.000,60.000,0,21,0.0,0.0,120.000,60.000,0,31,0.0,0.0,240.000,60.000,"
            "BI,0000000001,BO,000000,EV,0,T,0.1500,T01,0.0,T02,0.0,T03,0.0,T04,0.0,T05,0.0,T06,0.0,T07,0.0,T08,0.0,T09,0.0,T10,0.0,"
            "P8000,1898,P8k2,0,VDC,NA,BootCnt:100,DCAP0,Tmax,37.25,12,SMRT,SSF:NA,43.46,67.58;"
        )
        client = ScriptedSmrt46Client(
            {
                "qg,": ["GATE0000;", "GATE0000;"],
                "HSU;": ["HSU;"],
                "QC;": ["<G4>,<Model:SMRT46P>;"],
                "XU;": ["DONE", "DONE"],
                "QHS,": ["ACK", "ACK", "ACK", "ACK"],
                "QRYMAX;": [
                    "V,300.000,300.000,300.000,150.0000,I,60.000,60.000,60.000,conti,32.000,32.000,32.000;"
                ],
                "QRYALL;": [idle, idle, closed_before_voltage],
            }
        )
        client.connect()
        request = Smrt46VoltageInjectionRequest(
            voltages=[
                Smrt46VoltageChannelConfig(
                    channel=2,
                    amplitude=50.0,
                    phase_deg=120.0,
                    frequency_hz=60.0,
                )
            ],
            frequency_hz=60.0,
            stop_mode="binary_input",
            target_bin=1,
            poll_interval_s=0.01,
            safety_timeout_s=5.0,
        )

        result = client.run_voltage_injection(request)

        self.assertEqual(result.stop_reason, "voltage_output_lost")
        self.assertTrue(result.trip_detected)
        self.assertEqual(result.observed_peak_voltages, {})
        self.assertIn("before requested voltage was observed on: V2", result.notes[0])
