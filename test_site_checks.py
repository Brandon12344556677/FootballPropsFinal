"""Tests for site_checks.py: the per-page search basics and the sign-up link checks."""
import unittest
from unittest import mock

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


class Signup(unittest.TestCase):
    def run_with(self, poly_title, kalshi=429, carriers="join/propstreaklab " + S.KALSHI_REF_ID):
        def fetch(url, **kw):
            if url.startswith(S.POLY_REF):
                return 200, f"<html><head><title>{poly_title}</title></head></html>"
            if url.startswith("https://kalshi.com"):
                return kalshi, ""
            return 200, carriers
        with mock.patch.object(S, "fetch", side_effect=fetch):
            return S.check_signup()

    def test_all_good_and_kalshi_blocking_is_only_a_note(self):
        out, notes = self.run_with("Use your friend's code PROPSTREAKLAB and get $25 to trade on Polymarket.")
        self.assertEqual(out, {})
        self.assertIn("Kalshi", notes[0])

    def test_code_gone(self):
        out, _ = self.run_with("Polymarket — PROPSTREAKLAB2 | Polymarket".replace("PROPSTREAKLAB2", "OTHER"))
        self.assertIn("signup: polymarket", out)

    def test_offer_wording_is_not_checked_but_lost_links_are(self):
        out, _ = self.run_with("Use your friend's code PROPSTREAKLAB and get $10", kalshi=404, carriers="join/propstreaklab")
        self.assertEqual(sorted(out), ["signup: /", "signup: /app.js", "signup: /guides/polymarket-and-kalshi.html",
                                       "signup: kalshi"])


if __name__ == "__main__":
    unittest.main()
