"""Offline regressions for provider outages; never use live ephemeris services."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch

from astropy.table import Table
from astroquery.jplhorizons.core import HorizonsClass
import requests

from scripts import fetch_ephemeris as fe
from scripts import generate_feed_6month as six


WHEN = datetime(2026, 10, 26, 10, tzinfo=timezone.utc)
BODY = {"name": "Mercury", "horizons_id": "199", "category": "core_bodies",
        "_provider_chain": ["horizons", "miriade", "swiss"]}
POSITION = {"longitude": 218.7, "latitude": -2.4, "distance": 1.08,
            "velocity": 46.6}


class ProviderRecoveryTests(unittest.TestCase):
    def setUp(self):
        # Isolate process-global breaker state from every other test/run.
        self.saved_failures = dict(fe._breaker_failures)
        fe._breaker_failures.clear()
        self.addCleanup(self.restore_breaker)
        for name, value in (("PROVIDER_RETRY_ATTEMPTS", 3),
                            ("PROVIDER_RETRY_BASE_DELAY", 2.0),
                            ("PROVIDER_BREAKER_THRESHOLD", 3)):
            patcher = patch.object(fe, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleep = patch.object(fe._time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def restore_breaker(self):
        fe._breaker_failures.clear()
        fe._breaker_failures.update(self.saved_failures)

    def test_horizons_http_200_error_is_not_replayed_from_cache(self):
        """Exercise real Astroquery request/cache code, with offline HTTP transport.

        The error response is parsed by the real Horizons parser. Only parsing
        of the successful fixture is stubbed, to avoid a huge unrelated table.
        This fails if ephemerides() reverts to its default cache=True: all
        retries then replay the first HTTP-200 error with one transport call.
        """
        def response(text):
            result = requests.Response()
            result.status_code = 200
            result._content = text.encode()
            result.url = "https://ssd.jpl.nasa.gov/api/horizons.api"
            result.request = requests.Request("GET", result.url).prepare()
            return result

        original_parse = HorizonsClass._parse_result

        def parse(query, result, *args, **kwargs):
            if result.text == "RECOVERED_TEST_EPHEMERIS":
                return Table({"ObsEclLon": [218.7], "ObsEclLat": [-2.4],
                              "RA_app": [215.5], "DEC_app": [-16.7],
                              "delta": [1.08], "vel_obs": [46.6]})
            return original_parse(query, result, *args, **kwargs)

        with TemporaryDirectory() as directory:
            def horizons(**kwargs):
                query = HorizonsClass(**kwargs)
                query.cache_location = Path(directory)
                return query

            with patch.object(fe, "Horizons", horizons), \
                 patch.object(HorizonsClass, "_parse_result", parse), \
                 patch.object(requests.Session, "request", side_effect=[
                     response("wldini(): missing required file L"),
                     response("RECOVERED_TEST_EPHEMERIS"),
                 ]) as transport:
                result = fe._compute_single("horizons", BODY, WHEN)["Mercury"]

        self.assertEqual(transport.call_count, 2)
        self.assertEqual(result["source"], "horizons")
        self.assertAlmostEqual(result["longitude"], 218.7)
        self.assertNotIn("longitude_speed", result)  # vel_obs is not zodiac speed.
        self.assertEqual(self.sleep.call_args_list, [call(2.0)])

    def test_remote_retry_backoff_recovers(self):
        loader = Mock(side_effect=[requests.Timeout("timeout"), None, POSITION])
        result = fe._call_with_retries("miriade", loader, BODY, WHEN)
        self.assertEqual(result, POSITION)
        self.assertEqual(loader.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [call(2.0), call(4.0)])
        self.assertEqual(fe._breaker_failures["miriade"], 0)

    def test_sixmonth_horizons_also_bypasses_error_cache(self):
        query = Mock()
        query.ephemerides.return_value = Table()
        with patch.object(six, "Horizons", return_value=query):
            self.assertEqual(six.fetch_horizons_range(BODY, [WHEN], {}), {})
        query.ephemerides.assert_called_once_with(cache=False)

    def test_permanent_outage_remains_unresolved_with_errors(self):
        with patch.object(fe, "_horizons_position", side_effect=ValueError("wldini outage")) as jpl, \
             patch.object(fe, "_miriade_position", side_effect=requests.HTTPError("502 Bad Gateway")) as miriade, \
             patch.object(fe, "_swiss_position", return_value=None) as swiss:
            result = fe._resolve_body(BODY, WHEN)["Mercury"]
        self.assertEqual(result["source"], "unresolved")
        for key in ("longitude", "latitude", "distance", "velocity"):
            self.assertIsNone(result[key])
        self.assertTrue(any("wldini outage" in error for error in result["errors"]))
        self.assertTrue(any("502 Bad Gateway" in error for error in result["errors"]))
        self.assertEqual((jpl.call_count, miriade.call_count, swiss.call_count), (3, 3, 1))

    def test_outage_falls_back_without_relabeling_provider(self):
        with patch.object(fe, "_horizons_position", side_effect=ValueError("wldini outage")), \
             patch.object(fe, "_miriade_position", side_effect=requests.HTTPError("502")), \
             patch.object(fe, "_swiss_position", return_value=POSITION):
            result = fe._resolve_body(BODY, WHEN)["Mercury"]
        self.assertEqual(result["source"], "swiss")
        self.assertEqual(result["longitude"], POSITION["longitude"])
        self.assertEqual(result["timestamp"], fe._utc_iso(WHEN))
        self.assertEqual(len(result["errors"]), 2)

    def test_breaker_limits_outage_retries_and_recovery_resets_it(self):
        fe._breaker_failures["horizons"] = fe.PROVIDER_BREAKER_THRESHOLD
        failed = Mock(side_effect=ValueError("still down"))
        with self.assertRaisesRegex(ValueError, "still down"):
            fe._call_with_retries("horizons", failed, BODY, WHEN)
        self.assertEqual(failed.call_count, 1)
        self.sleep.assert_not_called()
        recovered = Mock(return_value=POSITION)
        self.assertEqual(fe._call_with_retries("horizons", recovered, BODY, WHEN), POSITION)
        self.assertEqual(fe._breaker_failures["horizons"], 0)
        intermittent = Mock(side_effect=[requests.Timeout("retry again"), POSITION])
        self.assertEqual(fe._call_with_retries("horizons", intermittent, BODY, WHEN), POSITION)
        self.assertEqual(intermittent.call_count, 2)


if __name__ == "__main__":
    unittest.main()
