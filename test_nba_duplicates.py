"""NBA picks recorded twice for one game (two ids a day apart) are voided as 'dup' (build_nba.void_duplicates)."""
import datetime
import unittest

import build_nba as N

NOW = datetime.datetime(2026, 11, 25, 12, tzinfo=datetime.timezone.utc)


def pick(gid, lists="", res="hit", start="2026-11-22T01:00Z", line=24.5):
    return {"src": "live", "gid": gid, "pid": "1", "stat": "pts", "line": line, "side": "over",
            "start": start, "lists": lists, "res": res}


class TestVoidDuplicates(unittest.TestCase):
    def test_second_copy_voided(self):
        a, b = pick("2026-11-21-BOS-WSH"), pick("2026-11-22-BOS-WSH")
        self.assertEqual(N.void_duplicates([a, b], NOW), 1)
        self.assertEqual((a["res"], b["res"]), ("hit", "dup"))

    def test_listed_copy_kept(self):
        a, b = pick("2026-11-21-BOS-WSH"), pick("2026-11-22-BOS-WSH", lists="V")
        N.void_duplicates([a, b], NOW)
        self.assertEqual((a["res"], b["res"]), ("dup", "hit"))

    def test_waits_for_both_graded_and_settled(self):
        a, b = pick("2026-11-21-BOS-WSH"), pick("2026-11-22-BOS-WSH", res=None)
        self.assertEqual(N.void_duplicates([a, b], NOW), 0)
        recent = [pick("x", start="2026-11-24T01:00Z"), pick("y", start="2026-11-24T01:00Z")]
        self.assertEqual(N.void_duplicates(recent, NOW), 0)

    def test_different_props_untouched(self):
        a, b = pick("2026-11-21-BOS-WSH"), pick("2026-11-22-BOS-WSH", line=25.5)
        self.assertEqual(N.void_duplicates([a, b], NOW), 0)

    def test_idempotent(self):
        ps = [pick("a"), pick("b"), pick("c")]
        self.assertEqual(N.void_duplicates(ps, NOW), 2)
        self.assertEqual(N.void_duplicates(ps, NOW), 0)
        self.assertEqual([p["res"] for p in ps], ["hit", "dup", "dup"])


if __name__ == "__main__":
    unittest.main()
