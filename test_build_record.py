"""build_record.py: the public Record page's numbers (units, the MLB unders rule, weekly series, empty files)."""
import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest

import build_record as br

NOW = datetime.datetime(2026, 11, 16, 18, 0, tzinfo=datetime.timezone.utc)
COLS = ["src", "date", "start", "side", "prob", "price", "px0", "pxc", "lists", "res", "vn", "th"]


def doc(*picks):
    return {"cols": COLS, "picks": [[p.get(c) for c in COLS] for p in picks]}


def pick(**kw):
    p = {"src": "live", "date": "2026-11-10", "side": "under", "prob": 0.7, "price": 0.5, "lists": "V", "res": "hit"}
    p.update(kw)
    return p


class Units(unittest.TestCase):
    def test_fraction_prices(self):
        rs = br.rows("nhl", doc(pick(price=0.4), pick(price=0.4, res="miss"), pick(price=0.8)))
        s = br.stats(rs)
        self.assertEqual((s["n"], s["hit"], s["priced"]), (3, 2, 3))
        self.assertAlmostEqual(s["units"], 1.5 - 1 + 0.25)
        self.assertAlmostEqual(s["roi"], 0.25, places=4)
        self.assertAlmostEqual(s["said"], 0.7)

    def test_nfl_prices_are_cents(self):
        rs = br.rows("nfl", doc(pick(price=40, px0=38, pxc=41), pick(price=50, res="miss")))
        s = br.stats(rs)
        self.assertAlmostEqual(rs[0]["price"], 0.4)
        self.assertAlmostEqual(s["units"], 0.5)
        self.assertEqual((s["clvN"], s["clvUp"], s["clv"]), (1, 1, 3.0))      # cents stay cents

    def test_fraction_price_move_is_in_cents(self):
        s = br.stats(br.rows("nba", doc(pick(price=0.52, px0=0.55, pxc=0.52))))
        self.assertEqual((s["clvN"], s["clvDn"], s["clv"]), (1, 1, -3.0))

    def test_unreal_price_counts_in_record_not_units(self):
        # 2c, and 52c -> 90c since the first price: both graded, neither in the units; no price at all, the same
        s = br.stats(br.rows("nba", doc(pick(price=0.02), pick(price=0.9, px0=0.52, res="miss"), pick(price=None),
                                        pick(price=0.5))))
        self.assertEqual((s["n"], s["hit"], s["priced"]), (4, 3, 1))
        self.assertAlmostEqual(s["units"], 1.0)

    def test_only_live_hits_and_misses(self):
        rs = br.rows("nba", doc(pick(src="bt"), pick(res="push"), pick(res="dnp"), pick(res=None), pick(res="void"), pick()))
        self.assertEqual(len(rs), 1)

    def test_launch_day_unchecked_left_out_of_nhl_and_mlb_only(self):
        d = doc(pick(date="2026-10-07"), pick(date="2026-10-07", vn="P"))
        self.assertEqual(len(br.rows("nhl", d)), 1)
        self.assertEqual(len(br.rows("nba", d)), 2)

    def test_day_is_et_day_of_the_start(self):
        rs = br.rows("nhl", doc(pick(date="2026-11-11", start="2026-11-11T00:30Z")))
        self.assertEqual(rs[0]["day"], "2026-11-10")


class MlbUnders(unittest.TestCase):
    def test_value_overs_get_their_own_row(self):
        d = doc(pick(side="under", lists="V"), pick(side="over", lists="V", res="miss"), pick(side="over", lists="TV"))
        b = {x["tag"]: x for x in br.sport_block("mlb", d, "2026-10-17")["lists"]}
        self.assertEqual((b["V"]["all"]["n"], b["V"]["all"]["hit"]), (1, 1))
        self.assertEqual((b["Vpre"]["all"]["n"], b["Vpre"]["all"]["hit"]), (2, 1))
        self.assertEqual(b["T"]["all"]["n"], 1)                 # an over still counts in Top 25

    def test_other_sports_keep_value_overs(self):
        d = doc(pick(side="over", lists="V"))
        self.assertEqual(br.sport_block("nhl", d, "2026-10-17")["lists"][0]["all"]["n"], 1)


class Weekly(unittest.TestCase):
    def test_cumulative_by_monday(self):
        rs = br.rows("nhl", doc(pick(date="2026-11-03", price=0.5),                 # Tue, week of Nov 2: +1
                                pick(date="2026-11-08", price=0.5, res="miss"),     # Sun, same week: -1
                                pick(date="2026-11-09", price=0.25),                # Mon, week of Nov 9: +3
                                pick(date="2026-11-10", price=None),                # no price: not a bet
                                pick(date="2026-11-24", price=0.5, res="miss")))    # a week with no picks is skipped
        self.assertEqual(br.weekly(rs), [["2026-11-02", 0.0, 2], ["2026-11-09", 3.0, 1], ["2026-11-23", 2.0, 1]])

    def test_last_30_days(self):
        d = doc(pick(date="2026-10-01", price=0.5, res="miss"), pick(date="2026-11-10", price=0.5))
        rec = br.build([("nhl", d)], None, NOW)
        v = rec["sports"][0]["lists"][0]
        self.assertEqual((v["all"]["n"], v["all"]["units"]), (2, 0.0))
        self.assertEqual((v["d30"]["n"], v["d30"]["units"]), (1, 1.0))


class Whole(unittest.TestCase):
    def test_empty_picks_file_still_lists_every_list(self):
        rec = br.build([("nfl", {"cols": COLS, "picks": []}), ("mlb", {"cols": [], "picks": []})], None, NOW)
        self.assertEqual([[b["tag"] for b in s["lists"]] for s in rec["sports"]], [["V", "T"], ["V", "Vpre", "T"]])
        for s in rec["sports"]:
            for b in s["lists"]:
                self.assertEqual((b["all"]["n"], b["all"]["units"], b["all"]["roi"], b["weeks"]), (0, 0, None, []))
        self.assertEqual((rec["losing"], rec["graded"], rec["since"], rec["calib"]), ([], 0, None, []))
        self.assertEqual([b["all"]["n"] for b in rec["botd"]], [0, 0])

    def test_losing_names_every_list_that_is_down(self):
        d = doc(pick(lists="V", price=0.5, res="miss"), pick(lists="T", price=0.9),
                pick(lists="T", price=0.9, res="miss", date="2026-09-20"), pick(lists="T", price=0.5, date="2026-09-20"),
                pick(lists="T", price=0.5, date="2026-09-20"))
        botd = {"days": [{"date": "2026-11-10", "lock": {"res": "miss", "price": 0.95, "prob": 0.95},
                          "value": {"res": "hit", "price": 0.4, "prob": 0.75}},
                         {"date": "2026-11-11", "lock": {"res": "void", "price": 0.95}, "value": None}],
                "record": {"lock": {"void": 1, "push": 0}}}
        rec = br.build([("nhl", d)], botd, NOW)
        names = [(x["name"], x["list"]) for x in rec["losing"]]
        self.assertEqual(names, [("NHL", "Value"), ("Pick of the Day", "Safe Pick")])
        lock = [b for b in rec["botd"] if b["tag"] == "lock"][0]
        self.assertEqual((lock["all"]["n"], lock["all"]["units"], lock["void"]), (1, -1.0, 1))
        value = [b for b in rec["botd"] if b["tag"] == "value"][0]
        self.assertEqual(value["all"]["units"], 1.5)

    def test_up_overall_but_down_this_month_is_named(self):
        d = doc(pick(lists="T", price=0.25, date="2026-09-20"), pick(lists="T", price=0.9, res="miss"))
        rec = br.build([("nhl", d)], None, NOW)
        self.assertEqual([(x["list"], x["units"], x["d30"]) for x in rec["losing"]], [("Top 25 Surest", 2.0, -1.0)])

    def test_tennis_is_marked_under_test_and_kept_out_of_the_pooled_fits(self):
        d = doc(pick(lists="V", price=0.5, res="miss"))
        rec = br.build([("tennis", d)], None, NOW)
        self.assertTrue(rec["sports"][0]["test"])
        self.assertEqual((rec["graded"], rec["calib"]), (0, []))
        self.assertEqual([x["list"] for x in rec["losing"]], ["Value"])      # never "Every priced side"


class Window(unittest.TestCase):
    def test_30_days_count_today(self):
        # NOW is Nov 16 ET: Oct 18 is the 30th day back (today included), Oct 17 is outside
        d = doc(pick(date="2026-10-17", price=0.5, res="miss"), pick(date="2026-10-18", price=0.5),
                pick(date="2026-11-16", price=0.5))
        v = br.build([("nhl", d)], None, NOW)["sports"][0]["lists"][0]
        self.assertEqual((v["all"]["n"], v["d30"]["n"], v["d30"]["units"]), (3, 2, 2.0))

    def test_weekly_series_ends_on_the_total(self):
        ps = [pick(date=(datetime.date(2026, 9, 1) + datetime.timedelta(days=3 * i)).isoformat(),
                   price=0.3 + 0.02 * (i % 20), res="hit" if i % 3 else "miss") for i in range(40)]
        b = br.sport_block("nba", doc(*ps), "2026-10-18")["lists"][0]
        days = [w[0] for w in b["weeks"]]
        self.assertEqual(days, sorted(set(days)))
        self.assertTrue(all(datetime.date.fromisoformat(x).weekday() == 0 for x in days))
        self.assertAlmostEqual(b["weeks"][-1][1], b["all"]["units"], places=2)
        self.assertEqual(sum(w[2] for w in b["weeks"]), b["all"]["priced"])


class Details(unittest.TestCase):
    def test_tennis_has_no_price_move(self):
        d = doc(pick(price=0.4, px0=0.97, pxc=0.4))
        self.assertEqual(br.stats(br.rows("tennis", d))["clvN"], 0)
        self.assertEqual(br.stats(br.rows("nhl", d))["clvN"], 1)

    def test_every_tennis_side_counts_in_its_all_row(self):
        b = {x["tag"]: x for x in br.sport_block("tennis", doc(pick(lists=None), pick(lists="V")), "2026-10-18")["lists"]}
        self.assertEqual((b["A"]["all"]["n"], b["V"]["all"]["n"], b["T"]["all"]["n"]), (2, 1, 0))

    def test_losing_order(self):
        # down all-time first (worst first), then up overall but down this month (worst month first)
        d = doc(pick(lists="V", price=0.5, res="miss"),
                pick(lists="T", price=0.1, date="2026-09-20"), pick(lists="T", price=0.9, res="miss"))
        m = doc(pick(lists="T", price=0.25, date="2026-09-20"), pick(lists="T", price=0.9, res="miss"),
                pick(lists="T", price=0.9, res="miss"))
        rec = br.build([("nhl", d), ("mlb", m)], None, NOW)
        self.assertEqual([(x["name"], x["list"], x["units"], x["d30"]) for x in rec["losing"]],
                         [("NHL", "Value", -1.0, -1.0), ("MLB", "Top 25 Surest", 1.0, -2.0), ("NHL", "Top 25 Surest", 8.0, -1.0)])

    def test_nfl_unreal_price_in_cents(self):
        s = br.stats(br.rows("nfl", doc(pick(price=5), pick(price=90, px0=52), pick(price=50, px0=45))))
        self.assertEqual((s["n"], s["priced"], s["units"]), (3, 1, 1.0))


class Robust(unittest.TestCase):
    def test_a_misshapen_picks_file_costs_only_that_sport(self):
        bad = {"cols": COLS, "picks": [7, None]}
        with contextlib.redirect_stdout(io.StringIO()):
            rec = br.build([("nba", bad), ("nhl", doc(pick())), ("nfl", {"cols": COLS, "picks": 5})], None, NOW)
        self.assertEqual([s["sport"] for s in rec["sports"]], ["nhl"])
        self.assertEqual(sum(c["n"] for c in rec["calib"]), 1)

    def test_misshapen_botd(self):
        for botd in (None, [], "x", {"days": None}, {"days": [None, 3, {"date": "2026-11-10", "lock": "x", "value": {"res": "hit", "price": "n/a"}}],
                                                   "record": []}):
            rec = br.build([("nhl", doc(pick()))], botd, NOW)
            self.assertEqual([b["tag"] for b in rec["botd"]], ["value", "lock"])
            self.assertEqual(rec["botd"][1]["all"]["n"], 0)
        self.assertEqual((rec["botd"][0]["all"]["n"], rec["botd"][0]["all"]["priced"]), (1, 0))


class Main(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()

    def tearDown(self):
        self.quiet.__exit__(None, None, None)
        os.chdir(self.old)
        self.tmp.cleanup()

    def put(self, name, value):
        with open(name, "w", encoding="utf-8") as f:
            f.write(value if isinstance(value, str) else json.dumps(value))

    def read(self, name):
        with open(name, encoding="utf-8") as f:
            return f.read()

    def test_writes_both_files_and_skips_what_it_cannot_read(self):
        self.put("nhl_picks.json", doc(pick(price=0.5)))
        self.put("nba_picks.json", "{not json")                  # unreadable; the other three don't exist; no botd.json
        self.put("record_template.html", "<script>const R=__RECORDDATA__;</script>")
        br.main()
        rec = json.loads(self.read("record.json"))
        self.assertEqual([s["sport"] for s in rec["sports"]], ["nhl"])
        self.assertEqual(self.read("record.html"), "<script>const R=" + self.read("record.json") + ";</script>")
        self.assertFalse([f for f in os.listdir(".") if f.endswith(".tmp")])

    def test_a_pass_that_changes_nothing_rewrites_nothing(self):
        self.put("nhl_picks.json", doc(pick(price=0.5)))
        self.put("record_template.html", "R=__RECORDDATA__")
        br.main()
        rec = json.loads(self.read("record.json"))
        rec["gen"] = "2026-01-01T00:00:00Z"                      # as if written by an earlier pass
        self.put("record.json", json.dumps(rec, separators=(",", ":"), ensure_ascii=False))
        before = self.read("record.json")
        br.main()
        self.assertEqual(self.read("record.json"), before)
        self.assertIn("2026-01-01T00:00:00Z", self.read("record.html"))
        self.put("nhl_picks.json", doc(pick(price=0.5), pick(price=0.5, res="miss")))
        br.main()
        self.assertNotEqual(json.loads(self.read("record.json"))["gen"], "2026-01-01T00:00:00Z")

    def test_no_picks_files_or_no_template_leaves_the_last_page(self):
        self.put("record.html", "last good page")
        self.put("record.json", "{}")
        br.main()                                                # nothing to read at all
        self.assertEqual((self.read("record.html"), self.read("record.json")), ("last good page", "{}"))
        self.put("nhl_picks.json", doc(pick()))
        br.main()                                                # picks, but no template
        self.assertEqual(self.read("record.html"), "last good page")
        self.assertEqual(len(json.loads(self.read("record.json"))["sports"]), 1)

    def test_script_text_in_the_data_cannot_close_the_script_tag(self):
        self.put("nhl_picks.json", doc(pick(date="</script><b>")))
        self.put("record_template.html", "R=__RECORDDATA__")
        br.main()
        self.assertNotIn("</script>", self.read("record.html"))


if __name__ == "__main__":
    unittest.main()
