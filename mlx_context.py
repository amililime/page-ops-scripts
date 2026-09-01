"""
Shared helper: sign into Multilogin, start a profile, and return
(client, started_profile) ready for connect_over_cdp().

Credentials come from environment variables MLX_EMAIL and MLX_PASSWORD.
Profile IDs come from mlx_profiles.json next to this file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from multilogin_client import MultiloginClient
from mlx_profiles import load_profile_map, validate_against

MLX_PROFILES_PATH = Path(__file__).parent / "mlx_profiles.json"


def _client() -> MultiloginClient:
    email = os.environ.get("MLX_EMAIL")
    password = os.environ.get("MLX_PASSWORD")
    if not email or not password:
        print("Error: MLX_EMAIL and MLX_PASSWORD environment variables must be set.")
        sys.exit(1)
    client = MultiloginClient(email=email, password=password)
    client.sign_in()
    return client


def start_profile_for(account_name: str):
    """
    Validate account against mlx_profiles.json, sign in, start the profile.
    Returns (MultiloginClient, StartedProfile).
    Caller must call client.stop_profile(started.profile_id) when done.
    """
    profile_map = load_profile_map(MLX_PROFILES_PATH)
    errors = validate_against([account_name], profile_map)
    if errors:
        for e in errors:
            print(f"MLX MAPPING ERROR: {e}")
        sys.exit(1)

    entry = profile_map[account_name]
    client = _client()
    started = client.start_profile(entry["folder_id"], entry["profile_id"])
    return client, started
