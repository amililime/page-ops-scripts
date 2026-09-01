"""
mlx_profiles.py

Loads and validates the Multilogin folder_id/profile_id mapping that lives
in mlx_profiles.json, separate from the account inventory spreadsheet.

Expected JSON shape:

    {
      "EMI_AUTO_111": {"folder_id": "f-abc123", "profile_id": "p-xyz789"},
      "EMI_AUTO_112": {"folder_id": "f-abc123", "profile_id": "p-qwe456"},
      ...
    }

Usage (e.g. at the top of login.py / post.py, before a batch run):

    from mlx_profiles import load_profile_map, validate_against

    account_ids = [row["account_id"] for row in validated_accounts]  # from script.py
    profile_map = load_profile_map("mlx_profiles.json")
    errors = validate_against(account_ids, profile_map)

    if errors:
        for e in errors:
            print(f"MLX MAPPING ERROR: {e}")
        raise SystemExit(1)  # fail fast, before opening a single browser

This is deliberately the JSON-file equivalent of "extend script.py's
validation to cover the new columns" from the spreadsheet-columns option:
same fail-fast guarantee, just checking two files agree instead of checking
two columns in one file.
"""

from __future__ import annotations

import json
from pathlib import Path


class ProfileMapError(RuntimeError):
    """Raised when mlx_profiles.json is missing, malformed, or unreadable."""


def load_profile_map(path: str | Path) -> dict[str, dict[str, str]]:
    path = Path(path)
    if not path.exists():
        raise ProfileMapError(f"{path} does not exist")

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProfileMapError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileMapError(f"{path} must be a JSON object mapping account_id -> {{folder_id, profile_id}}")

    return data


def validate_against(
    account_ids: list[str],
    profile_map: dict[str, dict[str, str]],
    *,
    warn_on_orphans: bool = True,
) -> list[str]:
    """
    Returns a list of human-readable error strings. Empty list = all good.

    - Every account_id from the spreadsheet must have an entry in profile_map.
    - Each entry must have non-empty folder_id and profile_id.
    - (Optional) entries in profile_map with no matching account are reported
      as warnings, not errors -- could be an account that was removed from
      the sheet but not yet cleaned up here, not necessarily a bug.
    """
    errors: list[str] = []
    account_id_set = set(account_ids)

    for account_id in account_ids:
        entry = profile_map.get(account_id)
        if entry is None:
            errors.append(f"'{account_id}' has no entry in mlx_profiles.json")
            continue

        folder_id = entry.get("folder_id", "").strip()
        profile_id = entry.get("profile_id", "").strip()

        if not folder_id:
            errors.append(f"'{account_id}' is missing folder_id")
        if not profile_id:
            errors.append(f"'{account_id}' is missing profile_id")

    if warn_on_orphans:
        orphans = set(profile_map) - account_id_set
        for orphan in sorted(orphans):
            print(f"MLX MAPPING WARNING: '{orphan}' is in mlx_profiles.json but not in the account sheet")

    return errors
