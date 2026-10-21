"""
One-time TikTok sign-in for tiktok_post.py: prints the refresh token to save as the
TIKTOK_REFRESH_TOKEN repository secret. Run it on your own computer:

    python tiktok_auth.py

It asks for the app's client key and secret (developers.tiktok.com → the app → Credentials;
the Sandbox's while the app runs from its Sandbox). Input is hidden and nothing is saved.
TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in the environment are used instead when set.

1. It prints a TikTok link. Open it, sign in as @propstreaklab and allow access.
2. TikTok sends you to propstreaklab.com/tiktok/callback.html, which shows a code. Paste it here.
3. Save the refresh token it prints in GitHub: Settings → Secrets and variables → Actions →
   New repository secret, named TIKTOK_REFRESH_TOKEN. Don't paste it anywhere else.

The token lasts a year. Run this again when the team dashboard's Social tab says to reconnect
TikTok. Standard library only.
"""
import getpass
import os
import secrets
import sys
import urllib.parse

import tiktok_post

REDIRECT = "https://propstreaklab.com/tiktok/callback.html"   # must match the app's Login Kit redirect URI exactly
SCOPES = "user.info.basic,video.upload"                       # video.upload: drafts to the inbox, photos and videos


def main():
    key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip() or getpass.getpass("TikTok client key (hidden): ").strip()
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip() or getpass.getpass("TikTok client secret (hidden): ").strip()
    if not key or not secret:
        sys.exit("Need the client key and secret (developers.tiktok.com → the app → Credentials).")
    state = secrets.token_urlsafe(12)
    q = urllib.parse.urlencode({"client_key": key, "scope": SCOPES, "response_type": "code",
                                "redirect_uri": REDIRECT, "state": state})
    print("1. Open this link, sign in as @propstreaklab and allow access:\n\n   "
          f"https://www.tiktok.com/v2/auth/authorize/?{q}\n")
    print(f"   The page you land on should show the check word {state!r}. If it doesn't, start over.\n")
    code = input("2. Paste the code from that page: ").strip()
    j = tiktok_post.http_json(f"{tiktok_post.API}/v2/oauth/token/",
                              {"client_key": key, "client_secret": secret, "code": code,
                               "grant_type": "authorization_code", "redirect_uri": REDIRECT}, form=True)
    if not j.get("refresh_token"):
        sys.exit(f"TikTok said no: {j.get('error')} {j.get('error_description', '')}")
    if "video.upload" not in (j.get("scope") or ""):
        print(f"Warning: TikTok granted only {j.get('scope')!r}; the drafts need video.upload (check the app's products).")
    days = int(j.get("refresh_expires_in") or 0) // 86400
    print(f"\n3. Save this as the TIKTOK_REFRESH_TOKEN repository secret (good for {days} days):\n\n   {j['refresh_token']}\n")


if __name__ == "__main__":
    main()
