import datetime
import math
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

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

    # ------------------------------------------------------------------
    # Provider routing efficiency (capability-based provider chains)
    # ------------------------------------------------------------------

    def test_body_without_jpl_mapping_never_calls_horizons(self):
        """A body with no horizons_id must not include 'jpl' in its chain,
        and resolve_moving_body must never call fetch_horizons_range."""
        body = {
            "name": "MiriadeOnlyBody",
            "provider_priority": ["horizons", "miriade", "swiss"],
            # No horizons_id present at all.
            "miriade_name": "a:MiriadeOnlyBody",
        }
        chain = six._provider_chain(body)
        self.assertNotIn("jpl", chain)
        self.assertIn("miriade", chain)

        body["_provider_chain"] = chain
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)]
        stats = {
            "jpl_range_requests": 0, "jpl_range_failures": 0, "jpl_retries": 0, "jpl_timeouts": 0,
            "miriade_fallback_requests": 0, "miriade_range_requests": 0, "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        with patch.object(six, "fetch_horizons_range") as jpl_mock, \
             patch.object(six, "fetch_miriade_range", return_value={"2026-01-01": {"ecl_lon_deg": 1.0, "ecl_lat_deg": 0.0, "source": "miriade"}}), \
             patch.object(six, "fetch_swiss_point", return_value=None):
            six.resolve_moving_body(body, dt_list, stats)

        jpl_mock.assert_not_called()

    def test_body_without_miriade_mapping_never_calls_miriade(self):
        """If a body has no name and no miriade_name, Miriade must be
        excluded from its chain and never invoked."""
        body = {
            "name": "",
            "provider_priority": ["horizons", "miriade", "swiss"],
            "horizons_id": "12345",
        }
        chain = six._provider_chain(body)
        self.assertNotIn("miriade", chain)

    def test_body_without_swiss_support_never_calls_swiss(self):
        """A body with no swiss_code and no SWISS_IDS entry must exclude
        'swiss' from its chain and resolve_moving_body must never call
        fetch_swiss_point for it."""
        body = {
            "name": "Hygiea",  # not in SWISS_IDS, no swiss_code in this test
            "provider_priority": ["horizons", "miriade", "swiss"],
            "horizons_id": "10;",
            "miriade_name": "a:Hygiea",
        }
        chain = six._provider_chain(body)
        self.assertNotIn("swiss", chain)

        body["_provider_chain"] = chain
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)]
        stats = {
            "jpl_range_requests": 0, "jpl_range_failures": 0, "jpl_retries": 0, "jpl_timeouts": 0,
            "miriade_fallback_requests": 0, "miriade_range_requests": 0, "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        with patch.object(six, "fetch_horizons_range", return_value={}), \
             patch.object(six, "fetch_miriade_range", return_value={}), \
             patch.object(six, "fetch_swiss_point") as swiss_mock:
            six.resolve_moving_body(body, dt_list, stats)

        swiss_mock.assert_not_called()

    def test_provider_chain_calculated_from_actual_mappings_not_guesses(self):
        # Has swiss_code explicitly -> swiss included.
        body_with_swiss = {
            "name": "Chiron",
            "provider_priority": ["miriade", "horizons", "swiss"],
            "horizons_id": "2060",
            "miriade_name": "a:Chiron",
            "swiss_code": 15,
        }
        self.assertEqual(["miriade", "jpl", "swiss"], six._provider_chain(body_with_swiss))

        # No swiss_code and name not in SWISS_IDS -> swiss excluded.
        body_without_swiss = {
            "name": "Pholus",
            "provider_priority": ["miriade", "horizons", "swiss"],
            "horizons_id": "5145",
            "miriade_name": "a:Pholus",
        }
        self.assertEqual(["miriade", "jpl"], six._provider_chain(body_without_swiss))

    def test_valid_jpl_first_bodies_remain_jpl_first(self):
        body = {
            "name": "Sun",
            "provider_priority": ["horizons", "miriade", "swiss"],
            "horizons_id": "10",
            "miriade_name": "p:Sun",
            "swiss_code": 0,
        }
        chain = six._provider_chain(body)
        self.assertEqual(["jpl", "miriade", "swiss"], chain)
        self.assertEqual("jpl_primary", six._classify_provider_route(chain))

    def test_miriade_primary_bodies_skip_jpl_completely_when_unmapped(self):
        """A body whose provider_priority lists miriade first AND has no
        JPL mapping must skip JPL entirely (not merely deprioritize it)."""
        body = {
            "name": "Hekate",
            "provider_priority": ["miriade", "horizons", "swiss"],
            # Intentionally no horizons_id.
            "miriade_name": "a:Hekate",
        }
        chain = six._provider_chain(body)
        self.assertEqual(["miriade"], chain)
        self.assertEqual("miriade_primary", six._classify_provider_route(chain))

    def test_body_with_no_valid_providers_creates_missing_diagnostics_without_network_calls(self):
        body = {
            "name": "GhostBody",
            "_provider_chain": [],  # simulates no valid configured provider
        }
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(3)]
        stats = {
            "jpl_range_requests": 0, "jpl_range_failures": 0, "jpl_retries": 0, "jpl_timeouts": 0,
            "miriade_fallback_requests": 0, "miriade_range_requests": 0, "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

        with patch.object(six, "fetch_horizons_range") as jpl_mock, \
             patch.object(six, "fetch_miriade_range") as miriade_mock, \
             patch.object(six, "fetch_swiss_point") as swiss_mock:
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        jpl_mock.assert_not_called()
        miriade_mock.assert_not_called()
        swiss_mock.assert_not_called()
        self.assertEqual({}, resolved)
        self.assertEqual(3, len(missing))
        for entry in missing:
            self.assertEqual("GhostBody", entry["body"])
            self.assertEqual([], entry["providers_attempted"])
        self.assertEqual(1, stats["provider_route_counts"]["no_valid_provider"])

    def test_routing_calculated_once_per_body_not_per_date(self):
        """_provider_chain must be invoked once at catalog-load time, not
        once per date during range resolution."""
        call_count = {"n": 0}
        original = six._provider_chain

        def counting_provider_chain(body):
            call_count["n"] += 1
            return original(body)

        with patch.object(six, "_provider_chain", side_effect=counting_provider_chain):
            moving, _, _ = six.load_catalog_targets(six.CATALOG_PATH)

        # Exactly one call per moving body in the catalog (41), never per date.
        self.assertEqual(len(moving), call_count["n"])
        self.assertEqual(41, call_count["n"])

        # resolve_moving_body itself never recomputes the chain.
        body = moving[0]
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(5)]
        stats = {
            "jpl_range_requests": 0, "jpl_range_failures": 0, "jpl_retries": 0, "jpl_timeouts": 0,
            "miriade_fallback_requests": 0, "miriade_range_requests": 0, "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }
        with patch.object(six, "_provider_chain") as chain_mock, \
             patch.object(six, "fetch_horizons_range", return_value={k: {"ecl_lon_deg": 1.0, "ecl_lat_deg": 0.0, "source": "jpl"} for k in [six._date_key(d) for d in dt_list]}):
            six.resolve_moving_body(body, dt_list, stats)
        chain_mock.assert_not_called()

    def test_full_catalog_provider_route_distribution(self):
        """Sanity-check the real catalog's routing distribution: every one
        of the 41 bodies currently has a valid horizons_id mapping, so none
        are routed away from JPL by this change — but the classification
        must still be computed correctly from real catalog fields."""
        moving, _, _ = six.load_catalog_targets(six.CATALOG_PATH)
        self.assertEqual(41, len(moving))

        routes = {"jpl_primary": 0, "miriade_primary": 0, "swiss_primary": 0, "no_valid_provider": 0}
        for body in moving:
            chain = body["_provider_chain"]
            routes[six._classify_provider_route(chain)] += 1

        self.assertEqual(0, routes["no_valid_provider"])
        self.assertEqual(41, routes["jpl_primary"] + routes["miriade_primary"] + routes["swiss_primary"])
        # Every body in the current catalog carries a horizons_id, so JPL is
        # never dropped from a chain that requests it — this test guards
        # against accidentally excluding still-valid JPL mappings.
        for body in moving:
            if body.get("horizons_id"):
                self.assertIn("jpl", body["_provider_chain"])

    def test_gap_only_fallback_keeps_valid_primary(self):
        body = {"name": "Test", "_provider_chain": ["jpl", "miriade", "swiss"]}
        dt_list = [
            datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 1, 3, tzinfo=datetime.timezone.utc),
        ]
        stats = {
            "jpl_range_requests": 0,
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
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
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
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
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
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
        self.assertEqual("3", kwargs["params"]["-nbd"])
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
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
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

    # ------------------------------------------------------------------
    # JPL Horizons timeout / retry behavior
    # ------------------------------------------------------------------

    def _make_body_dt_list(self, name="Gonggong", days=3):
        body = {"name": name, "_horizons_id": "225088;"}
        dt_list = [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i) for i in range(days)]
        return body, dt_list

    def _fresh_stats(self):
        return {
            "jpl_range_requests": 0,
            "jpl_range_failures": 0,
            "jpl_retries": 0,
            "jpl_timeouts": 0,
            "miriade_fallback_requests": 0,
            "miriade_range_requests": 0,
            "miriade_points_resolved": 0,
            "swiss_fallback_requests": 0,
        }

    def test_horizons_request_receives_finite_timeout(self):
        """The actual astroquery HTTP call must be bounded by a finite
        timeout, applied via astroquery.conf.timeout (the supported
        mechanism), not merely defined and unused."""
        body, dt_list = self._make_body_dt_list()
        stats = self._fresh_stats()

        fake_eph = MagicMock()
        fake_eph.colnames = []
        fake_eph.__len__.return_value = 0

        with patch.object(six, "Horizons", return_value=MagicMock(ephemerides=MagicMock(return_value=fake_eph))), \
             patch.object(six.astroquery_conf, "timeout", 0):
            six.fetch_horizons_range(body, dt_list, stats)
            self.assertEqual(six.REQUEST_TIMEOUT_HORIZONS, six.astroquery_conf.timeout)
            self.assertTrue(math.isfinite(six.REQUEST_TIMEOUT_HORIZONS))
            self.assertGreaterEqual(six.REQUEST_TIMEOUT_HORIZONS, 20)
            self.assertLessEqual(six.REQUEST_TIMEOUT_HORIZONS, 30)

    def test_jpl_timeout_does_not_abort_generator_and_falls_back_to_miriade(self):
        """A stalled/timed-out Horizons call must be caught, recorded, and
        must not raise out of resolve_moving_body — Miriade must still run."""
        body, dt_list = self._make_body_dt_list()
        body["_provider_chain"] = ["jpl", "miriade", "swiss"]
        stats = self._fresh_stats()

        def raise_timeout(*_args, **_kwargs):
            raise socket.timeout("timed out")

        miriade_called = {"count": 0}

        def fake_miriade_range(_body, _missing_dates, _stats):
            miriade_called["count"] += 1
            return {}

        with patch.object(six, "Horizons", side_effect=raise_timeout), \
             patch.object(six, "fetch_miriade_range", side_effect=fake_miriade_range), \
             patch.object(six, "fetch_swiss_point", return_value=None), \
             patch.object(six.time, "sleep", return_value=None):
            # Should not raise.
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        self.assertEqual(1, miriade_called["count"])
        self.assertEqual({}, resolved)
        self.assertEqual(len(dt_list), len(missing))

    def test_jpl_timeout_triggers_at_most_configured_retry_count(self):
        """One initial attempt + at most JPL_RETRY_ATTEMPTS-1 retries; the
        request must remain range-level (one call per attempt, not per-date)."""
        body, dt_list = self._make_body_dt_list(days=182)
        stats = self._fresh_stats()

        call_count = {"n": 0}

        def raise_timeout(*_args, **_kwargs):
            call_count["n"] += 1
            raise socket.timeout("timed out")

        with patch.object(six, "Horizons", side_effect=raise_timeout), \
             patch.object(six.time, "sleep", return_value=None):
            result = six.fetch_horizons_range(body, dt_list, stats)

        self.assertEqual({}, result)
        # Range-level: total Horizons() constructions == JPL_RETRY_ATTEMPTS,
        # never per-date (which would be 182).
        self.assertEqual(six.JPL_RETRY_ATTEMPTS, call_count["n"])
        self.assertLess(call_count["n"], len(dt_list))
        self.assertEqual(six.JPL_RETRY_ATTEMPTS, stats["jpl_range_requests"])
        self.assertEqual(six.JPL_RETRY_ATTEMPTS - 1, stats["jpl_retries"])
        self.assertEqual(six.JPL_RETRY_ATTEMPTS, stats["jpl_timeouts"])
        self.assertEqual(1, stats["jpl_range_failures"])

    def test_jpl_success_on_retry_does_not_count_as_failure(self):
        body, dt_list = self._make_body_dt_list(days=3)
        stats = self._fresh_stats()

        fake_eph = MagicMock()
        fake_eph.colnames = []
        fake_eph.__len__.return_value = 0

        attempts = {"n": 0}

        def flaky_horizons(*_args, **_kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise socket.timeout("timed out")
            return MagicMock(ephemerides=MagicMock(return_value=fake_eph))

        with patch.object(six, "Horizons", side_effect=flaky_horizons), \
             patch.object(six.time, "sleep", return_value=None):
            result = six.fetch_horizons_range(body, dt_list, stats)

        self.assertEqual({}, result)  # empty eph, but no failure state
        self.assertEqual(2, attempts["n"])
        self.assertEqual(1, stats["jpl_timeouts"])
        self.assertEqual(1, stats["jpl_retries"])
        self.assertEqual(0, stats["jpl_range_failures"])

    def test_non_timeout_jpl_exception_also_falls_back_gracefully(self):
        body, dt_list = self._make_body_dt_list(days=5)
        body["_provider_chain"] = ["jpl", "miriade", "swiss"]
        stats = self._fresh_stats()

        def raise_generic(*_args, **_kwargs):
            raise ValueError("some non-network parsing error")

        with patch.object(six, "Horizons", side_effect=raise_generic), \
             patch.object(six, "fetch_miriade_range", return_value={}) as miriade_mock, \
             patch.object(six, "fetch_swiss_point", return_value=None), \
             patch.object(six.time, "sleep", return_value=None):
            resolved, missing = six.resolve_moving_body(body, dt_list, stats)

        self.assertEqual({}, resolved)
        self.assertGreaterEqual(miriade_mock.call_count, 1)
        self.assertEqual(1, stats["jpl_range_failures"])

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
        self.assertIn("jpl_range_failures", data["runtime"])
        self.assertIn("jpl_retries", data["runtime"])
        self.assertIn("jpl_timeouts", data["runtime"])
        self.assertIn("provider_route_counts", data["runtime"])

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
