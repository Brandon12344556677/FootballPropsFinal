"""
Prop Streak Lab — daily site checks: can search engines read the site, and do the sign-up links pay?

Runs once a day in its own workflow (.github/workflows/site_checks.yml), from the outside:

  - search:   every URL in the live sitemap.xml loads; each sitemap page has a title, a meta
              description, one <h1>, a canonical link to itself and no "noindex"; robots.txt
              allows crawling and points at the sitemap; links on the hand-written pages
              (home, methodology, guides, best props, games, legal) all lead somewhere.
              (indexnow.yml already sends every sitemap URL to Bing once a day.)
  - signup:   the Polymarket referral page still shows the PROPSTREAKLAB code (so sign-ups are
              still credited to the site); the Kalshi referral link still answers (Kalshi often
              blocks servers, which is noted, not alerted); every page and script that
              carries a sign-up link carries the same code.

Problems go into one GitHub issue ("Site checks: ..."), updated as they change and closed
when everything passes (watchdog.report). Smaller search notes (a title that's long for
Google, a short description) go to the run's summary only.

    python site_checks.py     check and print; with GITHUB_TOKEN set, also open/update/close the issue

Standard library only.
"""
import concurrent.futures
import datetime
import os
import re
import sys
import urllib.parse

import watchdog
from watchdog import SITE, fetch

TITLE = "Site checks: search engines or sign-up links need a look"
MARK = "<!-- site-checks -->"
POLY_REF = "https://polymarket.us/join/propstreaklab"
POLY_CODE = "PROPSTREAKLAB"
KALSHI_REF_ID = "4373e9f9-0304-498c-8ca7-fccd3714b808"
KALSHI_REF = f"https://kalshi.com/sign-up/?referral={KALSHI_REF_ID}"
HAND_PAGES = ["/", "/methodology.html", "/guides/", "/guides/what-is-a-player-prop.html",
              "/guides/polymarket-and-kalshi.html", "/guides/how-to-read-the-model.html",
              "/best/", "/games/", "/privacy.html", "/terms.html", "/cookies.html"]
REF_CARRIERS = ["/", "/app.js", "/guides/polymarket-and-kalshi.html"]   # every one carries both sign-up links
NOINDEX_OK = re.compile(r"^/(team|p)/")
HINTS = {
    "search": "Search engines can't read or reach a page. Generated pages (players/, games/, best/) come from "
              "their builder (build_players.py, build_games.py); hand-written ones from the last PR that changed them.",
    "signup": "A sign-up link no longer shows the code or the offer the site promises. Check the link in a browser; "
              "if Polymarket or Kalshi changed the offer, update the wording in index.html, app.js (REF), the guides "
              "and post_daily.py.",
}
WORKERS = 8

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)
CANON_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]*)"', re.I)
NOINDEX_RE = re.compile(r'<meta\s+name="robots"\s+content="[^"]*noindex', re.I)
H1_RE = re.compile(r"<h1[\s>]", re.I)
HREF_RE = re.compile(r'<a\s[^>]*href="([^"#]+)', re.I)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def path_of(url):
    return urllib.parse.urlsplit(url).path or "/"


def page_seo(path, html):
    """(problems, notes) for one page's search basics."""
    problems, notes = [], []
    t = TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", t.group(1)).strip() if t else ""
    d = DESC_RE.search(html)
    desc = d.group(1).strip() if d else ""
    canon = CANON_RE.search(html)
    if not title:
        problems.append("no <title>")
    elif len(title) > 70:
        notes.append(f"title is {len(title)} characters (Google shows about 60)")
    if not desc:
        problems.append("no meta description")
    elif len(desc) < 50:
        notes.append(f"meta description is only {len(desc)} characters")
    if not H1_RE.search(html):
        problems.append("no <h1> heading")
    if NOINDEX_RE.search(html) and not NOINDEX_OK.match(path):
        problems.append('marked "noindex", so Google drops it, though it\'s in the sitemap')
    if canon is None:
        notes.append("no canonical link")
    elif path_of(canon.group(1)).rstrip("/") != path.rstrip("/") and not NOINDEX_OK.match(path):
        problems.append(f"its canonical link points somewhere else ({canon.group(1)})")
    return problems, notes


def check_search():
    out, notes = {}, []
    st, robots = fetch(f"{SITE}/robots.txt")
    if st != 200:
        out["search: robots.txt"] = f"{SITE}/robots.txt didn't load ({st or robots})."
    else:
        if re.search(r"(?im)^disallow:\s*/\s*$", robots):
            out["search: robots.txt"] = "robots.txt tells search engines to stay off the whole site (Disallow: /)."
        if "sitemap.xml" not in robots:
            notes.append("robots.txt doesn't point at sitemap.xml")
    st, sm = fetch(watchdog.bust("/sitemap.xml"))
    if st != 200:
        out["search: sitemap"] = f"{SITE}/sitemap.xml didn't load ({st or sm})."
        return out, notes, 0
    urls = list(dict.fromkeys(LOC_RE.findall(sm)))
    if not urls:
        out["search: sitemap"] = "sitemap.xml lists no pages."
        return out, notes, 0

    def one(url):
        st, html = fetch(url, tries=2)
        return url, st, html
    pages = {}
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        for url, st, html in ex.map(one, urls):
            path = path_of(url)
            if st != 200:
                out[f"search: {path}"] = f"{url} is in the sitemap but returns {st or html}."
                continue
            pages[path] = html
            probs, n = page_seo(path, html)
            if probs:
                out[f"search: {path}"] = f"{url}: " + "; ".join(probs) + "."
            notes += [f"{path}: {x}" for x in n]
    # links on the hand-written pages
    links = {}
    for path in HAND_PAGES:
        html = pages.get(path)
        if html is None:
            st, html = fetch(watchdog.bust(path))
            if st != 200:
                out[f"search: {path}"] = f"{SITE}{path} didn't load ({st or html})."
                continue
        for href in HREF_RE.findall(html):
            full = urllib.parse.urljoin(SITE + path, href)
            if full.startswith(SITE) and "${" not in href:
                links.setdefault(full.split("?")[0], path)
    known = {SITE + p for p in pages} | {u.split("?")[0] for u in urls}
    todo = [u for u in links if u not in known]
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as ex:
        for url, st, _ in ex.map(one, todo):
            if st != 200 and st is not None:
                out[f"search: link {path_of(url)}"] = f"{SITE}{links[url]} links to {path_of(url)}, which returns {st}."
    return out, notes, len(urls)


def check_signup():
    out, notes = {}, []
    st, html = fetch(POLY_REF)
    if st != 200:
        out["signup: polymarket"] = f"The Polymarket sign-up link {POLY_REF} returns {st or html}."
    else:
        t = TITLE_RE.search(html)
        title = re.sub(r"\s+", " ", t.group(1)) if t else ""
        if POLY_CODE not in title.upper():
            out["signup: polymarket"] = (f"The Polymarket sign-up page no longer shows the code {POLY_CODE} "
                                         f"(its title is \"{title.strip()[:120]}\"): new users may not be credited to you.")
    st, _ = fetch(KALSHI_REF, tries=2)
    if st in (403, 429, None):
        notes.append(f"Kalshi's sign-up link couldn't be checked from a server ({st or 'no answer'}); Kalshi blocks most bots.")
    elif st >= 400:
        out["signup: kalshi"] = f"The Kalshi sign-up link returns {st}."
    for path in REF_CARRIERS:
        st, text = fetch(watchdog.bust(path))
        if st != 200:
            continue          # a page that doesn't load is the watchdog's job
        missing = [name for name, needle in (("Polymarket code", "join/propstreaklab"), ("Kalshi referral", KALSHI_REF_ID))
                   if needle not in text]
        if missing:
            out[f"signup: {path}"] = f"{SITE}{path} no longer carries the {' or the '.join(missing)} link."
    return out, notes


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    search, notes, n_urls = check_search()
    signup, notes2 = check_signup()
    problems = {**search, **signup}
    notes += notes2
    for msg in problems.values():
        print(f"::warning title=Site checks::{msg}")
    for n in notes:
        print(f"  note: {n}")
    print(f"  site checks: {n_urls} sitemap page(s), {len(problems)} problem(s), {len(notes)} note(s)")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Site checks\n\n" + ("\n".join(f"- {m}" for m in problems.values()) or "Everything passes.") +
                    ("\n\n**Notes**\n\n" + "\n".join(f"- {n}" for n in notes[:60]) if notes else "") + "\n")
    token = os.environ.get("GITHUB_TOKEN")
    if token and watchdog.report(problems, now, token, title=TITLE, mark=MARK, hints=HINTS, who="The daily site check"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
