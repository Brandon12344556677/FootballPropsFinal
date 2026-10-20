"""Tests for tiktok_post.py: which drafts get made, their captions, the once-a-day guard and the TikTok calls."""
import datetime
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

import tiktok_post as tt

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 20, 16, 0, tzinfo=UTC)          # noon ET
TONIGHT = "2026-10-20T23:30:00Z"
SUNDAY = "2026-10-25T17:00:00Z"                                    # not today's games


def pick(sport, prob=0.7, price=0.5, start=TONIGHT, player="A Player"):
    return {"sport": sport, "kind": "value", "player": player, "side": "under", "line": 1.5, "statText": "Points",
            "prob": prob, "price": price, "start": start}


def streak(sport, n=6, start=TONIGHT):
    return {"sport": sport, "player": "S Player", "side": "over", "line": 0.5, "statText": "Hits", "streak": n,
            "prob": 0.8, "price": 0.7, "start": start}


def doc(sports=("nfl", "nba", "nhl", "mlb"), record=True):
    return {"picks": [pick(s, prob=0.6 + i / 100) for i, s in enumerate(sports)],
            "streaks": [streak(s) for s in sports],
            "record": {s: {"T": {"n": 100, "hit": 90}} for s in sports} if record else {},
            "last": {}}


class Candidates(unittest.TestCase):
    def test_only_todays_games_count(self):
        d = {"picks": [pick("nfl", start=SUNDAY), pick("nba")], "streaks": [streak("nfl", start=SUNDAY)], "record": {}}
        self.assertEqual(tt.candidates(d, NOW), {"nba": {"gap": [1]}})

    def test_late_west_coast_game_is_still_today(self):
        self.assertTrue(tt.on_today("2026-10-21T05:00:00Z", NOW))      # 1 AM ET
        self.assertFalse(tt.on_today("2026-10-21T11:00:00Z", NOW))     # 7 AM ET: tomorrow
        self.assertFalse(tt.on_today("2026-10-20T15:00:00Z", NOW))     # already started

    def test_biggest_gap_first_and_short_streaks_left_out(self):
        d = {"picks": [pick("nba", prob=0.6), pick("nba", prob=0.9), pick("nba", price=None)],
             "streaks": [streak("nba", n=4), streak("nba", n=9)], "record": {"nba": {"T": {"n": 29, "hit": 20}}}}
        self.assertEqual(tt.candidates(d, NOW), {"nba": {"gap": [1, 0], "streak": [1]}})


class PlanDay(unittest.TestCase):
    def test_four_sports_give_three_sports_and_three_angles(self):
        v = tt.plan_day(doc(), [], NOW)
        self.assertEqual(len({x["sport"] for x in v}), 3)
        self.assertEqual({x["angle"] for x in v}, set(tt.ANGLES))

    def test_one_sport_gives_three_angles(self):
        v = tt.plan_day(doc(("nhl",)), [], NOW)
        self.assertEqual([(x["sport"], x["angle"]) for x in v], [("nhl", "gap"), ("nhl", "streak"), ("nhl", "record")])

    def test_least_recently_used_pair_wins(self):
        hist = [{"date": "2026-10-19", "sport": "nhl", "angle": "gap"}, {"date": "2026-10-18", "sport": "nhl", "angle": "streak"}]
        v = tt.plan_day(doc(("nhl",)), hist, NOW, n=1)
        self.assertEqual((v[0]["sport"], v[0]["angle"]), ("nhl", "record"))

    def test_a_week_covers_every_sport_and_angle(self):
        hist, seen = [], set()
        for day in range(7):
            now = NOW + datetime.timedelta(days=day)
            d = doc()
            for k in ("picks", "streaks"):
                for x in d[k]:
                    x["start"] = (now + datetime.timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for v in tt.plan_day(d, hist, now):
                hist.append({"date": now.astimezone(tt.ET).date().isoformat(), "sport": v["sport"], "angle": v["angle"]})
                seen.add((v["sport"], v["angle"]))
        self.assertEqual({s for s, _ in seen}, set(tt.SPORTS))
        self.assertEqual({a for _, a in seen}, set(tt.ANGLES))
        self.assertGreaterEqual(len(seen), 12)       # 21 videos: every one of the 12 pairs at least once

    def test_no_games_falls_back_to_the_latest_records(self):
        d = doc(("nhl", "mlb"))
        d["picks"], d["streaks"] = [], []
        d["last"] = {"nhl": {"day": "2026-10-18"}, "mlb": {"day": "2026-10-19"}}
        v = tt.plan_day(d, [], NOW)
        self.assertEqual([(x["sport"], x["angle"]) for x in v], [("mlb", "record"), ("nhl", "record")])

    def test_nothing_at_all(self):
        self.assertEqual(tt.plan_day({"picks": [], "streaks": [], "record": {}}, [], NOW), [])


class Carousel(unittest.TestCase):
    def test_one_value_pick_per_sport_and_the_top_streak(self):
        d = doc(("nba", "nhl"))
        d["streaks"][1]["streak"] = 12
        c = tt.carousel_plan(d, NOW, "2026-10-20")
        self.assertEqual(c["gap"], [0, 1])
        self.assertEqual(c["streak"], [1])
        self.assertEqual(c["sports"], ["nba", "nhl"])


class Captions(unittest.TestCase):
    def test_no_gambling_words_and_18_plus(self):
        d = doc()
        botd = {"days": [{"date": "2026-10-20", "lock": pick("nba", prob=0.95)}]}
        texts = [tt.video_caption(d, v) for v in tt.plan_day(d, [], NOW)]
        c = tt.carousel_caption(d, botd, tt.carousel_plan(d, NOW, "2026-10-20"))
        texts += [c["title"], c["description"]]
        self.assertTrue(c["title"].startswith("Pick of the Day"))
        for t in texts:
            self.assertIsNone(tt.BANNED.search(t), t)
        for t in texts[:-2] + [c["description"]]:
            self.assertIn("18+", t)
            self.assertIn("link in bio", t)
        self.assertLessEqual(len(c["title"]), 90)

    def test_banned_words(self):
        for bad in ("Best bet today", "a LOCK", "on Polymarket", "Kalshi price", "betting"):
            self.assertIsNotNone(tt.BANNED.search(bad), bad)
        self.assertIsNone(tt.BANNED.search("alphabet blockers"))


class Video(unittest.TestCase):
    def test_slideshow_command(self):
        cmd = tt.ffmpeg_cmd(["a.png", "b.png", "c.png"], "out.mp4")
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("[s0][s1]xfade=transition=fade:duration=0.35:offset=2.85[x1]", fc)
        self.assertIn("[x1][s2]xfade=transition=fade:duration=0.35:offset=5.70[x2]", fc)
        self.assertEqual(cmd[cmd.index("-map") + 1], "[x2]")
        self.assertIn("anullsrc=r=44100:cl=stereo", cmd)
        self.assertEqual(cmd[-1], "out.mp4")


class Draw(unittest.TestCase):
    def test_reads_the_images_back_from_the_dumped_page(self):
        out = json.dumps({"ok": True, "sets": {"c": ["data:image/jpeg;base64,QUJD"]}}).replace("&", "&amp;").replace("<", "&lt;")
        dom = f'<html><body><p id="msg">Done.</p><pre id="out" hidden="">{out}</pre></body></html>'
        ran = mock.Mock(stdout=dom.encode(), stderr=b"")
        with mock.patch.object(tt, "browser", return_value="chrome"), mock.patch("subprocess.run", return_value=ran) as run:
            sets = tt.draw({"videos": []})
        self.assertEqual(tt.data_url_bytes(sets["c"][0]), b"ABC")
        self.assertIn("/team/render.html?plan=", run.call_args[0][0][-1])

    def test_a_drawing_error_is_raised(self):
        dom = '<pre id="out" hidden="">{"ok":false,"error":"TypeError: x"}</pre>'
        with mock.patch.object(tt, "browser", return_value="chrome"), \
             mock.patch("subprocess.run", return_value=mock.Mock(stdout=dom.encode(), stderr=b"")):
            with self.assertRaises(RuntimeError):
                tt.draw({"videos": []})


class Resp:
    def __init__(self, body, headers=None):
        self.body, self.headers = body if isinstance(body, bytes) else json.dumps(body).encode(), headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TikTokCalls(unittest.TestCase):
    def test_photo_draft_payload(self):
        b = tt.photo_init_body(["https://propstreaklab.com/tiktok/2026-10-20/c1.jpg"], {"title": "x" * 120, "description": "d"})
        self.assertEqual((b["media_type"], b["post_mode"], b["source_info"]["source"]), ("PHOTO", "MEDIA_UPLOAD", "PULL_FROM_URL"))
        self.assertEqual(len(b["post_info"]["title"]), 90)

    def test_video_is_one_chunk(self):
        self.assertEqual(tt.video_init_body(1234)["source_info"],
                         {"source": "FILE_UPLOAD", "video_size": 1234, "chunk_size": 1234, "total_chunk_count": 1})

    def test_api_error_raises(self):
        with mock.patch("urllib.request.urlopen", return_value=Resp({"error": {"code": "spam_risk_too_many_pending_share", "message": "too many"}})):
            with self.assertRaises(tt.TikTokError) as e:
                tt.api("/v2/post/publish/content/init/", {}, "tok")
        self.assertIn("spam_risk_too_many_pending_share", str(e.exception))

    def test_http_error_body_is_read(self):
        err = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b'{"error":"invalid_grant","error_description":"expired"}'))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(tt.TikTokError) as e:
                tt.refresh("k", "s", "r")
        self.assertIn("invalid_grant", str(e.exception))

    def test_rotated_refresh_token_is_saved(self):
        env = {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "old",
               "GITHUB_TOKEN": "gh", "GITHUB_REPOSITORY": "o/r"}
        with mock.patch.object(tt, "stored_token", return_value=(None, None)), \
             mock.patch.object(tt, "refresh", return_value={"access_token": "A", "refresh_token": "new"}), \
             mock.patch.object(tt, "save_token") as save:
            self.assertEqual(tt.access_token(env), "A")
        save.assert_called_once_with("gh", "o/r", "s", "new", None)

    def test_stored_token_tried_first_then_the_secret(self):
        env = {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "secret-tok",
               "GITHUB_TOKEN": "gh", "GITHUB_REPOSITORY": "o/r"}
        calls = []

        def refresh(key, secret, tok):
            calls.append(tok)
            if tok == "stored-tok":
                raise tt.TikTokError("token refresh refused: invalid_grant")
            return {"access_token": "A", "refresh_token": "secret-tok"}
        with mock.patch.object(tt, "stored_token", return_value=("stored-tok", "sha1")), \
             mock.patch.object(tt, "refresh", side_effect=refresh), mock.patch.object(tt, "save_token") as save:
            self.assertEqual(tt.access_token(env), "A")
        self.assertEqual(calls, ["stored-tok", "secret-tok"])
        save.assert_called_once_with("gh", "o/r", "s", "secret-tok", "sha1")

    def test_no_working_token_says_reconnect(self):
        env = {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "t"}
        with mock.patch.object(tt, "refresh", side_effect=tt.TikTokError("token refresh refused: invalid_grant")):
            with self.assertRaises(tt.TikTokError) as e:
                tt.access_token(env)
        self.assertTrue(str(e.exception).startswith("reconnect"))


class OncePerDay(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self.cwd)

    def state(self, drafts, date="2026-10-20"):
        os.makedirs("tiktok", exist_ok=True)
        with open(tt.STATE, "w") as f:
            json.dump({"date": date, "drafts": drafts, "history": [{"date": "2026-09-01", "sport": "nba", "angle": "gap"}]}, f)

    def test_waits_for_11_et(self):
        st = tt.todays_state(NOW.date())
        self.assertFalse(tt.gate(datetime.datetime(2026, 10, 20, 10, 59, tzinfo=tt.ET), st, False, "x"))
        self.assertTrue(tt.gate(datetime.datetime(2026, 10, 20, 11, 0, tzinfo=tt.ET), st, False, "x"))

    def test_only_failed_drafts_are_redone(self):
        self.state({"v1": {"ok": True}, "v2": {"ok": False}, "v3": {"ok": True}, "c": {"ok": True}})
        st = tt.todays_state(NOW.date())
        self.assertEqual(tt.missing(st), ["v2"])
        self.assertEqual(st["history"], [])           # older than KEEP_DAYS: dropped

    def test_done_for_the_day_unless_forced(self):
        self.state({k: {"ok": True} for k in tt.DRAFTS})
        st = tt.todays_state(NOW.date())
        self.assertFalse(tt.gate(datetime.datetime(2026, 10, 20, 15, 0, tzinfo=tt.ET), st, False, "x"))
        self.assertEqual(tt.wanted(st, True), tt.DRAFTS)

    def test_a_new_day_starts_fresh(self):
        self.state({k: {"ok": True} for k in tt.DRAFTS}, date="2026-10-19")
        self.assertEqual(tt.missing(tt.todays_state(NOW.date())), tt.DRAFTS)

    def test_send_without_secrets_does_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("urllib.request.urlopen") as net:
            tt.send(NOW, False, False)
        net.assert_not_called()

    def test_network_failure_is_recorded_not_raised(self):
        os.makedirs("tiktok/2026-10-20")
        with open("tiktok/2026-10-20/v1.mp4", "wb") as f:
            f.write(b"x")
        with open("tiktok/2026-10-20/plan.json", "w") as f:
            json.dump({"v1": {"sport": "nba", "angle": "gap", "caption": "c", "file": "tiktok/2026-10-20/v1.mp4"}}, f)
        env = {"TIKTOK_CLIENT_KEY": "k", "TIKTOK_CLIENT_SECRET": "s", "TIKTOK_REFRESH_TOKEN": "t"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(tt, "access_token", return_value="A"), \
             mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            tt.send(NOW, False, False)
        st = json.load(open(tt.STATE))
        self.assertFalse(st["drafts"]["v1"]["ok"])
        self.assertIn("down", st["drafts"]["v1"]["error"])
        self.assertEqual(st["history"], [])


if __name__ == "__main__":
    unittest.main()
