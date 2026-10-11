"""Tests for watchdog.py: the live-site checks and the issue it keeps, with the network faked."""
import datetime
import json
import unittest
from unittest import mock

import watchdog

NOW = datetime.datetime(2026, 10, 11, 12, 0, tzinfo=datetime.timezone.utc)


def iso(minutes_ago):
    return (NOW - datetime.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(minutes_ago, conclusion="success", status="completed"):
    return {"created_at": iso(minutes_ago), "status": status, "conclusion": conclusion, "html_url": "https://run"}


class Update(unittest.TestCase):
    def check(self, runs):
        with mock.patch.object(watchdog, "fetch", return_value=(200, json.dumps({"workflow_runs": runs}))):
            return watchdog.check_update(NOW, None)

    def test_healthy(self):
        self.assertEqual(self.check([run(5, None, "in_progress"), run(25), run(45, "failure")]), {})

    def test_failing_twice_in_a_row(self):
        out = self.check([run(5, None, "in_progress"), run(25, "failure"), run(45, "failure"), run(65)])
        self.assertIn("update: failing", out)
        self.assertIn("last 2", out["update: failing"])

    def test_stalled_schedule(self):
        self.assertIn("update: stalled", self.check([run(120), run(140)]))

    def test_api_down_is_not_a_problem(self):
        with mock.patch.object(watchdog, "fetch", return_value=(None, "timed out")):
            self.assertEqual(watchdog.check_update(NOW, None), {})


class Site(unittest.TestCase):
    PAGE = "<!doctype html><html><head>" + "x" * 2000 + '<script src="app.js?v=1a"></script></head></html>'

    def fake(self, pages):
        def fetch(url, **kw):
            path = url.replace(watchdog.SITE, "").split("?wd=")[0].split("&wd=")[0]
            return pages.get(path, (200, self.PAGE if not path.endswith(".json") else "{}"))
        return fetch

    def check(self, **pages):
        with mock.patch.object(watchdog, "fetch", side_effect=self.fake({k.replace("_", "/").replace("|", "."): v
                                                                         for k, v in pages.items()})):
            return watchdog.check_site(NOW)

    def test_all_good(self):
        out, today = self.check(**{"/today|json": (200, json.dumps({"gen": iso(12), "picks": []}))})
        self.assertEqual(out, {})
        self.assertEqual(today["picks"], [])

    def test_stale_data(self):
        out, _ = self.check(**{"/today|json": (200, json.dumps({"gen": iso(200)}))})
        self.assertIn("3 h 20 min old", out["fresh: today"])

    def test_missing_page_placeholder_bad_json_and_missing_asset(self):
        with mock.patch.object(watchdog, "fetch", side_effect=self.fake({
                "/games/": (404, "nope"),
                "/nhl.html": (200, self.PAGE.replace("xxxx", "__NHLDATA__", 1)),
                "/search.json": (200, '{"cut'),
                "/app.js?v=1a": (404, ""),
                "/today.json": (200, json.dumps({"gen": iso(1)}))})):
            out, _ = watchdog.check_site(NOW)
        self.assertEqual(sorted(out), ["assets: app.js?v=1a", "json: /search.json", "pages: /games/", "pages: /nhl.html"])

    def test_cut_off_page(self):
        with mock.patch.object(watchdog, "fetch", side_effect=self.fake({"/best/": (200, self.PAGE[:-10]),
                                                                         "/today.json": (200, json.dumps({"gen": iso(1)}))})):
            out, _ = watchdog.check_site(NOW)
        self.assertEqual(list(out), ["pages: /best/"])


class Render(unittest.TestCase):
    def test_picks_listed_but_no_cards_and_script_errors(self):
        doms = {"/": ('<b class="pc-who">', []), "/nfl.html": ("<p>empty</p>", []),
                "/nba.html": ("<p>off season</p>", []), "/nhl.html": ("", ["Uncaught TypeError: x (/app.js)"]),
                "/mlb.html": ('<b class="pc-who">', [])}
        with mock.patch.object(watchdog, "browser", return_value="chrome"), \
                mock.patch.object(watchdog, "render", side_effect=lambda exe, url: doms[url.replace(watchdog.SITE, "").split("?")[0]]):
            out = watchdog.check_render({"picks": [{"sport": "nfl"}, {"sport": "mlb"}]})
        self.assertEqual(sorted(out), ["render: /nfl.html", "render: /nhl.html"])   # NBA has no picks today: blank is fine
        self.assertIn("Uncaught TypeError", out["render: /nhl.html"])

    def test_console_filter(self):
        line = '[1:2:INFO:CONSOLE:5] "Uncaught ReferenceError: f is not defined", source: https://propstreaklab.com/app.js?v=1 (5)'
        m = watchdog.CONSOLE_RE.search(line)
        self.assertEqual(m.group(2), "https://propstreaklab.com/app.js?v=1")
        self.assertTrue(watchdog.JS_ERROR_RE.search(m.group(1)))
        self.assertTrue(watchdog.CONSOLE_IGNORE_RE.search("Error while trying to use the following icon from the Manifest"))


class Issue(unittest.TestCase):
    def calls(self, problems, open_issues):
        sent = []

        def fetch(url, token=None, method="GET", body=None, **kw):
            sent.append((method, url.replace(watchdog.API, ""), body))
            if method == "GET":
                return 200, json.dumps(open_issues)
            return (201 if method == "POST" else 200), json.dumps({"html_url": "u"})
        with mock.patch.object(watchdog, "fetch", side_effect=fetch):
            opened = watchdog.report(problems, NOW, "tok")
        return opened, [(m, u) for m, u, _ in sent[1:]], sent

    def issue(self, keys):
        return {"number": 7, "body": watchdog.issue_body({k: "m" for k in keys}, NOW)}

    def test_opens_one_issue_on_a_new_problem(self):
        opened, calls, sent = self.calls({"pages: /x": "broken"}, [{"number": 1, "body": "someone else's issue"}])
        self.assertTrue(opened)
        self.assertEqual(calls, [("POST", f"/repos/{watchdog.REPO}/issues")])
        self.assertIn('keys:["pages: /x"]', sent[1][2]["body"])

    def test_same_problems_leave_the_issue_alone(self):
        self.assertEqual(self.calls({"pages: /x": "broken"}, [self.issue(["pages: /x"])])[:2], (False, []))

    def test_changed_problems_update_and_comment(self):
        opened, calls, _ = self.calls({"pages: /y": "broken"}, [self.issue(["pages: /x"])])
        self.assertFalse(opened)
        self.assertEqual([m for m, _ in calls], ["PATCH", "POST"])

    def test_all_clear_closes_it(self):
        opened, calls, sent = self.calls({}, [self.issue(["pages: /x"])])
        self.assertEqual(calls, [("POST", f"/repos/{watchdog.REPO}/issues/7/comments"), ("PATCH", f"/repos/{watchdog.REPO}/issues/7")])
        self.assertEqual(sent[-1][2]["state"], "closed")

    def test_nothing_wrong_and_no_issue_does_nothing(self):
        self.assertEqual(self.calls({}, [])[:2], (False, []))


if __name__ == "__main__":
    unittest.main()
