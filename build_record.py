"""
Prop Streak Lab — record.html, the public Record page: every list in every sport, losers included.

Runs after build_today.py. Reads what the builders already wrote (each sport's picks file and
botd.json) and writes:

  record.json  {"gen", "day", "window": 30, "graded", "since",
                "sports": [{"sport", "name", "page", "test", "graded", "since",
                            "lists": [{"tag", "name", "all": stats, "d30": stats, "weeks": [[monday, units so far, bets that week], ...]}],
                            "calib": build_today.calibration's buckets, "fair": build_today.fair_weight's fit}],
                ("gen": when the numbers last changed; "window": 30 days, today included)
                "calib", "fair": the same two, pooled over the featured sports (what the home page shows),
                "botd": Pick of the Day's two slots, shaped like a sport's lists,
                "losing": [{"sport", "name", "list", "units", "priced", "roi", "d30"}]: every list down units}
               stats = {"n", "hit", "said": average model chance, "priced", "units", "roi",
                        "clvN", "clvUp", "clvDn", "clv": average price move in cents, first price to last
                        (none for tennis: NO_MOVE)}
  record.html  record_template.html with __RECORDDATA__ replaced by that JSON. The page only draws it.

The rules are the builders' own, so the numbers match each board's record: live picks that hit or
missed (pushes, voids and DNPs don't count), 1 unit on each at its recorded price, a price that can't
have been real (depth.real_price) counted in the wins and losses but not the units, launch-day picks
the $25 rule never checked (depth.unchecked) left out of NHL and MLB, MLB Value unders only (the
Value overs from before that rule get their own row), NFL prices in cents. Nothing is filtered by
how it turned out: a list that is down shows as down, and is named in "losing".

Standard library only. Never fails the deploy: a sport whose picks file is missing or can't be read
is skipped, and a failure leaves the previous record.json and record.html in place.
"""
import datetime
import json
import os
import sys

import build_today
import depth
from build_today import ET, NOT_FEATURED, SPORTS, cap, parse_start

OUT = "record.json"
PAGE = "record.html"
TEMPLATE = "record_template.html"
BOTD = "botd.json"
WINDOW = 30             # days in the "last 30 days" column
NAMES = {"nfl": "NFL", "nba": "NBA", "nhl": "NHL", "mlb": "MLB", "tennis": "Tennis"}
# Every list a board publishes, in the order the page shows them. "Vpre" is the Value picks made under an
# older rule (MLB's overs before unders only; NBA's unders and picks outside 30-60c / 20+ games before
# Nov 23, 2026): no longer made, still on the record, shown apart.
# "A" is every graded tennis side with a price, listed or not (tennis.json's own "A" row).
LISTS = {
    "nfl": [("V", "Value"), ("T", "Top 25 Surest")],
    "nba": [("V", "Value (overs, 30-60¢)"), ("Vpre", "Value, old rule (ended)"), ("T", "Top 25 Surest")],
    "nhl": [("V", "Value"), ("T", "Top 25 Surest")],
    "mlb": [("V", "Value (unders only)"), ("Vpre", "Value overs (ended)"), ("T", "Top 25 Surest")],
    "tennis": [("V", "Value"), ("T", "Top 25 Surest"), ("A", "Every priced side")],
}
BOTD_SLOTS = [("value", "Value Shot"), ("lock", "Safe Pick")]
UNCHECKED = ("nhl", "mlb")    # the boards whose records leave out depth.unchecked picks (as edge_report.graded does)
# Boards whose own record has no price-move numbers. Tennis: most of its early Value picks were first
# recorded at a 95-97c price that can't have been real (depth.real_price), so a "move" from it means nothing.
NO_MOVE = ("tennis",)


def rows(sport, doc):
    """A sport's live picks that hit or missed, as small dicts: {"day" (ET), "win", "prob",
    "price" (a fraction, None when there was none or it can't have been real), "tags" (the lists
    it counts in), "mv" (price move in cents, first recording to last, or None)}."""
    out = []
    cols = doc.get("cols") or []
    cents = 100.0 if sport == "nfl" else 1.0      # picks.json keeps prices in cents
    for row in doc.get("picks") or []:
        p = dict(zip(cols, row))
        if p.get("src") != "live" or p.get("res") not in ("hit", "miss"):
            continue
        if sport in UNCHECKED and depth.unchecked(p):
            continue
        t = parse_start(p.get("start"))
        day = t.astimezone(ET).date().isoformat() if t else p.get("date")   # NFL dates are already ET
        if not day:
            continue
        tags = list(p.get("lists") or "")
        if not build_today.value_fits(sport, p):   # MLB unders only, NBA overs 30-60c: older Value picks show apart
            tags = ["Vpre" if x == "V" else x for x in tags]
        if sport == "tennis":
            tags.append("A")
        price = p["price"] / cents if p.get("price") and depth.real_price(p) else None
        mv = None
        if sport not in NO_MOVE and p.get("px0") is not None and p.get("pxc") is not None:
            mv = round((p["pxc"] - p["px0"]) * 100.0 / cents, 1)
        out.append({"day": str(day), "win": p["res"] == "hit", "prob": cap(p.get("prob")), "price": price,
                    "tags": tags, "mv": mv})
    return out


def units(r):
    """What a 1-unit bet on a graded row returned: 1/price - 1 on a win, -1 on a loss, nothing without a real price."""
    if not r.get("price"):
        return None
    return (1.0 / r["price"] - 1) if r["win"] else -1.0


def stats(rs):
    """One list's record over the rows given (see the module docstring)."""
    said = [r["prob"] for r in rs if r.get("prob") is not None]
    bets = [u for u in map(units, rs) if u is not None]
    mv = [r["mv"] for r in rs if r.get("mv") is not None]
    return {"n": len(rs), "hit": sum(1 for r in rs if r["win"]),
            "said": round(sum(said) / len(said), 4) if said else None,
            "priced": len(bets), "units": round(sum(bets), 2),
            "roi": round(sum(bets) / len(bets), 4) if bets else None,
            "clvN": len(mv), "clvUp": sum(1 for m in mv if m >= 1), "clvDn": sum(1 for m in mv if m <= -1),
            "clv": round(sum(mv) / len(mv), 1) if mv else None}


def weekly(rs):
    """Units over time: [[Monday of the week, units won or lost so far, priced bets that week], ...],
    one point per week that had a priced bet, oldest first."""
    per = {}
    for r in rs:
        u = units(r)
        if u is None:
            continue
        try:
            d = datetime.date.fromisoformat(r["day"])
        except ValueError:
            continue
        w = per.setdefault((d - datetime.timedelta(days=d.weekday())).isoformat(), [0.0, 0])
        w[0] += u
        w[1] += 1
    out, total = [], 0.0
    for monday in sorted(per):
        total += per[monday][0]
        out.append([monday, round(total, 2), per[monday][1]])
    return out


def list_block(tag, name, rs, since):
    return {"tag": tag, "name": name, "all": stats(rs), "d30": stats([r for r in rs if r["day"] >= since]),
            "weeks": weekly(rs)}


def sport_block(sport, doc, since):
    rs = rows(sport, doc)
    n, first = build_today.graded(doc)
    return {"sport": sport, "name": NAMES.get(sport, sport.upper()), "page": f"{sport}.html",
            "test": sport in NOT_FEATURED, "graded": n, "since": first,
            "lists": [list_block(tag, name, [r for r in rs if tag in r["tags"]], since) for tag, name in LISTS[sport]],
            "calib": build_today.calibration([(sport, doc)]), "fair": build_today.fair_weight([(sport, doc)])}


def botd_blocks(doc, since):
    """Pick of the Day's two slots from botd.json, each a 1-unit bet at the price it was frozen at.
    Voids and pushes are left out, as in botd.json's own record (their counts ride along).
    A missing or misshapen botd.json gives two empty slots."""
    out = []
    doc = doc if isinstance(doc, dict) else {}
    days = doc.get("days") if isinstance(doc.get("days"), list) else []
    record = doc.get("record") if isinstance(doc.get("record"), dict) else {}
    for slot, name in BOTD_SLOTS:
        rs = []
        for d in days:
            p = d.get(slot) if isinstance(d, dict) else None
            if not isinstance(p, dict) or p.get("res") not in ("hit", "miss") or not d.get("date"):
                continue
            try:
                price = float(p["price"]) if p.get("price") else None
            except (TypeError, ValueError):
                price = None
            rs.append({"day": str(d["date"]), "win": p["res"] == "hit", "prob": cap(p.get("prob")),
                       "price": price / 100.0 if price and price > 1 else price, "tags": [slot], "mv": None})
        b = list_block(slot, name, rs, since)
        rec = record.get(slot) if isinstance(record.get(slot), dict) else {}
        b["push"], b["void"] = rec.get("push") or 0, rec.get("void") or 0
        out.append(b)
    return out


def losing(sports, botd):
    """Every list that is down units, all-time or over the last 30 days, worst first.
    Tennis's "every priced side" row isn't a list anyone was pointed to, so it's never named."""
    out = []
    for name, sport, lists in [(s["name"], s["sport"], s["lists"]) for s in sports] + [("Pick of the Day", "botd", botd)]:
        for b in lists:
            if b["tag"] == "A":
                continue
            a, d = b["all"], b["d30"]
            if (a["priced"] and a["units"] < 0) or (d["priced"] and d["units"] < 0):
                out.append({"sport": sport, "name": name, "list": b["name"], "units": a["units"], "priced": a["priced"],
                            "roi": a["roi"], "d30": d["units"] if d["priced"] else None})
    # down all-time first, by units; then the lists that are up overall but down this month, by the month
    return sorted(out, key=lambda x: (0, x["units"], x["d30"] or 0) if x["priced"] and x["units"] < 0 else (1, x["d30"], x["units"]))


def build(docs, botd_doc, now):
    """record.json's contents from [(sport, picks doc), ...] and botd.json's."""
    today = now.astimezone(ET).date()
    since = (today - datetime.timedelta(days=WINDOW - 1)).isoformat()    # 30 days, today included
    sports, good = [], []
    for sport, doc in docs:
        if sport not in LISTS:
            continue
        try:
            sports.append(sport_block(sport, doc, since))
        except Exception as e:  # noqa: BLE001 - one unreadable picks file costs that sport, not the page
            print(f"  {sport}: picks file can't be read ({type(e).__name__}: {e}), skipped")
            continue
        good.append((sport, doc))
    featured = [(sport, doc) for sport, doc in good if sport not in NOT_FEATURED]
    botd = botd_blocks(botd_doc, since)
    firsts = [s["since"] for s in sports if s["since"] and not s["test"]]
    return {"gen": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "day": today.isoformat(), "window": WINDOW,
            "graded": sum(s["graded"] for s in sports if not s["test"]), "since": min(firsts) if firsts else None,
            "sports": sports, "calib": build_today.calibration(featured), "fair": build_today.fair_weight(featured),
            "botd": botd, "losing": losing(sports, botd)}


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    docs = []
    for sport, _, picks_file, _ in SPORTS:
        doc = load(picks_file)
        if not isinstance(doc, dict) or "cols" not in doc or "picks" not in doc:
            print(f"  {sport}: {picks_file} missing or unreadable, skipped")
            continue
        docs.append((sport, doc))
    if not docs:
        print("record: no picks files, nothing written")
        return
    rec = build(docs, load(BOTD), now)
    if not rec["sports"]:
        print("record: no readable picks files, nothing written")
        return
    # "gen" is when the numbers last changed, so a pass that changes nothing rewrites nothing.
    old = load(OUT)
    if isinstance(old, dict) and old.get("gen") and {**old, "gen": None} == {**rec, "gen": None}:
        rec["gen"] = old["gen"]
    payload = json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
    try:
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            template = f.read()
    except OSError:
        template = ""
    wrote = [OUT, PAGE]
    if "__RECORDDATA__" not in template:
        print(f"  WARNING: {TEMPLATE} missing or without its __RECORDDATA__ placeholder, not writing {PAGE}")
        wrote = [OUT]
    else:
        with open(PAGE + ".tmp", "w", encoding="utf-8") as f:
            f.write(template.replace("__RECORDDATA__", payload.replace("</", "<\\/")))
        os.replace(PAGE + ".tmp", PAGE)
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(OUT + ".tmp", OUT)
    for s in rec["sports"]:
        print(f"  {s['sport']}: " + ", ".join(f"{b['name']} {b['all']['hit']}/{b['all']['n']} {b['all']['units']:+.2f}u" for b in s["lists"]))
    print(f"record: {len(rec['sports'])} sport(s), {len(rec['losing'])} list(s) down units, wrote {" and ".join(wrote)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 - the record page must never fail the deploy
        print(f"record: failed ({type(e).__name__}: {e}), previous files left in place")
        sys.exit(0)
