"""
Saves and loads browser cookies per account so repeated logins
use the saved session instead of going through the full login flow.

Sessions are stored in ./sessions/<account_name>.json
"""

import json
import os

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def session_path(account_name):
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    safe_name = account_name.replace("/", "_").replace(" ", "_")
    return os.path.join(SESSIONS_DIR, f"{safe_name}.json")


def save_session(account_name, cookies):
    path = session_path(account_name)
    with open(path, "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"Session saved: {path}")


def load_session(account_name):
    path = session_path(account_name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def delete_session(account_name):
    path = session_path(account_name)
    if os.path.exists(path):
        os.remove(path)
        print(f"Session deleted: {path}")
