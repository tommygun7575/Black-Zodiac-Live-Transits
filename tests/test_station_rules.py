"""Station / motion classification rules (2026-10-08 transit workflow rules).

* fixed stars: station=False, motion_status='fixed' (zero motion is never a station)
* Aether points, Sun, Moon, lunar nodes: never station events
* only longitude_speed drives motion; velocity is never used
* null longitude_speed stays unresolved (no fabrication)
"""
import unittest

from scripts.utils.celestial_math import (
    classify_position_motion,
    collect_stations,
    enrich_motion_fields,
    is_station_eligible,
    position_longitude_speed,
)


def _pos(**kw):
    base = {"longitude": 10.0, "latitude": 0.0, "distance": 1.0, "source": "horizons"}
    base.update(kw)
    return base


class TestStationRules(unittest.TestCase):
    def test_fixed_star_never_station(self):
        star = _pos(source="fixed_star_catalog", category="fixed_stars", velocity=0.0, longitude_speed=0.0)
        m = classify_position_motion("Regulus", star)
        self.assertFalse(m["station"])
        self.assertEqual("fixed", m["motion_status"])
        self.assertFalse(m["retrograde"])
        self.assertFalse(is_station_eligible("Regulus", star))

    def test_aether_never_station(self):
        a = _pos(source="calculated", category="aether_points", velocity=0.0, longitude_speed=None)
        m = classify_position_motion("Aetheric_Jovian_Arc", a)
        self.assertIs(m["station"], False)
        self.assertEqual("unresolved", m["motion_status"])
        a2 = dict(a, longitude_speed=0.0)
        self.assertIs(classify_position_motion("Aetheric_Jovian_Arc", a2)["station"], False)

    def test_sun_moon_nodes_not_station_eligible(self):
        for name, cat in (("Sun", "core_bodies"), ("Moon", "core_bodies"), ("True_Node", "lunar_nodes"),
                          ("Mean_Node", "lunar_nodes"), ("South_Node", "lunar_nodes")):
            m = classify_position_motion(name, _pos(category=cat, longitude_speed=0.0001))
            self.assertFalse(m["station"], name)
            self.assertFalse(m["station_eligible"], name)
        node = classify_position_motion("True_Node", _pos(category="lunar_nodes", source="swiss", longitude_speed=-0.05))
        self.assertTrue(node["retrograde"])
        self.assertEqual("retrograde", node["motion_status"])

    def test_eligible_body_can_station(self):
        m = classify_position_motion("Mercury", _pos(category="core_bodies", longitude_speed=0.001))
        self.assertTrue(m["station"])
        self.assertEqual("station", m["motion_status"])
        r = classify_position_motion("Saturn", _pos(category="core_bodies", longitude_speed=-0.03))
        self.assertTrue(r["retrograde"])
        self.assertFalse(r["station"])

    def test_velocity_never_used_as_longitude_speed(self):
        p = _pos(source="swiss", category="centaurs", velocity=-0.5)
        self.assertIsNone(position_longitude_speed(p))
        p = _pos(source="horizons", category="core_bodies", velocity=29.8)
        self.assertIsNone(position_longitude_speed(p))

    def test_null_speed_stays_unresolved(self):
        m = classify_position_motion("Eris", _pos(category="dwarf_planets", velocity=28.2, longitude_speed=None))
        self.assertEqual("unresolved", m["motion_status"])
        self.assertIsNone(m["retrograde"])
        self.assertIsNone(m["station"])
        self.assertIsNone(m["longitude_speed"])
        self.assertEqual(["weekly_6h_difference", "six_month_series"], m["motion_fallback_available"])

    def test_enrich_does_not_touch_positions(self):
        raw = {
            "Regulus": _pos(longitude=150.2, latitude=0.46, source="fixed_star_catalog", category="fixed_stars",
                            velocity=0.0, longitude_speed=0.0, declination=11.8, right_ascension=152.4),
            "Eris": _pos(longitude=25.5, latitude=-10.5, velocity=28.2, longitude_speed=None,
                         category="dwarf_planets", declination=0.06, right_ascension=27.4),
        }
        out = enrich_motion_fields(raw)
        for name in raw:
            for key in ("longitude", "latitude", "distance", "velocity", "declination", "right_ascension"):
                self.assertEqual(raw[name][key], out[name][key])

    def test_collect_stations_excludes_stars_and_nodes(self):
        positions = enrich_motion_fields({
            "Regulus": _pos(source="fixed_star_catalog", category="fixed_stars", velocity=0.0, longitude_speed=0.0),
            "True_Node": _pos(source="swiss", category="lunar_nodes", longitude_speed=-0.05),
            "Pluto": _pos(category="core_bodies", longitude_speed=-0.01),
            "Eris": _pos(category="dwarf_planets", longitude_speed=None),
        })
        st = collect_stations(positions)
        bodies = [i["body"] for i in st["items"]]
        self.assertEqual(["Pluto"], bodies)
        self.assertEqual(0, st["station_events_count"])
        self.assertFalse(st["true_station_source"])
        self.assertEqual(1, st["unresolved_motion_count"])
        self.assertEqual(["True_Node"], [i["body"] for i in st["excluded_node_motion"]])


if __name__ == "__main__":
    unittest.main()
