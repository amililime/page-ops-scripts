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
from mlx_profiles import discover_profiles

FOLDER_NAME = "BUFFALO FB"


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
    Discover profiles from Multilogin, sign in, start the named profile.
    Returns (MultiloginClient, StartedProfile).
    Caller must call client.stop_profile(started.profile_id) when done.
    """
    client = _client()
    profile_map = discover_profiles(client, FOLDER_NAME)

    if account_name not in profile_map:
        available = sorted(profile_map.keys())
        print(f"Error: account '{account_name}' not found in folder '{FOLDER_NAME}'.")
        print(f"Available: {available}")
        sys.exit(1)

    entry = profile_map[account_name]
    started = client.start_profile(entry["folder_id"], entry["profile_id"])
    return client, started
