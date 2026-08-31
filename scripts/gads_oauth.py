"""Generate the Google Ads API refresh token, interactively.

    uv run python scripts/gads_oauth.py

Reads `client_id` and `client_secret` from `google-ads.yaml`, opens a browser for
consent, and PRINTS the refresh token for you to paste back into that file. It
deliberately does not write the file itself: this repo's rule is that secrets are
edited by a human, and a script that rewrites a credentials file is one bug away
from destroying the other values in it.

Run this again whenever the refresh token stops working. If the OAuth app is still
in TESTING status, that will be every 7 days -- Google expires refresh tokens for
testing-status external apps. Publishing the app to Production removes that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from google_auth_oauthlib.flow import InstalledAppFlow

#: The Google Ads API's single scope. Read-only access is not separately scoped:
#: `adwords` is all-or-nothing, which is worth knowing before you consent.
SCOPES = ["https://www.googleapis.com/auth/adwords"]
CONFIG = Path(__file__).resolve().parent.parent / "google-ads.yaml"


def main() -> int:
    if not CONFIG.exists():
        print(f"missing {CONFIG.name} — copy google-ads.yaml.example to it first")
        return 1

    cfg = yaml.safe_load(CONFIG.read_text()) or {}
    client_id = (cfg.get("client_id") or "").strip()
    client_secret = (cfg.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        print(f"set client_id and client_secret in {CONFIG.name} first")
        print("(Google Cloud Console -> Clientes -> your Desktop app client)")
        return 1

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    # A local server beats copy-pasting a code: Google deprecated the out-of-band
    # flow, and the desktop client type expects a loopback redirect.
    creds = flow.run_local_server(port=0, prompt="consent")

    if not creds.refresh_token:
        print("\nno refresh token returned. Re-run; consent must be granted fresh.")
        return 1

    print("\n" + "=" * 68)
    print("Paste this into google-ads.yaml as `refresh_token`:\n")
    print(creds.refresh_token)
    print("=" * 68)
    print("\nThat value is a credential. It is printed here and written nowhere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
