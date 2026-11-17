"""Static checks on the service worker (sw.js): what it precaches exists, its app.js/app.css versions
match the pages', and it never touches the team dashboard. Standard library only."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


SW = read("sw.js")
# hand-written pages and templates that load app.js (the generated pages follow their templates)
PAGES = ["index.html", "record_template.html", "template.html", "tennis_template.html",
         "nfl_template.html", "nba_template.html", "nhl_template.html", "mlb_template.html"]
PAGES = [p for p in PAGES if os.path.exists(os.path.join(ROOT, p))]


def shell():
    m = re.search(r"const SHELL = \[(.*?)\];", SW, re.S)
    return re.findall(r"'([^']+)'", m.group(1))


class ServiceWorker(unittest.TestCase):
    def test_precache_files_exist(self):
        for url in shell():
            path = url.split("?")[0].lstrip("/") or "index.html"
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), url)

    def test_versions_match_pages(self):
        urls = shell()
        for asset in ("app.js", "app.css"):
            sw_v = [u.split("?v=")[1] for u in urls if u.split("?")[0] == "/" + asset]
            self.assertEqual(len(sw_v), 1, asset + " precached once, with ?v=")
            for page in PAGES:
                found = re.findall(re.escape(asset) + r"\?v=(\w+)", read(page))
                self.assertTrue(found, page + " loads " + asset)
                self.assertEqual(set(found), {sw_v[0]}, f"{page}: {asset}?v= differs from sw.js")

    def test_version_tracks_app_js(self):
        # VERSION names the caches; it moves with app.js so a new shell clears the old caches
        v = re.search(r"const VERSION = '(\w+)'", SW).group(1)
        self.assertIn(f"/app.js?v={v}'", SW)

    def test_offline_page(self):
        html = read("offline.html")
        self.assertIn("noindex", html)
        self.assertIn("'/offline.html'", SW)
        # served under any URL, so its own links must be absolute
        for ref in re.findall(r'(?:href|src)="([^"]+)"', html):
            self.assertTrue(ref.startswith("/"), ref)

    def test_never_team_or_other_sites(self):
        self.assertIn("p.startsWith('/team/')", SW)
        self.assertIn("u.origin !== self.location.origin", SW)
        self.assertIn("req.method !== 'GET'", SW)
        self.assertFalse(any(u.startswith("/team/") for u in shell()))
        self.assertIn("if (req.cache === 'no-store') return;", SW)   # live-price fetches stay uncached
        self.assertNotRegex(SW, r"https?://")   # no other site named anywhere
        self.assertFalse(re.search(r"const KILL = true", SW), "kill switch left on")

    def test_pages_and_data_network_first(self):
        # HTML and .json come from the network whenever it answers; the saved copy is the fallback
        self.assertRegex(SW, r"p\.endsWith\('\.html'\) \|\| p\.endsWith\('\.json'\)\)?[^\n]*return 'net'")
        self.assertIn("if (first.res) { fromCache.delete(req.url); return first.res; }", SW)

    def test_registration_guarded(self):
        app = read("app.js")
        self.assertIn("sw.register('/sw.js')", app)
        self.assertIn("location.pathname.startsWith('/team/')", app)
        self.assertIn("nosw", app)

    def test_manifest(self):
        m = json.loads(read("site.webmanifest"))
        for k in ("id", "scope", "start_url", "display", "icons"):
            self.assertIn(k, m)
        self.assertEqual(m["display"], "standalone")


if __name__ == "__main__":
    unittest.main()
