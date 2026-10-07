"""Frame regression: every body must be GEOCENTRIC apparent ecliptic OF DATE.

Guards against the July-Oct 2026 bug where Black Zodiac published astroquery
"EclLon"/"EclLat" (Horizons quantity 18 = HELIOCENTRIC) as geocentric
longitudes (Moon == Sun+180, Mercury 92 deg from the Sun), and against J2000
(equinox-of-epoch) values that run ~0.37 deg low in 2026.
"""

import datetime
import unittest
from unittest.mock import patch

from scripts import fetch_ephemeris as fe
from scripts import generate_feed_6month as six
from scripts.utils import frames

UTC = datetime.timezone.utc
REF_DT = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

# JPL Horizons OBSERVER QUANTITIES='31', CENTER='500@399', 2026-10-07 12:00 UTC
JPL_Q31 = {
    "Mercury": 218.7987,
    "Venus": 218.1449,
    "Moon": 155.1954,
    "Mars": 125.4335,
    "Jupiter": 140.7246,
}
TOL = 0.05


def arc(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


class _FakeColumn(list):
    pass


class _FakeTable:
    """Minimal astropy-table stand-in returned by Horizons().ephemerides()."""

    def __init__(self, cols):
        self._cols = {k: _FakeColumn([v]) for k, v in cols.items()}
        self.colnames = list(cols)

    def __len__(self):
        return 1

    def __getitem__(self, key):
        return self._cols[key]


class _FakeHorizons:
    TIMEOUT = 30
    table = None

    def __init__(self, *args, **kwargs):
        pass

    def ephemerides(self, *args, **kwargs):
        return _FakeHorizons.table


class FrameRegressionTests(unittest.TestCase):
    def test_swiss_matches_jpl_q31_reference(self):
        sun = fe._swiss_position({"name": "Sun"}, REF_DT)["longitude"]
        for name, ref in JPL_Q31.items():
            lon = fe._swiss_position({"name": name}, REF_DT)["longitude"]
            self.assertLess(arc(lon, ref), TOL, f"{name}: {lon} vs JPL {ref}")
        merc = fe._swiss_position({"name": "Mercury"}, REF_DT)["longitude"]
        venus = fe._swiss_position({"name": "Venus"}, REF_DT)["longitude"]
        self.assertLessEqual(arc(merc, sun), 28.0)
        self.assertLessEqual(arc(venus, sun), 48.0)

    def test_horizons_uses_obsecl_q31_not_heliocentric_eclon(self):
        # Real Horizons values for Mercury 2026-10-07 12:00 UTC.
        _FakeHorizons.table = _FakeTable({
            "EclLon": 285.785,      # q18 heliocentric — must be ignored
            "EclLat": -5.9143,
            "ObsEclLon": 218.7987123,
            "ObsEclLat": -2.4681873,
            "RA": 215.22389, "DEC": -16.64683,          # astrometric J2000
            "RA_app": 215.58932, "DEC_app": -16.76878,  # apparent of date
            "delta": 1.0833771736626,
            "vel_obs": 46.67,
        })
        with patch.object(fe, "Horizons", _FakeHorizons):
            pos = fe._horizons_position({"name": "Mercury", "horizons_id": "199",
                                         "category": "core_bodies"}, REF_DT)
        self.assertLess(arc(pos["longitude"], JPL_Q31["Mercury"]), TOL)
        self.assertAlmostEqual(pos["declination"], -16.76878, places=4)
        self.assertAlmostEqual(pos["right_ascension"], 215.58932, places=4)

    def test_horizons_sun_masked_eclon_falls_back_to_apparent_radec_of_date(self):
        _FakeHorizons.table = _FakeTable({
            "RA": 192.76415, "DEC": -5.47033,
            "RA_app": 193.10702, "DEC_app": -5.61478,
            "delta": 0.9995,
        })
        with patch.object(fe, "Horizons", _FakeHorizons):
            pos = fe._horizons_position({"name": "Sun", "horizons_id": "10",
                                         "category": "core_bodies"}, REF_DT)
        # JPL q31 Sun = 194.2396 (J2000 RA/DEC would give ~193.87)
        self.assertLess(arc(pos["longitude"], 194.2396), TOL)

    def test_six_month_extract_prefers_obsecl(self):
        row = {"EclLon": 85.4188, "EclLat": 0.9649,
               "ObsEclLon": 107.7522664, "ObsEclLat": 1.0188716}
        lon, lat = six._extract_lon_lat(row, list(row), REF_DT)
        self.assertAlmostEqual(lon, 107.7522664, places=6)
        self.assertAlmostEqual(lat, 1.0188716, places=6)
        # heliocentric-only rows are rejected outright
        self.assertIsNone(six._extract_lon_lat({"EclLon": 1.0, "EclLat": 0.0},
                                               ["EclLon", "EclLat"], REF_DT))

    def test_fixed_star_precessed_to_of_date(self):
        pos = frames.fixed_star_of_date("Aldebaran", 68.9801625, 16.5093028,
                                        frames.jd_ut(REF_DT))
        self.assertLess(arc(pos["longitude"], 70.169), TOL)
        # precession fallback (no Swiss catalog name) agrees too
        fb = frames.fixed_star_of_date("NoSuchStarXYZ", 68.9801625, 16.5093028,
                                       frames.jd_ut(REF_DT))
        self.assertLess(arc(fb["longitude"], 70.169), TOL)

    def test_miriade_sexagesimal_ecliptic_parse(self):
        lon, lat = frames.miriade_row_lon_lat(
            {"longitude": "+218:47:55.13162", "latitude": "-02:28:10.6779"})
        self.assertLess(arc(lon, JPL_Q31["Mercury"]), TOL)
        self.assertAlmostEqual(lat, -2.4696, places=3)
        self.assertEqual(frames.MIRIADE_APPARENT_OF_DATE_PARAMS["-teph"], "2")

    def test_deprecated_vector_batch_parser_emits_nothing(self):
        text = "Target body name: Mercury (199)\n$$SOE\nX = 1 Y = 1 Z = 0\n$$EOE"
        self.assertEqual({}, fe._parse_horizons_vector_batch(text, {"199": "Mercury"}))

    def test_observer_q31_batch_parser(self):
        text = (" Date__(UT)__HR:MN, , ,    ObsEcLon,   ObsEcLat,\n"
                "$$SOE\n 2026-Oct-07 12:00, , , 218.7987123, -2.4681873,\n$$EOE\n")
        parsed = fe._parse_horizons_observer_q31(text)
        self.assertAlmostEqual(parsed["longitude"], 218.7987123, places=6)


if __name__ == "__main__":
    unittest.main()
