"""
Regression tests: every figure quoted in docs/ must be reproducible from the
evidence file. Run with:  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from ulog_forensic_extractor import ULog, analyse, file_hashes  # noqa: E402

EVIDENCE = os.path.join(ROOT, "evidence", "ulog", "12127aab-02aa-4e98-890a-f17523ebba0c.ulg")
SHA256 = "68d1020f688109f027dba08d2950247cc0ae34aaefdcf37e4a7d60838f3e1aa3"


class TestEvidenceIntegrity(unittest.TestCase):
    def test_sha256_matches_evidence_register(self):
        self.assertEqual(file_hashes(EVIDENCE)["sha256"], SHA256)


class TestULogFindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = ULog(EVIDENCE)
        cls.r = analyse(cls.log)

    def test_container(self):
        self.assertEqual(self.log.version, 1)
        self.assertEqual(len(self.log.params), 980)
        self.assertEqual(len(self.log.data), 70)
        self.assertEqual(self.r["log"]["truncated_bytes"], 0)
        self.assertAlmostEqual(self.r["log"]["logging_duration_s"], 7.324, places=2)
        self.assertEqual(self.r["log"]["total_dropout_ms"], 30)

    def test_system_identification(self):
        s = self.r["system"]
        self.assertEqual(s["hardware"], "CUBEPILOT_CUBEORANGE")
        self.assertEqual(s["firmware_release"], "1.11.2")
        self.assertEqual(s["firmware_branch"], "v1.11.2_w_rc_sysid")
        self.assertEqual(s["vehicle_uuid"], "000600000000383638393239510d0035002d")
        self.assertEqual(s["airframe_id"], 13014)
        self.assertAlmostEqual(s["vehicle_life_flight_time_s"], 22035.4, places=0)  # 6 h 7 min 15 s

    def test_wall_clock(self):
        self.assertTrue(self.r["time_reference"]["log_start_utc"].startswith("2021-04-21 06:30:57"))

    def test_gnss(self):
        g = self.r["gnss"]
        self.assertAlmostEqual(g["first_fix"]["lat"], 63.4170622, places=6)
        self.assertAlmostEqual(g["first_fix"]["lon"], 10.4082151, places=6)
        self.assertEqual(g["satellites_used"]["min"], 14)
        self.assertLess(g["hdop"]["max"], 1.0)
        self.assertIn("MAX_HORZ_ERR (eph > EKF2_REQ_EPH)", self.r["estimator"]["gps_checks_failed"])
        self.assertFalse(self.r["kinematics"]["horizontal_position_valid_any"])

    def test_operator_control(self):
        v = self.r["vehicle_status"]
        self.assertEqual([s for _, s in v["nav_state_transitions"]], ["MANUAL"])
        self.assertFalse(self.r["rc_input"]["rc_lost_any"])
        self.assertFalse(self.r["rc_input"]["rc_failsafe_any"])
        self.assertEqual(self.r["mission"]["waypoint_count"], 0)

    def test_event_sequence(self):
        msgs = [m["message"] for m in self.r["logged_messages"]]
        self.assertEqual(msgs, ["[commander] Takeoff detected", "[commander] Landing detected",
                                "[commander] Disarmed by landing"])

    def test_no_safety_circuit_breakers(self):
        p = self.r["parameters_of_interest"]
        for k in ("CBRK_SUPPLY_CHK", "CBRK_USB_CHK", "CBRK_IO_SAFETY", "CBRK_AIRSPD_CHK"):
            self.assertEqual(p[k], 0, k)
        self.assertEqual(p["COM_ARM_WO_GPS"], 1)


if __name__ == "__main__":
    unittest.main()
