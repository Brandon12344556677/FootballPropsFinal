"""Tests for team_stats.py: GoatCounter row cleanup and the encryption the /team/ page decrypts."""
import json
import os
import shutil
import tempfile
import unittest

import team_stats


class Rows(unittest.TestCase):
    def test_sizes_named_from_id(self):
        out = team_stats.rows([{"id": "phone", "name": "", "count": 5}, {"id": "desktophd", "name": "", "count": 1}], "sizes")
        self.assertEqual([r["name"] for r in out], ["Phone", "Large computer screen"])

    def test_blank_referrer_is_unknown_and_keeps_scheme(self):
        out = team_stats.rows([{"name": "", "count": 60, "ref_scheme": "o"}], "toprefs")
        self.assertEqual(out, [{"name": "(unknown)", "n": 60, "kind": "o"}])

    def test_named_rows_pass_through(self):
        out = team_stats.rows([{"id": "US", "name": "United States", "count": 224}], "locations")
        self.assertEqual(out, [{"name": "United States", "n": 224}])


class TimeOnPage(unittest.TestCase):
    def test_ranges_in_order_with_zeros(self):
        events = [{"path": "time/1-3m", "count": 4, "event": True}, {"path": "/time/0-10s", "count": 9, "event": True},
                  {"path": "time/bogus", "count": 2, "event": True}, {"path": "other-event", "count": 1, "event": True}]
        out = team_stats.time_rows(events)
        self.assertEqual([r["name"] for r in out], team_stats.TIME_RANGES)
        self.assertEqual({r["name"]: r["n"] for r in out}["0-10s"], 9)
        self.assertEqual({r["name"]: r["n"] for r in out}["1-3m"], 4)
        self.assertEqual(sum(r["n"] for r in out), 13)

    def test_no_time_events_is_empty(self):
        self.assertEqual(team_stats.time_rows([]), [])

    def test_events_kept_out_of_visits(self):
        responses = {
            "/stats/total": {"total": 10, "total_events": 4,
                             "stats": [{"day": "2026-10-10", "daily": 10, "hourly": [0] * 23 + [10]}]},
            "/stats/hits": {"hits": [
                {"path": "/", "count": 6, "event": False, "stats": []},
                {"path": "time/1-3m", "count": 4, "event": True,
                 "stats": [{"day": "2026-10-10", "daily": 4, "hourly": [0] * 23 + [4]}]}]},
        }
        old = team_stats.get
        team_stats.get = lambda token, path, **q: responses.get(path, {"stats": []})
        try:
            r = team_stats.range_stats("t", team_stats.dt.datetime(2026, 10, 10, 23), 1)
        finally:
            team_stats.get = old
        self.assertEqual(r["total"], 6)
        self.assertEqual(r["daily"], [{"day": "2026-10-10", "n": 6}])
        self.assertEqual(r["hourly"][-1], 6)
        self.assertEqual([p["path"] for p in r["pages"]], ["/"])
        self.assertEqual({t["name"]: t["n"] for t in r["time"]}["1-3m"], 4)


@unittest.skipUnless(shutil.which("openssl"), "openssl not installed")
class Crypto(unittest.TestCase):
    def setUp(self):
        self.iter = team_stats.ITERATIONS
        team_stats.ITERATIONS = 1000  # fast; the format is the same
        self.dir = tempfile.mkdtemp()
        self.out = team_stats.OUT
        team_stats.OUT = os.path.join(self.dir, "stats.enc")

    def tearDown(self):
        team_stats.ITERATIONS = self.iter
        team_stats.OUT = self.out
        shutil.rmtree(self.dir)

    def test_round_trip_in_openssl_salted_format(self):
        blob = team_stats.encrypt('{"a":1}', "pw")
        import base64
        self.assertTrue(base64.b64decode(blob).startswith(b"Salted__"))  # the header the page reads
        self.assertEqual(team_stats.decrypt(blob, "pw"), '{"a":1}')

    def test_wrong_password_fails(self):
        blob = team_stats.encrypt('{"a":1}' * 20, "pw")
        with self.assertRaises(Exception):  # bad padding (openssl exits non-zero) or garbage that isn't JSON
            json.loads(team_stats.decrypt(blob, "nope"))

    def test_unchanged_ignores_timestamp(self):
        snap = {"generated_at": "2026-10-10T00:00:00Z", "d1": {"total": 3}}
        with open(team_stats.OUT, "w") as f:
            f.write(team_stats.encrypt(json.dumps(snap), "pw"))
        self.assertTrue(team_stats.unchanged(dict(snap, generated_at="2026-10-10T01:00:00Z"), "pw"))
        self.assertFalse(team_stats.unchanged(dict(snap, d1={"total": 4}), "pw"))
        self.assertFalse(team_stats.unchanged(snap, "other"))


class Skip(unittest.TestCase):
    def test_no_secrets_does_nothing(self):
        old = {k: os.environ.pop(k, None) for k in ("GOATCOUNTER_TOKEN", "TEAM_DASH_PASSWORD")}
        try:
            self.assertEqual(team_stats.main(), 0)
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
