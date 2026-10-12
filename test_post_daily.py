"""Tests for post_daily.py's campaign tags on our own links."""
import unittest

import post_daily


class Email(unittest.TestCase):
    def test_email_has_botd_picks_results_and_tracked_links(self):
        import datetime
        p = {"sport": "nhl", "pid": "1", "player": "Jane Doe", "side": "under", "line": 0.5, "statText": "Points",
             "stat": "pts", "prob": 0.8, "price": 0.55, "start": "2026-10-12T23:00:00Z", "vn": "P"}
        subject, body = post_daily.email_message([p], True, [("nhl", 9, 13, 3.58)], datetime.date(2026, 10, 12), lock=p)
        self.assertEqual(subject, "Today's best props (Mon, Oct 12): Jane Doe under 0.5 Points")
        self.assertIn("## Pick of the Day", body)
        self.assertIn("utm_source=email", body)
        self.assertIn("9/13 hit · +3.6 units", body)
        self.assertIn("Research, not betting advice", body)
        self.assertEqual(post_daily.email_message([], True, [], datetime.date(2026, 10, 12)), ("", ""))


class Tag(unittest.TestCase):
    def test_tags_go_before_the_prop_hash(self):
        url = post_daily.pick_link({"sport": "nfl", "pid": 123, "stat": "rec", "line": 4.5, "side": "over", "player": "A. Brown"})
        self.assertEqual(post_daily.tag(url, "discord"),
                         "https://propstreaklab.com/nfl.html?utm_source=discord&utm_campaign=daily-post"
                         "#player/123/rec/4.5/over/a-brown")

    def test_home_link_gets_a_slash(self):
        self.assertEqual(post_daily.tag(post_daily.SITE, "telegram"),
                         "https://propstreaklab.com/?utm_source=telegram&utm_campaign=daily-post")

    def test_other_sites_untouched(self):
        self.assertEqual(post_daily.tag(post_daily.REFERRAL, "discord"), post_daily.REFERRAL)

    def test_messages_tag_each_channel(self):
        d, t = post_daily.messages([], True, [("nfl", 3, 5, 1.2)], post_daily.datetime.date(2026, 10, 11))
        self.assertIn("utm_source=discord", d)
        self.assertNotIn("utm_source=telegram", d)
        self.assertIn("utm_source=telegram", t)


if __name__ == "__main__":
    unittest.main()
