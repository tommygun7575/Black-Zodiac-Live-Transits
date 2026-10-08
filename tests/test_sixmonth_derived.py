"""Six-month derived layer + generic transit-to-natal engine (synthetic data)."""
import unittest
from datetime import datetime, timedelta, timezone

from scripts.sixmonth_derived import (
    detect_stations,
    finite_difference_speed,
    sample_times,
    station_eligible,
    wrap180,
)
from scripts.transit_to_natal import _series_for_signature, load_rules

T0 = datetime(2026, 10, 7, 18, 57, 5, tzinfo=timezone.utc)


class TestSixMonthDerived(unittest.TestCase):
    def test_wrap180(self):
        self.assertAlmostEqual(-2.0, wrap180(359.0 - 1.0))
        self.assertAlmostEqual(2.0, wrap180(1.0 - 359.0))

    def test_speed_central_and_edges_across_wrap(self):
        L = [358.0, 359.0, 0.0, 1.0, 2.0]
        sp, meth = finite_difference_speed(L)
        for s in sp:
            self.assertAlmostEqual(1.0, s)
        self.assertEqual(["forward_one_sided", "central", "central", "central", "backward_one_sided"], meth)

    def test_sample_times_preserve_time_of_day(self):
        payload = {"meta": {"range_utc": [T0.isoformat(), (T0 + timedelta(days=2)).isoformat()]},
                   "transits": {"2026-10-07": {}, "2026-10-08": {}, "2026-10-09": {}}}
        keys, times, mism = sample_times(payload)
        self.assertEqual([], mism)
        self.assertEqual((18, 57, 5), (times[1].hour, times[1].minute, times[1].second))

    def test_station_detection_quadratic(self):
        tv = 20.3  # true station (days from T0)
        L = [(100.0 + 0.004 * (i - tv) ** 2) % 360 for i in range(41)]  # minimum => station direct
        times = [T0 + timedelta(days=i) for i in range(41)]
        sp, _ = finite_difference_speed(L)
        st = detect_stations("Saturn", L, sp, times)
        self.assertEqual(1, len(st))
        self.assertEqual("station_direct", st[0]["station_type"])
        got = datetime.fromisoformat(st[0]["timestamp_utc"].replace("Z", "+00:00"))
        self.assertLess(abs((got - (T0 + timedelta(days=tv))).total_seconds()), 600)
        self.assertAlmostEqual(100.0, st[0]["longitude"], places=4)
        L2 = [(50.0 - 0.004 * (i - tv) ** 2) % 360 for i in range(41)]
        sp2, _ = finite_difference_speed(L2)
        self.assertEqual("station_retrograde", detect_stations("Mars", L2, sp2, times)[0]["station_type"])

    def test_station_eligibility(self):
        self.assertFalse(station_eligible("Regulus", "fixed_stars"))
        self.assertFalse(station_eligible("Aetheric_Jovian_Arc", "aether_points"))
        for b in ("Sun", "Moon", "True_Node", "Mean_Node", "South_Node"):
            self.assertFalse(station_eligible(b, "core_bodies"))
        self.assertTrue(station_eligible("Eris", "dwarf_planets"))

    def test_transit_to_natal_single_hit_window(self):
        n = 30
        times = [T0 + timedelta(days=i) for i in range(n)]
        LT = [(10.0 + 1.0 * i) % 360 for i in range(n)]   # 1 deg/day direct
        SP = [1.0] * n
        r = _series_for_signature("Sun", "Mars", "conjunction", 1, 2.0, LT, SP, 25.5, times, [], load_rules(), 0.1, 30.0)
        self.assertEqual(1, r["exact_pass_count"])
        hit = datetime.fromisoformat(r["exact_passes_utc"][0].replace("Z", "+00:00"))
        self.assertLess(abs((hit - (T0 + timedelta(days=15.5))).total_seconds()), 60)
        w = r["windows"][0]
        self.assertEqual("applying", w["entry_motion"])
        self.assertEqual("separating", w["exit_motion"])
        ent = datetime.fromisoformat(w["entry_utc"].replace("Z", "+00:00"))
        self.assertLess(abs((ent - (T0 + timedelta(days=13.5))).total_seconds()), 60)


if __name__ == "__main__":
    unittest.main()
