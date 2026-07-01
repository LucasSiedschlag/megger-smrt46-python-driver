import unittest

from smrt46_client.protocol import (
    build_current_bootstrap_sequence,
    build_current_cleanup_sequence,
    build_current_injection_sequence,
    build_current_output_vector_command,
    build_simulated_trip_command,
    build_voltage_injection_sequence,
    build_voltage_output_vector_command,
)
from smrt46_client.protocol import (
    normalize_command as normalize_smrt46_command,
)


class ProtocolTests(unittest.TestCase):
    def test_smrt46_command_normalization_preserves_comma_style(self) -> None:
        self.assertEqual(normalize_smrt46_command("QC;"), "QC;")
        self.assertEqual(normalize_smrt46_command("QG,"), "QG,")
        self.assertEqual(normalize_smrt46_command("QVER"), "QVER;")

    def test_smrt46_bootstrap_sequence_matches_manual_driver_log(self) -> None:
        self.assertEqual(
            build_current_bootstrap_sequence(),
            [
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
            ],
        )

    def test_smrt46_current_vector_matches_manual_test_1(self) -> None:
        self.assertEqual(
            build_current_output_vector_command([3.0, None, None]),
            "v1,off,v2,p120.000,off,v3,p240.000,off,v4,off,c1,a3.0000,d0,p0.000,f60.000,on,c2,p120.000,off,c3,p240.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
        )

    def test_smrt46_current_vector_matches_manual_test_2(self) -> None:
        self.assertEqual(
            build_current_output_vector_command([0.0, 5.0, None]),
            "v1,off,v2,p120.000,off,v3,p240.000,off,v4,off,c1,a0.0000,d0,p0.000,off,c2,a5.0000,d0,p120.000,f60.000,on,c3,p240.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
        )

    def test_smrt46_current_vector_matches_manual_test_3(self) -> None:
        self.assertEqual(
            build_current_output_vector_command([3.0, 5.0, None]),
            "v1,off,v2,p120.000,off,v3,p240.000,off,v4,off,c1,a3.0000,d0,p0.000,f60.000,on,c2,a5.0000,d0,p120.000,f60.000,on,c3,p240.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
        )

    def test_smrt46_current_injection_sequence_matches_manual_driver_shape(self) -> None:
        self.assertEqual(
            build_current_injection_sequence([3.0, 5.0, None]),
            [
                "v1,off,v2,p120.000,off,v3,p240.000,off,v4,off,c1,a3.0000,d0,p0.000,f60.000,on,c2,a5.0000,d0,p120.000,f60.000,on,c3,p240.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
                "WANYXXXXXXXXX1,",
                "TSOSTO,",
                "V0,OF,C0,OF,",
                "QHS,",
                ";",
            ],
        )

    def test_smrt46_voltage_vector_matches_v2_driver_log(self) -> None:
        self.assertEqual(
            build_voltage_output_vector_command([None, 50.0, None, None]),
            "v1,a0.0000,d0,p0.000,f60.000,off,v2,a50.0000,d0,p120.000,f60.000,on,v3,a0.0000,d0,p240.000,f60.000,off,v4,a0.0000,d0,p0.000,f60.000,off,c1,a0.0000,d0,p0.000,f60.000,off,c2,a0.0000,d0,p120.000,f60.000,off,c3,a0.0000,d0,p240.000,f60.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
        )

    def test_smrt46_voltage_injection_sequence_matches_driver_shape(self) -> None:
        self.assertEqual(
            build_voltage_injection_sequence([None, 50.0, None, None]),
            [
                "v1,a0.0000,d0,p0.000,f60.000,off,v2,a50.0000,d0,p120.000,f60.000,on,v3,a0.0000,d0,p240.000,f60.000,off,v4,a0.0000,d0,p0.000,f60.000,off,c1,a0.0000,d0,p0.000,f60.000,off,c2,a0.0000,d0,p120.000,f60.000,off,c3,a0.0000,d0,p240.000,f60.000,off,TRL,TSOSTA,BO010,BO020,BO030,BO040,BO050,BO060,",
                "WANYXXXXXXXXX1,",
                "TSOSTO,",
                "V0,OF,C0,OF,",
                "QHS,",
                ";",
            ],
        )

    def test_smrt46_simulated_trip_command_matches_voltage_simulation_log(self) -> None:
        self.assertEqual(build_simulated_trip_command(), "XQ;")

    def test_smrt46_cleanup_sequence_matches_manual_driver_log(self) -> None:
        self.assertEqual(
            build_current_cleanup_sequence(),
            [
                "XU;",
                "V0C0,a0;",
                "QHS,",
                "C0,off,V0,off;",
                "V1,S,V2,S,V3,S,V4,S,C1,S,C2,S,C3,S;",
            ],
        )


if __name__ == "__main__":
    unittest.main()
