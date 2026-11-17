"""
Slim page payload for the NHL, NBA and MLB boards.

Each builder writes its full dataset (<sport>.json) for the other scripts, and bakes a slim copy
into <sport>.html: only players with a pending pick on a list (Top 25, Value: the cards on the
Today tab, which draw each player's last games) keep their game logs. Everyone else keeps
{id, n, p, t}, an empty g, lazy: 1 and gn (their game count, for search ranking); the page fetches
<sport>.json for their logs when it needs them (ensureFull() in the templates). Standard library only.
"""
import datetime
import json

STALE_DAYS = 2   # a pending pick older than this (an ungraded leftover) doesn't keep its player's logs


def keep_ids(picks, today=None):
    """The player ids whose game logs stay in the page: every pending (ungraded) pick on a list (lists
    set: the Today tab's cards), from the last STALE_DAYS days or later. Locked picks count: they stay on
    the boards until their game starts. Unlisted board picks (every player on the slate) don't: the
    page only needs their logs when one is opened, and it loads them then."""
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=STALE_DAYS)).isoformat()
    out = set()
    for p in picks or []:
        if p.get("res") is not None or p.get("pid") is None or not str(p.get("lists") or "").strip():
            continue
        if (p.get("date") or since) < since:
            continue
        out.add(str(p["pid"]))
    return out


def slim_db(db, keep, full_name):
    """A copy of db for the page: kept players unchanged, every other player with games reduced to
    {id, n, p, t, g: [], lazy: 1, gn}. db itself is not changed. Adds "full" (the file to fetch)
    and "slim": True."""
    players = []
    for p in db.get("players") or []:
        g = p.get("g") or []
        if not g or str(p.get("id")) in keep:
            players.append(p)
            continue
        players.append({"id": p.get("id"), "n": p.get("n"), "p": p.get("p"), "t": p.get("t"),
                        "g": [], "lazy": 1, "gn": len(g)})
    out = dict(db)
    out["players"] = players
    out["full"] = full_name
    out["slim"] = True
    return out


def page_payload(db, picks, full_name, today=None):
    """The JSON baked into the page. Falls back to the full db if anything goes wrong, so a bug
    here costs page weight, never the page."""
    try:
        page = slim_db(db, keep_ids(picks, today), full_name)
    except Exception as e:  # noqa: BLE001
        print(f"  slim page: skipped ({e})")
        page = db
    return json.dumps(page, separators=(",", ":"), ensure_ascii=False)
