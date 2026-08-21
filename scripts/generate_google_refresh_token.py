#!/usr/bin/env python3
"""Helper script to generate a permanent GOOGLE_REFRESH_TOKEN for MediCORE Gmail API integration.

To prevent the refresh token from expiring after 7 days:
1. Go to Google Cloud Console (https://console.cloud.google.com/) -> APIs & Services -> OAuth consent screen.
2. Under "Publishing status", click "PUBLISH APP" to switch status to "In production".
3. Run this script to generate your permanent GOOGLE_REFRESH_TOKEN.
"""

import os
import sys
import urllib.parse
import httpx

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main():
    print("=" * 70)
    print(" MediCORE - Google OAuth Refresh Token Generator")
    print("=" * 70)
    print("\n[!IMPORTANT NOTICE ABOUT 7-DAY EXPIRATION]:")
    print(" If your OAuth Consent Screen in Google Cloud Console is in 'Testing' mode,")
    print(" Google will automatically expire refresh tokens every 7 days.")
    print(" To make the refresh token permanent:")
    print(" 1. Go to https://console.cloud.google.com/apis/credentials/consent")
    print(" 2. Set 'Publishing status' to 'In production' (click 'PUBLISH APP').")
    print("    (You do NOT need to complete verification for your own internal admin account)\n")

    client_id = os.getenv("GOOGLE_CLIENT_ID") or input("Enter GOOGLE_CLIENT_ID: ").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or input("Enter GOOGLE_CLIENT_SECRET: ").strip()

    if not client_id or not client_secret:
        print("[ERROR] GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required.")
        sys.exit(1)

    auth_params = {
        "client_id": client_id,
        "redirect_uri": "https://developers.google.com/oauthplayground",
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(auth_params)

    print("\n" + "-" * 70)
    print("STEP 1: Open this URL in your web browser:")
    print("-" * 70)
    print(auth_url)
    print("-" * 70)
    print("\nSTEP 2: Log in with your Gmail account and grant permissions.")
    print("  (If you see 'Google hasn't verified this app', click 'Advanced' -> 'Go to ... (unsafe)')")
    print("  After authorizing, you will be redirected. Copy the 'code' parameter from the URL or screen.")
    print("-" * 70)

    auth_code = input("\nEnter the authorization code: ").strip()
    if not auth_code:
        print("[ERROR] No authorization code entered.")
        sys.exit(1)

    # Decode if user copied full URL or urlencoded string
    if "code=" in auth_code:
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(auth_code).query)
        if "code" in parsed:
            auth_code = parsed["code"][0]

    print("\nExchanging authorization code for permanent refresh token...")
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": "https://developers.google.com/oauthplayground",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        refresh_token = data.get("refresh_token")

        if not refresh_token:
            print("\n[WARNING] No refresh_token returned in response.")
            print("Response:", data)
            print("\nTip: Make sure you used prompt=consent and access_type=offline, or re-run the script.")
            return

        print("\n" + "=" * 70)
        print("SUCCESS! Your Permanent Google OAuth Refresh Token:")
        print("=" * 70)
        print(f"\nGOOGLE_REFRESH_TOKEN={refresh_token}\n")
        print("Add this value to your .env file in production and local environments.")
        print("=" * 70)

    except httpx.HTTPStatusError as e:
        print(f"\n[ERROR] Token exchange failed ({e.response.status_code}): {e.response.text}")
    except Exception as e:
        print(f"\n[ERROR] An error occurred: {e}")


if __name__ == "__main__":
    main()
