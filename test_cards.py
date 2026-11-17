"""Tests for cards.py (link-preview cards) and the share-page side in build_games.py."""
import datetime
import os
import re
import shutil
import tempfile
import unittest

import cards
import build_games as G

def touch(path):
    with open(path, "wb") as f:
        f.write(b"png")


TODAY = datetime.date(2026, 11, 17)
REC = {"graded": 145023, "since": "2026-09-10", "sports": [
    {"sport": "nfl", "name": "NFL", "test": False, "graded": 21609, "since": "2026-09-10", "lists": [
        {"tag": "V", "d30": {"n": 186, "hit": 98, "units": 21.45, "said": 0.65}},
        {"tag": "T", "d30": {"n": 500, "hit": 450, "units": 3.0, "said": 0.94}}]},
    {"sport": "nba", "name": "NBA", "test": False, "graded": 52835, "since": "2026-10-20", "lists": [
        {"tag": "V", "d30": {"n": 1438, "hit": 654, "units": -54.2, "said": 0.6}}]},
    {"sport": "tennis", "name": "Tennis", "test": True, "graded": 900, "since": "2026-11-02", "lists": [
        {"tag": "V", "d30": {"n": 40, "hit": 30, "units": 9.0, "said": 0.6}}]}]}
PICK = {"player": "Quentin Grimes", "side": "under", "line": 9.5, "statText": "Points", "prob": 0.57, "price": 0.32, "vn": "K"}
BOTD = {"days": [{"date": "2026-11-17", "lock": dict(PICK, sport="nba", prob=0.96, price=0.95),
                  "value": dict(PICK, sport="nba", picked="x", res=None)}]}


class Cards(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.dir = tempfile.mkdtemp()
        os.chdir(self.dir)
        os.makedirs("og")
        os.makedirs(os.path.join("p", "nba"))

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.dir, ignore_errors=True)

    def names(self, state, botd=None, queue=None, today=TODAY):
        return [t[0] for t in cards.plan(today, state, REC, botd, queue)]

    def draw_all(self, todo, today=TODAY, state=None):
        state = {} if state is None else state
        for name, path, kind, data in todo:
            touch(path)
            if not name.startswith("p/"):
                state[name] = {"fp": cards.fingerprint([kind, data]), "day": today.isoformat(), "kind": kind}
        return state

    def test_first_run_draws_every_page_card(self):
        self.assertEqual(sorted(self.names({})), sorted(["site", "record", "home", *cards.SPORTS]))

    def test_up_to_date_cards_are_left_alone(self):
        state = self.draw_all(cards.plan(TODAY, {}, REC, None, []))
        self.assertEqual(self.names(state), [])

    def test_daily_cards_redraw_at_most_once_a_day(self):
        state = self.draw_all(cards.plan(TODAY, {}, REC, None, []))
        changed = {**REC, "graded": 146000}
        self.assertEqual([t[0] for t in cards.plan(TODAY, state, changed, None, [])], [])
        tomorrow = TODAY + datetime.timedelta(days=1)
        self.assertIn("site", [t[0] for t in cards.plan(tomorrow, state, changed, None, [])])

    def test_home_card_switches_to_pick_of_the_day_when_it_is_made(self):
        state = self.draw_all(cards.plan(TODAY, {}, REC, None, []))
        todo = cards.plan(TODAY, state, REC, BOTD, [])
        self.assertEqual([(t[0], t[2]) for t in todo], [("home", "potd")])
        slots = todo[0][3]["slots"]
        self.assertEqual([s["title"] for s in slots], ["Safe Pick", "Value Shot"])
        self.assertNotIn("picked", slots[1]["pick"])      # only what the card shows

    def test_pick_cards_drawn_once_deduped_and_capped(self):
        state = self.draw_all(cards.plan(TODAY, {}, REC, None, []))
        q = [{"sport": "nba", "key": "1-pts-9.5-under", "pick": PICK, "game": "CHA @ LAL"}] * 2
        q += [{"sport": "nba", "key": "../evil", "pick": PICK}, {"sport": "xfl", "key": "2-pts-1.5-over", "pick": PICK}]
        todo = cards.plan(TODAY, state, REC, None, q)
        self.assertEqual([t[0] for t in todo], ["p/nba/1-pts-9.5-under"])
        self.draw_all(todo, state=state)
        self.assertEqual(cards.plan(TODAY, state, REC, None, q), [])
        many = [{"sport": "nba", "key": f"{i}-pts-9.5-under", "pick": PICK} for i in range(100, 200)]
        self.assertEqual(len(cards.plan(TODAY, state, REC, None, many)), cards.MAX_PICKS)

    def test_no_chrome_draws_nothing_and_keeps_going(self):
        orig = cards.browser
        cards.browser = lambda: None
        try:
            self.assertEqual(cards.draw([("site", "og/site.png", "site", {})]), {})
        finally:
            cards.browser = orig


class Content(unittest.TestCase):
    def test_sport_card_shows_losses_as_losses(self):
        nba = cards.sport_card(REC, "nba")
        self.assertEqual(nba["tiles"][0][:3], ["Value · 30 days", "−54.2u", "dn"])
        nfl = cards.sport_card(REC, "nfl")
        self.assertEqual(nfl["tiles"][0][1:3], ["+21.4u", "up"])
        self.assertEqual(nfl["tiles"][1][1], "90% hit")

    def test_site_and_record_cards_leave_tennis_out_and_name_the_losers(self):
        site = cards.site_card(REC)
        self.assertEqual(site["tiles"][2][1:4], ["1", "dn", "NBA"])
        rows = cards.record_card(REC)["rows"]
        self.assertEqual([r["label"] for r in rows], ["NFL Value", "NBA Value"])
        self.assertIn("Sep 10", cards.record_card(REC)["title"])

    def test_cards_without_a_record_still_draw(self):
        self.assertTrue(cards.sport_card(None, "nhl")["tiles"])
        self.assertTrue(cards.site_card(None)["tiles"])
        self.assertIsNone(cards.potd_card(None, TODAY))

    def test_draw_page_knows_every_kind_and_keeps_the_copy_rules(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "og", "draw.html"), encoding="utf-8") as f:
            page = f.read()
        for kind in ("pick", "sport", "potd", "record", "site"):
            self.assertRegex(page, rf"\n    {kind}\(ctx, d\) \{{")
        self.assertIn("18+", page)
        script = page.split("<script>", 1)[1]
        self.assertNotRegex(script.lower(), r"'[^']*\b(bet|lock)\b[^']*'")
        self.assertEqual(page.count('<pre id="out"'), 1)   # cards.py reads the first one


class SharePages(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.dir = tempfile.mkdtemp()
        os.chdir(self.dir)
        os.makedirs(os.path.join("p", "nba"))
        os.makedirs("og")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_share_page_uses_its_card_then_the_sport_card_then_the_logo(self):
        self.assertIn("icon-512.png", G.og_image("nba", "1-pts-9.5-under"))
        touch(os.path.join("og", "nba.png"))
        self.assertIn("/og/nba.png", G.og_image("nba", "1-pts-9.5-under"))
        touch(os.path.join("p", "nba", "1-pts-9.5-under.png"))
        tags = G.og_image("nba", "1-pts-9.5-under")
        self.assertIn("/p/nba/1-pts-9.5-under.png", tags)
        self.assertIn("summary_large_image", tags)

    def test_card_job_carries_what_the_card_shows(self):
        start = datetime.datetime(2026, 11, 18, 4, 0, tzinfo=datetime.timezone.utc)
        c = dict(PICK, pid="1", stat="pts", cls="value")
        job = G.card_job("nba", c, {"away": "CHA", "home": "LAL", "start": start, "timed": True}, TODAY)
        self.assertEqual(job["key"], "1-pts-9.5-under")
        self.assertEqual(job["asOf"], "Nov 17")
        self.assertTrue(re.match(r"CHA @ LAL · Tue, Nov 17, 11:00 PM ET", job["game"]))
        self.assertEqual(set(job["pick"]), {"player", "side", "line", "statText", "prob", "price", "vn"})


if __name__ == "__main__":
    unittest.main()
