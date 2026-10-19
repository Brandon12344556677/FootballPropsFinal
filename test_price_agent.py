import datetime
import json
import os
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

import price_agent

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 19, 19, 0, tzinfo=UTC)          # 3:00 PM ET


def move(pid, was, price, lists="V", why=None, sport="nhl"):
    return {"sport": sport, "pid": pid, "player": "P" + pid, "team": "A", "opp": "B", "stat": "pts",
            "statText": "points", "line": 0.5, "side": "under", "was": was, "price": price,
            "start": "2026-10-19T23:00:00Z", "lists": lists, "why": why}


class FakeClient:
    """Stands in for anthropic.Anthropic: answers from a list of responses, records the requests."""
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def answer(text, stop="end_turn", citations=()):
    return NS(stop_reason=stop, model=price_agent.MODEL,
              content=[NS(type="text", text=text, citations=[NS(url=u, title=t) for u, t in citations])])


class PriceAgentTest(unittest.TestCase):
    def test_only_unexplained_value_moves_biggest_first(self):
        fast = [move("1", 0.40, 0.52), move("2", 0.40, 0.70), move("3", 0.40, 0.60, lists="T"),
                move("4", 0.40, 0.80, why="Questionable"), move("5", 0.70, 0.45)]
        got = [m["pid"] for m in price_agent.to_do(fast, {"days": {}}, "2026-10-19")]
        self.assertEqual(got, ["2", "5", "1"])      # Top 25 and news-explained moves are skipped

    def test_once_per_direction_and_within_budget(self):
        m = move("1", 0.40, 0.60)
        state = {"days": {"2026-10-19": {price_agent.move_key(m): {}}}}
        self.assertEqual(price_agent.to_do([m], state, "2026-10-19"), [])
        back = move("1", 0.60, 0.45)                # moved back down: a new question
        self.assertEqual(len(price_agent.to_do([back], state, "2026-10-19")), 1)
        full = {"days": {"2026-10-19": {str(i): {} for i in range(price_agent.PER_DAY)}}}
        self.assertEqual(price_agent.to_do([back], full, "2026-10-19"), [])
        many = [move(str(i), 0.40, 0.60) for i in range(10)]
        self.assertEqual(len(price_agent.to_do(many, {"days": {}}, "2026-10-19")), price_agent.PER_RUN)

    def test_parse_reason_confidence_and_sources(self):
        r = answer("Coach said P1 is out tonight (lower body), reported at 2:10 PM. Confidence: High",
                   citations=[("https://team.example/news", "Team news"), ("https://team.example/news", "dup")])
        reason, conf, sources = price_agent.parse(r.content, r.stop_reason)
        self.assertEqual(conf, "high")
        self.assertNotIn("Confidence", reason)
        self.assertEqual(sources, [{"title": "Team news", "url": "https://team.example/news"}])
        self.assertEqual(price_agent.parse([], "refusal")[1], "low")

    def test_research_resumes_a_paused_turn(self):
        paused = NS(stop_reason="pause_turn", model=price_agent.MODEL, content=[NS(type="server_tool_use")])
        client = FakeClient(paused, answer("Nothing explains it. Confidence: low"))
        (reason, conf, _), _ = price_agent.research(client, move("1", 0.4, 0.6), NOW)
        self.assertEqual((reason, conf), ("Nothing explains it.", "low"))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["messages"][-1], {"role": "assistant", "content": paused.content})
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["tools"][0]["type"], "web_search_20260209")
        self.assertIn("40c to 60c", call["messages"][0]["content"])

    def test_main_skips_without_keys(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            cwd = os.getcwd(); os.chdir(d)
            try:
                self.assertEqual(price_agent.main(), 0)
                self.assertFalse(os.path.exists(price_agent.OUT))
            finally:
                os.chdir(cwd)

    def test_main_writes_encrypted_state(self):
        client = FakeClient(answer("P2 ruled out at 2:30 PM. Confidence: medium"))
        fake = NS(Anthropic=lambda **kw: client, APIError=type("APIError", (Exception,), {}))
        env = {"TEAM_DASH_PASSWORD": "pw", "ANTHROPIC_API_KEY": "k"}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env),                 mock.patch.dict("sys.modules", {"anthropic": fake}),                 mock.patch.object(price_agent.team_stats, "ITERATIONS", 1000):
            cwd = os.getcwd(); os.chdir(d)
            try:
                with open("today.json", "w") as f:
                    json.dump({"fastAll": [move("2", 0.40, 0.70), move("3", 0.40, 0.70, lists="T")]}, f)
                self.assertEqual(price_agent.main(), 0)
                state = price_agent.read_state("pw")
            finally:
                os.chdir(cwd)
        (k, w), = next(iter(state["days"].values())).items()
        self.assertTrue(k.endswith("|up"))
        self.assertEqual((w["player"], w["conf"]), ("P2", "medium"))
        self.assertEqual(len(client.calls), 1)                                   # the Top 25 move is skipped


if __name__ == "__main__":
    unittest.main()
