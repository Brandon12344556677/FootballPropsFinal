"""Tests for start_run.py: a dispatch counts only once the new run really started."""
import datetime
import unittest
from unittest import mock

import start_run as S

T0 = datetime.datetime(2026, 11, 11, 20, 18, tzinfo=datetime.timezone.utc)


def run(created, status, conclusion=None):
    return {"created_at": created, "status": status, "conclusion": conclusion}


class VerdictTest(unittest.TestCase):
    def test_new_runs(self):
        since = T0
        self.assertEqual(S.verdict([], since), "none")
        self.assertEqual(S.verdict([run("2026-11-11T20:17:00Z", "completed", "success")], since), "none")   # older run
        self.assertEqual(S.verdict([run("2026-11-11T20:18:13Z", "queued")], since), "ok")
        self.assertEqual(S.verdict([run("2026-11-11T20:18:13Z", "completed", "startup_failure")], since), "failed")
        self.assertEqual(S.verdict([run("2026-11-11T20:18:13Z", "completed", "startup_failure"),
                                    run("2026-11-11T20:18:20Z", "in_progress")], since), "ok")


class StartTest(unittest.TestCase):
    def go(self, responses):
        """responses: what _req returns, in order."""
        it = iter(responses)
        calls = []

        def fake(url, token, data=None):
            calls.append(("POST" if data is not None else "GET", url))
            return next(it)
        with mock.patch.object(S, "_req", fake):
            ok = S.start("update.yml", {"chain": "1"}, "o/r", "t", sleep=lambda s: None, now=lambda: T0)
        return ok, [c[0] for c in calls]

    def test_confirmed_first_try(self):
        ok, calls = self.go([(204, None), (200, {"workflow_runs": [run("2026-11-11T20:18:05Z", "queued")]})])
        self.assertTrue(ok)
        self.assertEqual(calls, ["POST", "GET"])

    def test_startup_failure_asks_again(self):
        ok, calls = self.go([(204, None), (200, {"workflow_runs": [run("2026-11-11T20:18:05Z", "completed", "startup_failure")]}),
                             (204, None), (200, {"workflow_runs": [run("2026-11-11T20:18:40Z", "pending")]})])
        self.assertTrue(ok)
        self.assertEqual(calls, ["POST", "GET", "POST", "GET"])

    def test_refused_then_ok(self):
        ok, calls = self.go([(500, None), (204, None), (200, {"workflow_runs": [run("2026-11-11T20:18:05Z", "in_progress")]})])
        self.assertTrue(ok)

    def test_every_try_fails(self):
        ok, _ = self.go([(500, None)] * len(S.WAITS))
        self.assertFalse(ok)

    def test_no_run_appears_then_asks_again(self):
        polls = [(200, {"workflow_runs": []})] * (S.CONFIRM_SEC // S.POLL_SEC)
        ok, calls = self.go([(204, None)] + polls + [(204, None), (200, {"workflow_runs": [run("2026-11-11T20:19:00Z", "queued")]})])
        self.assertTrue(ok)
        self.assertEqual(calls.count("POST"), 2)


if __name__ == "__main__":
    unittest.main()
