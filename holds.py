"""
Prop Streak Lab — props that wait for injury news (every sport).

A prop stays off Top 25 Surest and Value while the news it depends on isn't settled:
  - the player himself is questionable, doubtful or day-to-day (he may not play, or may play
    less), or out (he isn't playing);
  - or a teammate in his position group with a real role is questionable, doubtful or
    day-to-day: whether that teammate plays changes this player's role.
The hold lifts on the first update after the news settles: the teammate is ruled out (then his
teammates' props come back, judged on the model's numbers) or cleared to play (the report drops
the designation or shows him active). Each builder says what a position group and a real role
are in its sport, and can pass news that settles a player for one game before the injury report
does (MLB's posted lineups).

"hd" on a pick names what it waits on ("DeVonta Smith (questionable)"); None when nothing.
Standard library only.
"""
import re

UNSURE = re.compile(r"questionable|doubtful|day-to-day|game[- ]time|\bgtd\b", re.I)
OUT = re.compile(r"\bout\b|injured reserve|\bil\b|\bir\b|suspen|physically unable|\bpup\b|non-football"
                 r"|paternity|bereavement|inactive", re.I)


def status(text):
    """An injury report status -> "unsure", "out", or None (active: nothing keeps him out)."""
    t = str(text or "")
    if UNSURE.search(t):
        return "unsure"
    if OUT.search(t):
        return "out"
    return None


def label(text):
    """How a hold names a status: "out", or the report's own word ("questionable", "day-to-day")."""
    return "out" if status(text) == "out" else (str(text or "").strip().lower() or "questionable")


def last_games(rows, n=5):
    """{player id: (his latest team, his last n box rows for that team)} from a builder's box
    rows (dicts with "pid", "team" and "date")."""
    by = {}
    for r in rows:
        by.setdefault(r["pid"], []).append(r)
    out = {}
    for pid, rs in by.items():
        rs.sort(key=lambda r: r["date"])
        team = rs[-1]["team"]
        out[pid] = (team, [r for r in rs if r["team"] == team][-n:])
    return out


def match(report, people, key):
    """The injury report ([{"id", "name", "status"}], news.espn_injuries) -> {player id: status},
    by ESPN id, else by a name only one player has (key normalizes names)."""
    names = {}
    for pid, (name, _team, _pos) in people.items():
        names.setdefault(key(name), []).append(pid)
    out = {}
    for x in report or []:
        pid = x.get("id") if x.get("id") in people else None
        if pid is None:
            c = names.get(key(x.get("name") or ""), [])
            pid = c[0] if len(c) == 1 else None
        if pid is not None:
            out[pid] = x.get("status") or ""
    return out


def apply(picks, report, people, groups, role, is_open, settled=None):
    """Set "hd" on every pick is_open(p) allows; returns how many are held.
      report:  {player id: status text} for the players on the injury report (match()).
      people:  {player id: (name, team, position)}: an injured player the builder doesn't know
               has no role to hand on.
      groups(position) -> the set of position groups a player at that position is in.
      role(player id)  -> does he have a real role in his group (the sport's definition)?
      settled(player id, pick) -> None, "in", or a label meaning out ("not in the lineup"):
               news that settles him for the pick's game ahead of the report."""
    unsure = {}
    for pid, text in report.items():
        if status(text) == "unsure" and pid in people and role(pid):
            name, team, pos = people[pid]
            unsure.setdefault(team, []).append((pid, name, groups(pos), label(text)))
    n = 0
    for p in picks:
        if not is_open(p):
            continue
        why = []
        s = settled(p["pid"], p) if settled else None
        if s is not None and s != "in":
            why.append(f"{p['player']} ({s})")
        elif s is None and status(report.get(p["pid"])):
            why.append(f"{p['player']} ({label(report[p['pid']])})")
        mine = groups(p.get("pos") or "")
        for pid, name, g, lab in unsure.get(p.get("team"), ()):
            if pid == p["pid"] or not (g & mine):
                continue
            if settled and settled(pid, p) is not None:     # in or out for this game: settled
                continue
            why.append(f"{name} ({lab})")
        p["hd"] = ", ".join(why)[:120] or None
        n += p["hd"] is not None
    return n
