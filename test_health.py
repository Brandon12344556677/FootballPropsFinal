import os
import tempfile
import unittest

import health


class FromLogsTest(unittest.TestCase):
    def logs(self, **files):
        d = tempfile.mkdtemp()
        for name, text in files.items():
            with open(os.path.join(d, name + ".log"), "w", encoding="utf-8") as f:
                f.write(text)
        return health.from_logs(d)

    def test_polymarket_global_list_gone_is_a_note_not_a_problem(self):
        out = self.logs(build_nhl="  polymarket (global): event list not available from Polymarket (404); Polymarket US prices still used\n",
                        build_nba="  polymarket: skipped (HTTP Error 500: Internal Server Error)\n")
        self.assertEqual(list(out), ["build_nba: polymarket"])     # the 404 note is fine; any other error still shows

    def test_skips_and_crashes_show(self):
        out = self.logs(build_mlb="  kalshi: skipped (timed out)\nTraceback (most recent call last):\n  File x\nValueError: bad\n")
        self.assertIn("build_mlb: kalshi", out)
        self.assertIn("build_mlb: crashed", out)


if __name__ == "__main__":
    unittest.main()
