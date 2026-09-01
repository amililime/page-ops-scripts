"""
multilogin_client.py

Thin client for starting a Multilogin browser profile and getting back a
local CDP port that Playwright can connect to with connect_over_cdp().

Drop this file next to login.py / post.py / session_manager.py.

Usage:

    from multilogin_client import MultiloginClient

    mlx = MultiloginClient(
        email=os.environ["MLX_EMAIL"],
        password=os.environ["MLX_PASSWORD"],
    )
    mlx.sign_in()
    port = mlx.start_profile(folder_id, profile_id)

    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()

Notes:

- These endpoints (api.multilogin.com for auth, launcher.mlx.yt:45001 for
  starting/stopping profiles) come from Multilogin X's current docs. If
  start_profile() 404s or 401s, you may be on an older Multilogin 6/7 setup
  that uses a different local API (check app.properties on your machine).
- Credentials (MLX_EMAIL / MLX_PASSWORD) should come from environment
  variables or a secrets manager -- never hardcode them.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

AUTH_BASE = "https://api.multilogin.com"
LAUNCHER_BASE = "https://launcher.mlx.yt:45001"

_PORT_CACHE = Path(tempfile.gettempdir()) / "mlx_running_ports.json"


def _load_port_cache() -> dict:
    try:
        return json.loads(_PORT_CACHE.read_text())
    except Exception:
        return {}


def _save_port_cache(profile_id: str, port: int) -> None:
    cache = _load_port_cache()
    cache[profile_id] = port
    _PORT_CACHE.write_text(json.dumps(cache))


def _clear_port_cache(profile_id: str) -> None:
    cache = _load_port_cache()
    cache.pop(profile_id, None)
    _PORT_CACHE.write_text(json.dumps(cache))


class MultiloginError(RuntimeError):
    """Raised when a Multilogin API call fails."""


@dataclass
class StartedProfile:
    profile_id: str
    port: int

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class MultiloginClient:
    """
    Minimal wrapper around the two calls this workflow actually needs:
    sign in once, then start a profile per account.
    """

    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._token: str | None = None

    def sign_in(self) -> None:
        """Authenticate and cache the bearer token for subsequent calls."""
        password_hash = hashlib.md5(self._password.encode()).hexdigest()

        resp = requests.post(
            f"{AUTH_BASE}/user/signin",
            json={"email": self._email, "password": password_hash},
            timeout=15,
        )
        if not resp.ok:
            raise MultiloginError(f"Multilogin sign-in failed ({resp.status_code}): {resp.text}")

        try:
            self._token = resp.json()["data"]["token"]
        except (KeyError, ValueError) as exc:
            raise MultiloginError(f"Unexpected sign-in response shape: {resp.text}") from exc

        log.info("Signed in to Multilogin")

    def start_profile(
        self,
        folder_id: str,
        profile_id: str,
        headless: bool = False,
    ) -> StartedProfile:
        """
        Start a Multilogin profile and return the local port Playwright
        should connect to via connect_over_cdp().
        """
        if not self._token:
            raise MultiloginError("Call sign_in() before start_profile()")

        url = (
            f"{LAUNCHER_BASE}/api/v2/profile/f/{folder_id}/p/{profile_id}/start"
            f"?automation_type=playwright&headless_mode={'true' if headless else 'false'}"
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        if not resp.ok:
            # If already running, fetch the port from the active profile status
            if "PROFILE_ALREADY_RUNNING" in resp.text:
                return self._get_running_profile(profile_id, folder_id, headless)
            raise MultiloginError(
                f"Failed to start profile {profile_id} ({resp.status_code}): {resp.text}"
            )

        try:
            port = resp.json()["data"]["port"]
        except (KeyError, ValueError) as exc:
            raise MultiloginError(f"Unexpected start-profile response shape: {resp.text}") from exc

        log.info("Started Multilogin profile %s on port %s", profile_id, port)
        _save_port_cache(profile_id, port)
        return StartedProfile(profile_id=profile_id, port=port)

    def _get_running_profile(self, profile_id: str, folder_id: str, headless: bool) -> StartedProfile:
        """Reconnect to an already-running profile using the cached port, or restart it."""
        import time

        cached_port = _load_port_cache().get(profile_id)
        if cached_port:
            log.info("Profile %s already running — reconnecting on cached port %s", profile_id, cached_port)
            return StartedProfile(profile_id=profile_id, port=cached_port)

        log.info("Profile %s already running — no cached port, stopping and restarting...", profile_id)
        self.stop_profile(profile_id)
        time.sleep(2)

        url = (
            f"{LAUNCHER_BASE}/api/v2/profile/f/{folder_id}/p/{profile_id}/start"
            f"?automation_type=playwright&headless_mode={'true' if headless else 'false'}"
        )
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )
        if not resp.ok:
            raise MultiloginError(
                f"Failed to restart profile {profile_id} ({resp.status_code}): {resp.text}"
            )
        try:
            port = resp.json()["data"]["port"]
        except (KeyError, ValueError) as exc:
            raise MultiloginError(f"Unexpected restart response shape: {resp.text}") from exc

        log.info("Restarted profile %s on port %s", profile_id, port)
        _save_port_cache(profile_id, port)
        return StartedProfile(profile_id=profile_id, port=port)

    def stop_profile(self, profile_id: str) -> None:
        """Stop a running profile. Logs a warning rather than raising so it's safe in a finally block."""
        if not self._token:
            return
        try:
            resp = requests.get(
                f"{LAUNCHER_BASE}/api/v1/profile/stop/p/{profile_id}",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=15,
            )
            if not resp.ok:
                log.warning("stop_profile(%s) returned %s: %s", profile_id, resp.status_code, resp.text)
            else:
                log.info("Stopped Multilogin profile %s", profile_id)
                _clear_port_cache(profile_id)
        except requests.RequestException as exc:
            log.warning("stop_profile(%s) request failed: %s", profile_id, exc)
