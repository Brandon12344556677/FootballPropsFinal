"""Tests for dashboard_check.py: the team dashboard's page, encrypted numbers and feeds, network faked."""
import datetime
import json
import unittest
from unittest import mock

import dashboard_check as D
import team_stats

NOW = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=datetime.timezone.utc)
PW = "test-password"


def rng():
    return {k: ([] if k != "total" else 5) for k in D.RANGE_KEYS}


def snap(hours_ago=1, drop=None):
    s = {"generated_at": (NOW - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for r in D.RANGES:
        s[r] = rng()
    if drop:
        del s["d7"][drop]
    return team_stats.encrypt(json.dumps(s), PW)


def fake(files):
    def fetch(url, **kw):
        path = url.replace(D.SITE, "").split("?wd=")[0].split("&wd=")[0]
        return files.get(path, (404, ""))
    return fetch


class Stats(unittest.TestCase):
    def run_with(self, blob, password=PW):
        with mock.patch.object(D, "fetch", side_effect=fake({"/team/stats.enc": (200, blob)})):
            return D.check_stats(NOW, password)

    def test_good(self):
        self.assertEqual(self.run_with(snap()), ({}, []))

    def test_stale_missing_and_wrong_password(self):
        self.assertIn("19 hours old", self.run_with(snap(hours_ago=19))[0]["stats: fresh"])
        self.assertIn("d7.views", self.run_with(snap(drop="views"))[0]["stats: contents"])
        self.assertIn("stats: decrypt", self.run_with(snap(), password="nope")[0])

    def test_not_an_encrypted_file_and_no_password(self):
        self.assertIn("stats: file", self.run_with("<html>404</html>")[0])
        out, notes = self.run_with(snap(), password="")
        self.assertEqual(out, {})
        self.assertIn("not checked", notes[0])


class Edges(unittest.TestCase):
    def run_with(self, hours_ago, strategies=True, graded_hours_ago=None, picks=True):
        gen = (NOW - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        blob = team_stats.encrypt(json.dumps({"generated_at": gen, "strategies": [{"key": "x"}] if strategies else []}), PW)
        files = {"/team/edges.enc": (200, blob)}
        if picks:
            rows = [] if graded_hours_ago is None else                 [["hit", (NOW - datetime.timedelta(hours=graded_hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")]]
            files["/nhl_picks_recent.json"] = (200, json.dumps({"cols": ["res", "start"], "picks": rows}))
        with mock.patch.object(D, "fetch", side_effect=fake(files)):
            return D.check_edges(NOW, PW)

    def test_fresh_stale_and_empty(self):
        self.assertEqual(self.run_with(1), {})
        self.assertIn("edges: fresh", self.run_with(12, graded_hours_ago=8))   # a game graded since: should have been rebuilt
        self.assertIn("edges: contents", self.run_with(0, strategies=False))

    def test_a_quiet_stretch_is_not_stale(self):
        self.assertEqual(self.run_with(11), {})                      # no games graded since the last rebuild
        self.assertEqual(self.run_with(11, graded_hours_ago=3), {})  # a game that may not be graded yet
        self.assertEqual(self.run_with(11, graded_hours_ago=14), {}) # graded before the last rebuild

    def test_no_picks_files_falls_back_to_a_long_limit(self):
        self.assertEqual(self.run_with(30, picks=False), {})
        self.assertIn("edges: fresh", self.run_with(80, picks=False))


class Page(unittest.TestCase):
    def test_missing_parts_and_script(self):
        html = '<form id="lockForm"></form><input id="pw"><div id="app"></div><script src="ads.js?v=1"></script>'
        with mock.patch.object(D, "fetch", side_effect=fake({"/team/": (200, html)})), \
                mock.patch.object(D.watchdog, "browser", return_value=None):
            out = D.check_page()
        self.assertIn("views", out["page: parts"])
        self.assertIn("page: ads.js?v=1", out)


class Feeds(unittest.TestCase):
    def test_today_fields(self):
        doc = {k: [] for k in D.TODAY_KEYS}
        with mock.patch.object(D, "fetch", side_effect=fake({"/today.json": (200, json.dumps(doc))})):
            self.assertEqual(D.check_feeds(), {})
        del doc["live"]
        with mock.patch.object(D, "fetch", side_effect=fake({"/today.json": (200, json.dumps(doc))})):
            self.assertIn("live", D.check_feeds()["feeds: today"])


if __name__ == "__main__":
    unittest.main()
