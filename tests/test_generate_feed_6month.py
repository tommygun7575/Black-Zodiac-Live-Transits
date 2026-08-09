import datetime
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import generate_feed_6month as six


class TestGenerateFeed6Month(unittest.TestCase):
    def test_daily_samples_exactly_182(self):
        start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        samples = six._daily_samples(start, six.SAMPLE_DAYS)
        self.assertEqual(182, len(samples))
        self.assertEqual(start.date(), samples[0].date())
        self.assertEqual((start + datetime.timedelta(days=181)).date(), samples[-1].date())

    def test_catalog_driven_moving_population_matches_expected(self):
        moving, fixed, aether = six.load_catalog_targets(six.CATALOG_PATH)
        moving_names = {b["name"] for b in moving}
        expected = {
            "Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
            "Ceres", "Eris", "Haumea", "Makemake",
            "Pallas", "Juno", "Vesta", "Hygiea",
            "Eros", "Psyche", "Sappho", "Hekate", "Nemesis", "Karma", "Destinn", "Aura", "Merlin",
            "Chiron", "Pholus", "Nessus", "Chariklo", "Hylonome", "Asbolus",
            "Orcus", "Quaoar", "Sedna", "Gonggong", "Ixion", "Varuna", "Huya", "Salacia",
        }
        self.assertEqual(expected, moving_names)
        self.assertEqual(41, len(moving_names))
        self.assertIn("Regulus", set(fixed))
        self.assertIn("Aetheric_SunMoon_Midpoint", set(aether))

    def test_small_body_ids_preserve_semicolons(self):
        chiron = {"name": "Chiron", "category": "centaurs", "horizons_id": "2060"}
        self.assertEqual("2060;", six._normalize_horizons_id(chiron))
        ceres = {"name": "Ceres", "category": "dwarf_planets", "horizons_id": "1;"}
        self.assertEqual("1;", six._normalize_horizons_id(ceres))

    def test_invalid_nan_and_inf_are_rejected(self):
        row = {"EclLon": float("nan"), "EclLat": 1.0}
        self.assertIsNone(six._extract_lon_lat(row, ["EclLon", "EclLat"], datetime.datetime.now(datetime.timezone.utc)))
        row = {"EclLon": 1.0, "EclLat": float("inf")}
        self.assertIsNone(six._extract_lon_lat(row, ["EclLon", "EclLat"], datetime.datetime.now(datetime.timezone.utc)))

    def test_longitude_normalization(self):
        self.assertTrue(0.0 <= six._normalize_lon(-1.0) < 360.0)
        self.assertTrue(0.0 <= six._normalize_lon(721.0) < 360.0)

    def test_group_contiguous_dates_single_run(self):
        dts = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(5)]
        groups = six._group_contiguous_dates(dts)
        self.assertEqual(1, len(groups))
        self.assertEqual(5, len(groups[0]))

    def test_group_contiguous_dates_split_runs(self):
        base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        dts = [base, base + datetime.timedelta(days=1), base + datetime.timedelta(days=5), base + datetime.timedelta(days=6)]
        groups = six._group_contiguous_dates(dts)
        self.assertEqual(2, len(groups))
        self.assertEqual(2, len(groups[0]))
        self.assertEqual(2, len(groups[1]))

    def test_gap_only_fallback_keeps_valid_primary(self):
        body = {"name": "Test", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [
            datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 3, tzinfo=datetime.timezone.utc),
        ]
        stats = {
            "jpl_range_requests": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        def fake_jpl(_body, _dt_list, _stats):
            return {
                "2026-01-01": {"ecl_lon_deg": 10.0, "ecl_lat_deg": 0.1, "source": "jpl"},
                "2026-01-03": {"ecl_lon_deg": 30.0, "ecl_lat_deg": 0.3, "source": "jpl"},
            }

        def fake_miriade_range(_body, missing_dates, _stats):
            # Only 2026-01-02 should be requested (a single-date contiguous group)
            self.assertEqual(1, len(missing_dates))
            self.assertEqual("2026-01-02", missing_dates[0].strftime("%Y-%m-%d"))
            return {"2026-01-02": {"ecl_lon_deg": 20.0, "ecl_lat_deg": 0.2, "source": "miriade"}}

        with patch.object(six, "fetch_horizons_range", side_effect=fake_jpl), \
             patch.object(six, "fetch_miriade_range", side_effect=fake_miriade_range) as miriade_mock, \
             patch.object(six, "fetch_swiss_point", return_value=None) as swiss_mock:
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        self.assertEqual(3, len(resolved))
        self.assertEqual("jpl", resolved["2026-01-01"]["source"])
        self.assertEqual("jpl", resolved["2026-01-03"]["source"])
        self.assertEqual("miriade", resolved["2026-01-02"]["source"])
        self.assertEqual(1, miriade_mock.call_count)
        self.assertEqual(0, swiss_mock.call_count)
        self.assertEqual([], missing)

    def test_missing_diagnostics_and_attempted_providers(self):
        body = {"name": "MissingBody", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)]
        stats = {
            "jpl_range_requests": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        with patch.object(six, "fetch_horizons_range", return_value={}), \
             patch.object(six, "fetch_miriade_range", return_value={}), \
             patch.object(six, "fetch_swiss_point", return_value=None):
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        self.assertEqual({}, resolved)
        self.assertEqual(1, len(missing))
        self.assertEqual(["JPL", "Miriade", "Swiss"], missing[0]["providers_attempted"])

    def test_182_missing_dates_cause_one_miriade_range_request(self):
        """The core performance fix: a body missing all 182 days must trigger
        exactly ONE Miriade range request, not 182 individual HTTP calls."""
        body = {"name": "FullyMissing", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(182)]
        stats = {
            "jpl_range_requests": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        request_log = []

        def fake_miriade_range(_body, missing_dates, _stats):
            request_log.append(len(missing_dates))
            return {}

        with patch.object(six, "fetch_horizons_range", return_value={}), \
             patch.object(six, "fetch_miriade_range", side_effect=fake_miriade_range) as miriade_mock, \
             patch.object(six, "fetch_swiss_point", return_value=None):
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        # Exactly one call (one contiguous range covering all 182 days).
        self.assertEqual(1, miriade_mock.call_count)
        self.assertEqual([182], request_log)
        self.assertEqual(182, len(missing))

    def test_fetch_miriade_range_maps_rows_to_correct_dates(self):
        body = {"name": "Vesta", "miriade_name": "a:Vesta"}
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(3)]
        stats = {"miriade_fallback_requests": 0, "miriade_range_requests": 0, "miriade_points_resolved": 0}

        fake_payload = {
            "result": {
                "data": [
                    {"ELon": "10.0", "ELat": "1.0"},
                    {"ELon": "20.0", "ELat": "2.0"},
                    {"ELon": "30.0", "ELat": "3.0"},
                ]
            }
        }

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return fake_payload

        with patch.object(six.requests, "get", return_value=FakeResponse()) as get_mock:
            results = six.fetch_miriade_range(body, dt_list, stats)

        self.assertEqual(1, get_mock.call_count)
        _, kwargs = get_mock.call_args
        self.assertEqual("182" if False else "3", kwargs["params"]["-nbd"])
        self.assertEqual("1d", kwargs["params"]["-step"])
        self.assertEqual(3, len(results))
        self.assertEqual(10.0, results["2026-01-01"]["ecl_lon_deg"])
        self.assertEqual(20.0, results["2026-01-02"]["ecl_lon_deg"])
        self.assertEqual(30.0, results["2026-01-03"]["ecl_lon_deg"])
        for entry in results.values():
            self.assertEqual("miriade", entry["source"])
        self.assertEqual(1, stats["miriade_range_requests"])
        self.assertEqual(1, stats["miriade_fallback_requests"])
        self.assertEqual(3, stats["miriade_points_resolved"])

    def test_swiss_only_receives_dates_unresolved_after_miriade(self):
        body = {"name": "Test", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [
            datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 3, tzinfo=datetime.timezone.utc),
        ]
        stats = {
            "jpl_range_requests": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        def fake_miriade_range(_body, missing_dates, _stats):
            # Resolve only the first of the three missing dates.
            first_key = missing_dates[0].strftime("%Y-%m-%d")
            return {first_key: {"ecl_lon_deg": 5.0, "ecl_lat_deg": 0.5, "source": "miriade"}}

        swiss_calls = []

        def fake_swiss(_body, dt, _stats):
            swiss_calls.append(dt.strftime("%Y-%m-%d"))
            return {"ecl_lon_deg": 1.0, "ecl_lat_deg": 0.0, "source": "swiss"}

        with patch.object(six, "fetch_horizons_range", return_value={}), \
             patch.object(six, "fetch_miriade_range", side_effect=fake_miriade_range), \
             patch.object(six, "fetch_swiss_point", side_effect=fake_swiss):
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        self.assertEqual(3, len(resolved))
        self.assertEqual(["2026-01-02", "2026-01-03"], sorted(swiss_calls))
        self.assertEqual([], missing)

    def test_coverage_counts_exclude_fixed_and_aether(self):
        fake_moving = [{"name": "BodyA", "_provider_chain": ["jpl"]}, {"name": "BodyB", "_provider_chain": ["jpl"]}]
        fixed = ["Regulus"]
        aether = ["Aetheric_SunMoon_Midpoint"]

        def fake_resolve(body, dt_list, stats):
            keys = [d.strftime("%Y-%m-%d") for d in dt_list]
            if body["name"] == "BodyA":
                return {k: {"ecl_lon_deg": 1.0, "ecl_lat_deg": 0.0, "source": "jpl"} for k in keys}, []
            return {}, [{"date": k, "body": "BodyB", "providers_attempted": ["JPL"]} for k in keys]

        with patch.object(six, "load_catalog_targets", return_value=(fake_moving, fixed, aether)), \
             patch.object(six, "load_fixed_stars_for_catalog", return_value={"Regulus": {"ecl_lon_deg": 10.0, "ecl_lat_deg": 1.0, "source": "fixed"}}), \
             patch.object(six, "resolve_moving_body", side_effect=fake_resolve):
            data, _ = six.generate_six_month_feed(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))

        self.assertEqual(182 * 2, data["total_points"])
        self.assertEqual(182, data["resolved_points"])
        self.assertTrue(math.isclose(data["coverage"], 182 / (182 * 2)))
        one_day = next(iter(data["transits"].values()))
        self.assertIn("Regulus", one_day)
        self.assertIn("Aetheric_SunMoon_Midpoint", one_day)

    def test_structure_is_transits_date_body(self):
        fake_moving = [{"name": "BodyA", "_provider_chain": ["jpl"]}]

        with patch.object(six, "load_catalog_targets", return_value=(fake_moving, [], [])), \
             patch.object(six, "load_fixed_stars_for_catalog", return_value={}), \
             patch.object(six, "resolve_moving_body", return_value=({"2026-01-01": {"ecl_lon_deg": 1.0, "ecl_lat_deg": 0.0, "source": "jpl"}}, [])):
            data, _ = six.generate_six_month_feed(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))

        self.assertIn("transits", data)
        self.assertIsInstance(data["transits"], dict)
        self.assertIn("2026-01-01", data["transits"])
        self.assertIn("BodyA", data["transits"]["2026-01-01"])
        self.assertIn("miriade_range_requests", data["runtime"])
        self.assertIn("miriade_points_resolved", data["runtime"])

    def test_atomic_write_preserves_existing_file_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "output.json"
            out.write_text('{"ok":true}', encoding="utf-8")
            with self.assertRaises(TypeError):
                six.write_output_atomic(out, {"bad": {1, 2, 3}})
            self.assertEqual('{"ok":true}', out.read_text(encoding="utf-8"))

    def test_range_request_not_per_date(self):
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(5)]
        fake_moving = [
            {"name": "BodyA", "_provider_chain": ["jpl"]},
            {"name": "BodyB", "_provider_chain": ["jpl"]},
        ]

        call_counter = {"count": 0}

        def fake_resolve(body, passed_dt_list, stats):
            self.assertEqual(len(dt_list), len(passed_dt_list))
            call_counter["count"] += 1
            keys = [d.strftime("%Y-%m-%d") for d in passed_dt_list]
            return {k: {"ecl_lon_deg": 1.0, "ecl_lat_deg": 0.0, "source": "jpl"} for k in keys}, []

        with patch.object(six, "SAMPLE_DAYS", 5), \
             patch.object(six, "load_catalog_targets", return_value=(fake_moving, [], [])), \
             patch.object(six, "load_fixed_stars_for_catalog", return_value={}), \
             patch.object(six, "resolve_moving_body", side_effect=fake_resolve):
            data, _ = six.generate_six_month_feed(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))

        self.assertEqual(2, call_counter["count"])
        self.assertEqual(5, len(data["transits"]))


if __name__ == "__main__":
    unittest.main()
