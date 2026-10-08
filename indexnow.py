"""
Prop Streak Lab — tell Bing which pages to re-read (IndexNow).

IndexNow (indexnow.org) is how a site tells Bing, and the other engines that share it (Yandex,
Seznam, Naver...), that its pages changed, instead of waiting for them to come back on their own.
This posts every URL in sitemap.xml with the site's key; the engines confirm the site is ours by
fetching the key file, https://propstreaklab.com/<KEY>.txt, which holds the key.

Run once a day by .github/workflows/indexnow.yml. The boards change every few minutes, but
IndexNow asks for changed pages, not a ping on every update. Google doesn't use IndexNow (that's
Search Console). Standard library only.
"""
import json
import re
import sys
import urllib.error
import urllib.request

HOST = "propstreaklab.com"
KEY = "0c458d186b9ad4232ca6684f6709bf94"
ENDPOINT = "https://api.indexnow.org/indexnow"


def sitemap_urls(path="sitemap.xml"):
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", open(path, encoding="utf-8").read())


def main():
    urls = [u for u in sitemap_urls() if u.startswith(f"https://{HOST}/")][:10000]
    body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt",
                       "urlList": urls}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            # 200: received; 202: received, key still being checked
            print(f"IndexNow: HTTP {r.status}, {len(urls)} URL(s) submitted")
    except urllib.error.HTTPError as e:
        print(f"IndexNow: HTTP {e.code} ({e.read()[:300].decode('utf-8', 'replace')})")
        sys.exit(1)


if __name__ == "__main__":
    main()
