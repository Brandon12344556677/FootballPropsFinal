"""Tests for site_checks.py: the per-page search basics."""
import unittest

import site_checks as S

GOOD = ('<html><head><title>Best NHL player props today | Prop Streak Lab</title>'
        '<meta name="description" content="Today\'s best NHL player props with the model\'s chance and the price, free.">'
        '<link rel="canonical" href="https://propstreaklab.com/best/nhl.html"></head><body><h1>Best</h1></body></html>')


class PageSeo(unittest.TestCase):
    def test_good_page(self):
        self.assertEqual(S.page_seo("/best/nhl.html", GOOD), ([], []))

    def test_missing_basics(self):
        probs, _ = S.page_seo("/x.html", "<html><head></head><body></body></html>")
        self.assertEqual(probs, ["no <title>", "no meta description", "no <h1> heading"])

    def test_noindex_and_wrong_canonical(self):
        html = GOOD.replace("</head>", '<meta name="robots" content="noindex"></head>')
        probs, _ = S.page_seo("/best/nfl.html", html)
        self.assertEqual(len(probs), 2)
        self.assertEqual(S.page_seo("/p/nhl/x.html", html)[0], [])      # share pages are meant to be noindex

    def test_long_title_is_only_a_note(self):
        html = GOOD.replace("Best NHL player props today", "x" * 80)
        probs, notes = S.page_seo("/best/nhl.html", html)
        self.assertEqual(probs, [])
        self.assertIn("characters", notes[0])


if __name__ == "__main__":
    unittest.main()
